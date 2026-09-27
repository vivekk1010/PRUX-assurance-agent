"""Playwright execution of allow-listed scenario steps with evidence capture."""
import json
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import Locator, sync_playwright

from agent.guardrails import mask_secrets, resolve_placeholders, scrub_zip
from agent.models import Step, StepResult, Target, UXIntent
from agent.tools.data import ReadOnlyDB, reconcile, CALCULATIONS
from agent.tools.figma_compare import compare_frame

SNAPSHOT_JS = """() => {
  const label = el => (el.labels && el.labels[0] && el.labels[0].innerText.trim()) || el.getAttribute('aria-label') || '';
  const out = [];
  document.querySelectorAll('button, a, input, select, textarea, h1, h2, table').forEach(el => {
    const r = el.getBoundingClientRect(); if (!r.width && !r.height) return;
    const tag = el.tagName.toLowerCase();
    const role = tag === 'a' ? 'link' : tag === 'button' ? 'button' : /^h[1-6]$/.test(tag) ? 'heading'
      : tag === 'select' ? (el.multiple ? 'multi-select' : 'select') : tag === 'table' ? 'table'
      : el.type === 'password' ? 'password' : 'textbox';
    const name = ['input', 'select', 'textarea', 'table'].includes(tag) ? label(el) : el.innerText.trim().slice(0, 60);
    out.push({role, name, readonly: !!el.readOnly});
  });
  return out;
}"""


class BrowserSession:
    def __init__(self, settings, ux: UXIntent, out_dir: Path):
        self.s = settings
        self.ux = ux
        self.out_dir = out_dir
        self.network: list[dict] = []
        self._secrets = [settings.stage_password]

    def __enter__(self) -> "BrowserSession":
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.s.headless)
        self.context = self.browser.new_context(base_url=self.s.stage_base_url, viewport={"width": 1280, "height": 800})
        self.context.tracing.start(screenshots=True, snapshots=True, sources=False)
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.s.step_timeout_ms)
        self.page.on("requestfinished", self._on_request)
        return self

    def __exit__(self, *exc) -> None:
        try:
            trace = self.out_dir / "trace.zip"
            self.context.tracing.stop(path=str(trace))
            scrub_zip(trace, self._secrets)
            network = mask_secrets(json.dumps(self.network, indent=2), self._secrets)
            (self.out_dir / "network.json").write_text(network, encoding="utf-8")
        finally:
            self.context.close()
            self.browser.close()
            self._pw.stop()

    def _on_request(self, request) -> None:
        if "/api/" not in request.url:
            return
        entry = {"method": request.method, "url": request.url, "duration_ms": round(request.timing.get("responseEnd", 0))}
        try:
            response = request.response()
            entry["status"] = response.status if response else None
            if response and "json" in (response.headers.get("content-type") or ""):
                entry["body"] = response.json()
        except Exception as exc:
            entry["body_error"] = str(exc)
        self.network.append(entry)

    # ---------- locating ----------
    def _raw(self, t: Target) -> Locator:
        p = self.page
        if t.testid:
            return p.get_by_test_id(t.testid)
        if t.role:
            return p.get_by_role(t.role, name=t.name, exact=True) if t.name else p.get_by_role(t.role)
        if t.label:
            return p.get_by_label(t.label, exact=True)
        return p.get_by_text(t.text or "")

    @staticmethod
    def _visible(loc: Locator, timeout: int) -> bool:
        try:
            loc.first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def _candidates(self, t: Target) -> list[tuple[Target, str]]:
        """Planned target first, then equivalent forms of the same visible name, then approved variances."""
        out: list[tuple[Target, str]] = [(t, "")]
        name = t.name or t.label or t.text
        if name and not t.testid:
            forms = [Target(label=name), Target(role="button", name=name), Target(role="link", name=name),
                     Target(role="heading", name=name), Target(text=name)]
            out += [(f, f"planned [{t.describe()}] resolved as [{f.describe()}]") for f in forms if f != t]
        for v in self.ux.approved_variances:
            if v.get("label") != name:
                continue
            reason = f"approved variance: '{name}'"
            for alt in v.get("allowed_labels", []):
                out += [(Target(role=r, name=alt), f"{reason} rendered as '{alt}' ({v.get('reason')})") for r in ("button", "link")]
                out.append((Target(label=alt), f"{reason} rendered as '{alt}' ({v.get('reason')})"))
            for kind in v.get("allowed_kinds", []):
                out.append((Target(role=kind, name=name), f"{reason} rendered as {kind} ({v.get('reason')})"))
        return out

    def locate(self, t: Target) -> tuple[Optional[Locator], str]:
        candidates = [(self._raw(c), note) for c, note in self._candidates(t)]
        combined = candidates[0][0]
        for loc, _ in candidates[1:]:
            combined = combined.or_(loc)
        if not self._visible(combined, self.s.step_timeout_ms):
            return None, ""
        for loc, note in candidates:
            try:
                if loc.first.is_visible():
                    return loc, note
            except Exception:
                continue
        return None, ""

    def snapshot(self) -> str:
        return json.dumps(self.page.evaluate(SNAPSHOT_JS), indent=0)

    def _settle(self) -> None:
        self.page.wait_for_timeout(250)
        self.page.wait_for_load_state("networkidle")

    def _poll(self, predicate, timeout_ms: Optional[int] = None) -> bool:
        deadline = time.monotonic() + (timeout_ms or self.s.step_timeout_ms) / 1000
        while True:
            try:
                if predicate():
                    return True
            except Exception:
                pass
            if time.monotonic() > deadline:
                return False
            self.page.wait_for_timeout(150)

    # ---------- execution ----------
    def describe(self, step: Step) -> str:
        parts = [step.action]
        if step.target:
            parts.append(f"[{step.target.describe()}]")
        for field in ("path", "value", "text", "contains", "name", "frame"):
            val = getattr(step, field)
            if val:
                parts.append(f"{field}={val!r}")
        if step.values:
            parts.append(f"values={step.values}")
        return mask_secrets(" ".join(parts), self._secrets)

    def execute(self, step: Step, index: int) -> StepResult:
        start = time.perf_counter()
        try:
            status, detail, data = getattr(self, f"_do_{step.action}")(step)
        except Exception as exc:
            status, detail, data = "error", f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}", {}
        data["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
        shot = self.out_dir / f"step-{index:02d}-{step.action}.png"
        try:
            self.page.screenshot(path=str(shot), full_page=True)
            shot_path = shot.name
        except Exception:
            shot_path = None
        return StepResult(
            index=index, action=step.action, description=self.describe(step), status=status,
            detail=mask_secrets(detail, self._secrets), screenshot=shot_path, data=data,
        )

    def _text(self, value: Optional[str]) -> str:
        return resolve_placeholders(value or "", self.s.stage_user, self.s.stage_password)

    def _need(self, step: Step):
        loc, note = self.locate(step.target)
        if loc is None:
            return None, ("missing", f"element not found: {step.target.describe()}", {"reason": "not_found"})
        return loc, note

    def _do_goto(self, step: Step):
        resp = self.page.goto(step.path)
        self._settle()
        code = resp.status if resp else None
        if code and code >= 500:
            return "error", f"HTTP {code} for {step.path}", {"status": code}
        return "ok", f"landed on {self.page.url}", {"status": code}

    def _do_fill(self, step: Step):
        loc, note = self._need(step)
        if loc is None:
            return note
        loc.first.fill(self._text(step.value))
        return "ok", note, {}

    def _do_click(self, step: Step):
        loc, note = self._need(step)
        if loc is None:
            return note
        loc.first.click()
        self._settle()
        return "ok", note, {}

    def _do_select(self, step: Step):
        loc, note = self._need(step)
        if loc is None:
            return note
        values = step.values or ([step.value] if step.value else [])
        multiple = loc.first.evaluate("e => !!e.multiple")
        if len(values) > 1 and not multiple:
            return "missing", f"control is single-select; cannot select {values}", {"reason": "capability"}
        loc.first.select_option(values)
        self._settle()
        return "ok", note, {}

    def _do_expect_visible(self, step: Step):
        loc, note = self._need(step)
        if loc is None:
            return note
        return "ok", note, {}

    def _do_expect_hidden(self, step: Step):
        visible = self._visible(self._raw(step.target), 500)
        return ("mismatch", "element is visible", {}) if visible else ("ok", "", {})

    def _do_expect_text(self, step: Step):
        expected = self._text(step.text)
        if not step.target:
            found = self._poll(lambda: expected in self.page.inner_text("body"))
            return ("ok", "", {}) if found else ("mismatch", f"text '{expected}' not on page", {})
        loc, note = self._need(step)
        if loc is None:
            return note
        ok = self._poll(lambda: expected in loc.first.inner_text())
        actual = loc.first.inner_text()
        return ("ok", note, {"actual": actual}) if ok else ("mismatch", f"expected '{expected}', saw '{actual}'", {"actual": actual})

    def _do_expect_value(self, step: Step):
        loc, note = self._need(step)
        if loc is None:
            return note
        is_field = loc.first.evaluate("e => ['input', 'textarea', 'select'].includes(e.tagName.toLowerCase())")
        expected = self._text(step.text)
        actual = loc.first.input_value() if is_field else loc.first.inner_text()
        return ("ok", note, {"actual": actual}) if expected in actual else ("mismatch", f"expected '{expected}', saw '{actual}'", {})

    def _do_expect_readonly(self, step: Step):
        loc, note = self._need(step)
        if loc is None:
            return note
        return ("mismatch", "field is editable", {}) if loc.first.is_editable() else ("ok", note, {})

    def _do_expect_url(self, step: Step):
        ok = self._poll(lambda: step.contains in self.page.url)
        return ("ok", self.page.url, {}) if ok else ("mismatch", f"URL is {self.page.url}, expected to contain '{step.contains}'", {})

    def _do_expect_rows(self, step: Step):
        expected = set(step.values or [])
        if not self.page.url.split("?")[0].rstrip("/").endswith("/blogs"):
            self.page.goto("/blogs")
            self._settle()
        titles = self.page.get_by_test_id("post-title")
        ok = self._poll(lambda: set(titles.all_inner_texts()) == expected)
        actual = titles.all_inner_texts()
        data = {"expected": sorted(expected), "actual": actual}
        return ("ok", "", data) if ok else ("mismatch", f"expected rows {sorted(expected)}, saw {actual}", data)

    def _do_check_calculation(self, step: Step):
        if step.name not in CALCULATIONS:
            return "error", f"unknown calculation '{step.name}'", {}
        if not self.page.url.rstrip("/").endswith("/blogs"):
            self.page.goto("/blogs")
            self._settle()
        rows = self.page.get_by_test_id("post-row")
        if not self._visible(rows, self.s.step_timeout_ms):
            return "missing", "no post rows on My Blogs", {"reason": "not_found"}
        testid = CALCULATIONS[step.name]["ui_testid"]
        ui_rows = {int(r.get_attribute("data-post-id")): r.get_by_test_id(testid).inner_text() for r in rows.all()}
        api = self.page.request.get("/api/posts")
        api_posts = api.json()
        self.network.append({"method": "GET", "url": api.url, "status": api.status, "body": api_posts, "source": "agent"})
        db = ReadOnlyDB(self.s.stage_db_path)
        try:
            marks = ",".join("?" * len(ui_rows))
            source = db.query(f"SELECT id, title, content FROM posts WHERE id IN ({marks})", tuple(ui_rows))
        finally:
            db.close()
        result = reconcile(step.name, ui_rows, api_posts, source)
        (self.out_dir / f"calculation-{step.name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if result["problems"]:
            summary = "; ".join(
                f"'{p['title']}': UI={p['ui']} API={p['api']} expected={p['expected']} (words={p['source_words']}) -> {p['finding']}"
                for p in result["problems"]
            )
            return "mismatch", f"{len(result['problems'])}/{len(result['rows'])} posts break {result['rule']}: {summary}", result
        return "ok", f"all {len(result['rows'])} posts match {result['rule']}", result

    def _do_figma_check(self, step: Step):
        components = self.ux.frames.get(step.frame)
        if components is None:
            return "error", f"frame '{step.frame}' not in UX intent", {}
        findings = compare_frame(self.page, components, self.ux.approved_variances, step.values)
        (self.out_dir / f"figma-{step.frame.replace(' ', '_')}.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
        bad = [f for f in findings if f["status"] in {"missing", "mismatch"}]
        data = {"findings": findings}
        if bad:
            return "missing", "; ".join(f"{f['kind']} '{f['label']}' (node {f['node_id']}): {f['detail']}" for f in bad), {**data, "reason": "figma"}
        notes = [f"{f['label']}: {f['detail']}" for f in findings if f["status"] == "approved_variance"]
        return "ok", "; ".join(notes) or f"{len(findings)} components match", data

    def _do_measure_load(self, step: Step):
        start = time.perf_counter()
        self.page.goto(step.path)
        self._settle()
        wall = int((time.perf_counter() - start) * 1000)
        nav = self.page.evaluate(
            "() => { const n = performance.getEntriesByType('navigation')[0];"
            " return n ? {dom_content_loaded_ms: Math.round(n.domContentLoadedEventEnd), load_ms: Math.round(n.loadEventEnd)} : {}; }"
        )
        return "ok", f"wall {wall} ms, DOMContentLoaded {nav.get('dom_content_loaded_ms')} ms", {"wall_ms": wall, **nav}

    def _do_screenshot(self, step: Step):
        return "ok", step.name or "", {}

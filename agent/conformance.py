"""Figma conformance: one verdict per design frame, independent of stories.

For each frame: open its StageUI route -> compare every component -> click each prototype flow and check the
destination -> capture design and live screenshots -> optional vision review (advisory, never changes the label).
"""
import json
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

from agent.classifier import PRECEDENCE
from agent.adapters import get_adapter
from agent.config import Settings
from agent.guardrails import check_step
from agent.models import FlowCheck, FrameVerdict, Step, Target, UXIntent, VisualReview
from agent.tools.browser import BrowserSession
from agent.tools.figma_compare import compare_frame
from llm import LLM, ReplayMissing
from mcp_servers.figma_mock.render_frames import frame_slug

def _load_prerequisites(settings: Settings) -> dict:
    path = settings.knowledge_dir / "flow_test_data.json"
    return json.loads(path.read_text(encoding="utf-8")).get("prerequisites", {}) if path.exists() else {}


class _Counter:
    def __init__(self):
        self.n = 0

    def __call__(self) -> int:
        self.n += 1
        return self.n


def _check_flow(b: BrowserSession, settings: Settings, ux: UXIntent, frame: str, flow: dict,
                prereqs: dict, step_no: _Counter) -> FlowCheck:
    adapter = get_adapter(settings)
    route = ux.frame_routes[frame]["path"]
    target_route = ux.frame_routes.get(flow["to_frame"], {}).get("path", "")
    base = {"trigger_label": flow["trigger_label"], "to_frame": flow["to_frame"], "expected_path": target_route}
    b.execute(Step(action="goto", path=route), step_no())
    for field in prereqs.get(f"{frame}/{flow['trigger_label']}", []):
        b.execute(Step(action="fill", target=Target(label=field["label"]), value=field["value"]), step_no())

    click = Step(action="click", target=Target(role="button", name=flow["trigger_label"]))
    refusal = check_step(click, settings.stage_base_url, adapter.allowed_origins, settings.target_read_only)
    if refusal:
        return FlowCheck(**base, status="error", detail=f"guardrail: {refusal}")
    result = b.execute(click, step_no())
    if result.status == "missing":
        return FlowCheck(**base, status="missing", detail=f"trigger '{flow['trigger_label']}' not found")
    if result.status != "ok":
        return FlowCheck(**base, status="error", detail=result.detail)
    observed = urlparse(b.page.url).path.rstrip("/") or "/"
    if observed == target_route.rstrip("/"):
        return FlowCheck(**base, observed_url=b.page.url, status="ok", detail=result.detail)
    return FlowCheck(**base, observed_url=b.page.url, status="mismatch",
                     detail=f"landed on {observed}, design navigates to '{flow['to_frame']}' ({target_route})")


def _visual_review(llm: LLM, frame: str, design: Path, live: Path, findings: list[dict], variances: list[dict], log):
    conditional = [f["label"] for f in findings if f["status"] == "skipped"]
    approved = [v for v in variances if v.get("frame") == frame]
    approved_text = "; ".join(
        f"'{v['label']}' may appear as {v.get('allowed_labels') or v.get('allowed_kinds')} ({v['reason']})" for v in approved
    ) or "none"
    text = (f"Frame: {frame}\n"
            f"Components expected on screen: {json.dumps([f['kind'] + ' ' + repr(f['label']) for f in findings if f['status'] != 'skipped'])}\n"
            f"Conditional states that are NOT expected on this screen (do not report): {conditional or 'none'}\n"
            f"Approved variances (do not report): {approved_text}")
    try:
        review = llm.vision("visual_review", frame_slug(frame), llm.prompt("visual_review_system"), text, [design, live], VisualReview)
    except ReplayMissing:
        return None
    except Exception as exc:
        log(f"    visual review skipped for {frame}: {type(exc).__name__}: {str(exc)[:200]}")
        return None
    ignore = [s.lower() for s in conditional]
    for v in approved:
        ignore += [a.lower() for a in v.get("allowed_labels", [])]
    kept = [o for o in review.observations if not any(term in f"{o.area} {o.difference}".lower() for term in ignore)]
    if review.observations and not kept:
        review.summary = "No differences beyond approved variances and conditional states."
    review.observations = kept
    return review


def _verdict(frame: str, findings: list[dict], flows: list[FlowCheck], login_ok: bool) -> tuple[str, str]:
    reasons: list[tuple[str, str]] = []
    if not login_ok:
        reasons.append(("RISK", "Could not log in to reach this screen."))
    for f in findings:
        if f["status"] in {"missing", "mismatch"}:
            reasons.append(("GAP", f"{f['kind']} '{f['label']}' (node {f['node_id']}): {f['detail']}."))
    for fl in flows:
        if fl.status == "mismatch":
            reasons.append(("DEFECT", f"Flow '{fl.trigger_label}' → {fl.to_frame}: {fl.detail}."))
        elif fl.status == "missing":
            reasons.append(("GAP", f"Flow '{fl.trigger_label}' → {fl.to_frame}: {fl.detail}."))
        elif fl.status == "error":
            reasons.append(("RISK", f"Flow '{fl.trigger_label}' → {fl.to_frame}: {fl.detail}."))
    variances = [f"{f['label']}: {f['detail']}" for f in findings if f["status"] == "approved_variance"]
    if not reasons:
        matched = sum(f["status"] in {"matched", "approved_variance"} for f in findings)
        ok_flows = sum(fl.status == "ok" for fl in flows)
        text = f"{matched} components and {ok_flows} prototype flows match the design."
        return "PASS", text + (" Approved variances: " + "; ".join(variances) + "." if variances else "")
    label = max((r[0] for r in reasons), key=PRECEDENCE.get)
    ordered = [r[1] for r in reasons if r[0] == label] + [f"(also {r[0]}) {r[1]}" for r in reasons if r[0] != label]
    return label, " ".join(ordered)


def run_conformance(settings: Settings, ux: UXIntent, llm: LLM, run_dir: Path, log=print) -> list[FrameVerdict]:
    adapter = get_adapter(settings)
    prereqs = _load_prerequisites(settings)
    verdicts = []
    for frame, components in ux.frames.items():
        route = ux.frame_routes.get(frame)
        if not route:
            log(f"  • {frame}: no route mapped; skipped")
            continue
        start = time.perf_counter()
        out = run_dir / "figma" / frame_slug(frame)
        step_no = _Counter()
        flows_out = sorted((f for f in ux.flows if f["from_frame"] == frame), key=lambda f: f["to_frame"] == "Login")
        with BrowserSession(settings, ux, out) as b:
            login_ok = True
            if route.get("requires_login"):
                login_ok = all(b.execute(s, step_no()).status == "ok" for s in adapter.login_steps())
            b.execute(Step(action="goto", path=route["path"]), step_no())
            b.page.screenshot(path=str(out / "live.png"))
            findings = compare_frame(b.page, components, ux.approved_variances)
            flows = [_check_flow(b, settings, ux, frame, fl, prereqs, step_no) for fl in flows_out] if login_ok else []

        design_src = ux.frame_images.get(frame, {}).get("path")
        design = None
        if design_src and Path(design_src).exists():
            design = out / "design.png"
            shutil.copyfile(design_src, design)
        review = _visual_review(llm, frame, design, out / "live.png", findings, ux.approved_variances, log) if design else None

        label, rationale = _verdict(frame, findings, flows, login_ok)
        img = ux.frame_images.get(frame, {})
        verdict = FrameVerdict(
            frame=frame, node_id=ux.frame_nodes.get(frame, ""),
            route=route["path"], label=label, rationale=rationale,
            components=findings, flows=flows,
            design_image=design.relative_to(run_dir).as_posix() if design else None,
            live_image=(out / "live.png").relative_to(run_dir).as_posix(),
            design_size={"width": img.get("width") or 1280, "height": img.get("height") or 800},
            visual_review=review,
            trace_path=(out / "trace.zip").relative_to(run_dir).as_posix(),
            duration_ms=int((time.perf_counter() - start) * 1000),
        )
        (out / "verdict.json").write_text(verdict.model_dump_json(indent=2), encoding="utf-8")
        notes = f", {len(review.observations)} visual note(s)" if review else ""
        log(f"  • {frame} ({route['path']}): {label}{notes}")
        verdicts.append(verdict)
    return verdicts

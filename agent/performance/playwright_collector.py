import hashlib
import json
import platform
import secrets
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

from agent.adapters import get_adapter
from agent.guardrails import resolve_placeholders
from agent.models import Step, Target
from agent.performance.models import PerformanceProfile, PerformanceSample

OBSERVER_SCRIPT = """
(() => {
  window.__uqePerf = {lcp: 0, cls: 0, long_task_ms: 0, event_ms: 0};
  const observe = (type, callback) => {
    try {
      new PerformanceObserver(list => list.getEntries().forEach(callback))
        .observe({type, buffered: true});
    } catch (_) {}
  };
  observe('largest-contentful-paint', e => window.__uqePerf.lcp = Math.max(window.__uqePerf.lcp, e.startTime));
  observe('layout-shift', e => { if (!e.hadRecentInput) window.__uqePerf.cls += e.value; });
  observe('longtask', e => window.__uqePerf.long_task_ms += e.duration);
  observe('event', e => window.__uqePerf.event_ms = Math.max(window.__uqePerf.event_ms, e.duration || 0));
})();
"""


def _locator(page: Page, target: Target):
    if target.testid:
        return page.get_by_test_id(target.testid)
    if target.role:
        return page.get_by_role(target.role, name=target.name, exact=True) if target.name else page.get_by_role(target.role)
    if target.label:
        return page.get_by_label(target.label, exact=True)
    return page.get_by_text(target.text or "", exact=True)


def _execute_step(page: Page, step: Step, user: str, password: str) -> None:
    if step.action == "goto":
        page.goto(step.path)
    elif step.action == "fill":
        _locator(page, step.target).first.fill(resolve_placeholders(step.value or "", user, password))
    elif step.action == "click":
        _locator(page, step.target).first.click()
    elif step.action == "select":
        values = step.values or ([step.value] if step.value else [])
        _locator(page, step.target).first.select_option(values)
    elif step.action == "screenshot":
        return
    else:
        raise ValueError(f"Performance profiles do not support action '{step.action}'")


def _settle(page: Page, condition) -> None:
    timeout = condition.timeout_ms
    if condition.kind == "network-idle":
        page.wait_for_load_state("networkidle", timeout=timeout)
    elif condition.kind == "load":
        page.wait_for_load_state("load", timeout=timeout)
    elif condition.kind == "dom-content-loaded":
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    elif condition.kind == "visible":
        _locator(page, Target.model_validate(condition.target or {})).first.wait_for(
            state="visible", timeout=timeout
        )
    elif condition.kind == "hidden":
        _locator(page, Target.model_validate(condition.target or {})).first.wait_for(
            state="hidden", timeout=timeout
        )
    elif condition.kind == "url":
        page.wait_for_url(f"**{condition.value or ''}**", timeout=timeout)
    elif condition.kind == "app-mark":
        page.wait_for_function(
            "name => performance.getEntriesByName(name).length > 0",
            condition.value, timeout=timeout,
        )


def _page_metrics(page: Page) -> dict[str, float]:
    return page.evaluate("""() => {
      const nav = performance.getEntriesByType('navigation')[0] || {};
      const paints = Object.fromEntries(
        performance.getEntriesByType('paint').map(e => [e.name, e.startTime])
      );
      const resources = performance.getEntriesByType('resource');
      const api = resources.filter(e => {
        try { return new URL(e.name).pathname.includes('/api/'); } catch (_) { return false; }
      });
      const observed = window.__uqePerf || {};
      return {
        ttfb_ms: nav.responseStart || 0,
        dom_content_loaded_ms: nav.domContentLoadedEventEnd || 0,
        load_ms: nav.loadEventEnd || 0,
        fcp_ms: paints['first-contentful-paint'] || 0,
        lcp_ms: observed.lcp || 0,
        cls: observed.cls || 0,
        inp_ms: observed.event_ms || 0,
        long_task_ms: observed.long_task_ms || 0,
        transfer_bytes: resources.reduce((n, e) => n + (e.transferSize || 0), 0),
        request_count: resources.length,
        api_request_count: api.length,
        api_max_duration_ms: api.reduce((n, e) => Math.max(n, e.duration || 0), 0),
        api_total_duration_ms: api.reduce((n, e) => n + (e.duration || 0), 0)
      };
    }""")


def _environment_fingerprint(browser_version: str, profile: PerformanceProfile) -> str:
    payload = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "browser": browser_version,
        "viewport": profile.browser.viewport,
        "cpu_slowdown": profile.browser.cpu_slowdown,
        "latency_ms": profile.browser.latency_ms,
        "download_kbps": profile.browser.download_kbps,
        "upload_kbps": profile.browser.upload_kbps,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class PlaywrightPerformanceCollector:
    def __init__(self, settings):
        self.settings = settings
        self.adapter = get_adapter(settings)

    def collect(self, profile: PerformanceProfile, out_dir: Path) -> tuple[list[PerformanceSample], str, dict[str, str]]:
        samples: list[PerformanceSample] = []
        out_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.settings.headless)
            browser_version = browser.version
            try:
                for cache_mode in profile.browser.cache_modes:
                    total = profile.browser.warmups + profile.browser.iterations
                    for sequence in range(total):
                        measured_iteration = sequence - profile.browser.warmups
                        iteration_samples = self._iteration(
                            browser, profile, cache_mode, measured_iteration
                        )
                        if measured_iteration >= 0:
                            samples.extend(iteration_samples)
            finally:
                browser.close()
        fingerprint = _environment_fingerprint(browser_version, profile)
        tools = {"playwright": playwright.__class__.__module__, "chromium": browser_version}
        (out_dir / "samples.json").write_text(
            json.dumps([sample.model_dump(mode="json") for sample in samples], indent=2),
            encoding="utf-8",
        )
        return samples, fingerprint, tools

    def _iteration(self, browser, profile: PerformanceProfile, cache_mode: str, iteration: int) -> list[PerformanceSample]:
        context = browser.new_context(
            base_url=self.settings.stage_base_url,
            viewport=profile.browser.viewport,
            **self.adapter.context_options(),
        )
        page = context.new_page()
        page.set_default_timeout(self.settings.step_timeout_ms)
        page.add_init_script(OBSERVER_SCRIPT)
        trace_id = None
        if profile.integrations.opentelemetry:
            trace_id = secrets.token_hex(16)
            page.set_extra_http_headers({
                "traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01"
            })
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": cache_mode == "cold"})
        if profile.browser.cpu_slowdown > 1:
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": profile.browser.cpu_slowdown})
        if profile.browser.latency_ms or profile.browser.download_kbps or profile.browser.upload_kbps:
            cdp.send("Network.emulateNetworkConditions", {
                "offline": False,
                "latency": profile.browser.latency_ms,
                "downloadThroughput": profile.browser.download_kbps * 1024 / 8 or -1,
                "uploadThroughput": profile.browser.upload_kbps * 1024 / 8 or -1,
                "connectionType": "other",
            })
        try:
            for login_step in self.adapter.login_steps():
                _execute_step(
                    page, login_step, self.settings.stage_user, self.settings.stage_password
                )
            if self.adapter.login_steps():
                page.wait_for_load_state("networkidle")
            if cache_mode == "warm" and profile.path:
                page.goto(profile.path)
                page.wait_for_load_state("networkidle")
            return self._measure(page, profile, cache_mode, iteration, trace_id)
        finally:
            context.close()

    def _measure(
        self, page: Page, profile: PerformanceProfile, cache_mode: str,
        iteration: int, trace_id: str | None,
    ) -> list[PerformanceSample]:
        values: list[PerformanceSample] = []
        measurements = {item.action_index: item for item in profile.measurements if item.action_index is not None}
        if profile.path and (profile.scope == "page" or not profile.steps):
            measurement = profile.measurements[0] if profile.measurements else None
            started = time.perf_counter()
            page.goto(profile.path)
            if measurement:
                _settle(page, measurement.end)
            wall = (time.perf_counter() - started) * 1000
            values.extend(self._samples(profile, measurement.id if measurement else "navigation", {
                "wall_ms": wall, **_page_metrics(page),
            }, cache_mode, iteration, trace_id))
            return values

        if profile.path and (not profile.steps or profile.steps[0].get("action") != "goto"):
            page.goto(profile.path)
            page.wait_for_load_state("networkidle")
        for index, raw_step in enumerate(profile.steps):
            step = Step.model_validate(raw_step)
            measurement = measurements.get(index)
            started = time.perf_counter()
            if measurement and measurement.end.kind == "response":
                with page.expect_response(
                    lambda response: (measurement.end.value or "") in response.url,
                    timeout=measurement.end.timeout_ms,
                ):
                    _execute_step(page, step, self.settings.stage_user, self.settings.stage_password)
            else:
                _execute_step(page, step, self.settings.stage_user, self.settings.stage_password)
                if measurement:
                    _settle(page, measurement.end)
            if measurement:
                elapsed = (time.perf_counter() - started) * 1000
                values.extend(self._samples(profile, measurement.id, {
                    "interaction_ms": elapsed, **_page_metrics(page),
                }, cache_mode, iteration, trace_id))
        return values

    @staticmethod
    def _samples(
        profile: PerformanceProfile,
        measurement_id: str,
        metrics: dict[str, Any],
        cache_mode: str,
        iteration: int,
        trace_id: str | None,
    ) -> list[PerformanceSample]:
        return [
            PerformanceSample(
                profile_id=profile.id,
                measurement_id=measurement_id,
                metric=f"{measurement_id}.{name}.{cache_mode}",
                value=float(value),
                unit="" if name in {"cls", "request_count", "api_request_count"} else (
                    "bytes" if name == "transfer_bytes" else "ms"
                ),
                iteration=iteration,
                cache_mode=cache_mode,
                tags=profile.tags,
                trace_id=trace_id,
            )
            for name, value in metrics.items()
        ]

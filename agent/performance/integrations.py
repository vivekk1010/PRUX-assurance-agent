import json
import re
import shutil
import subprocess
from pathlib import Path

from agent.performance.models import PerformanceProfile, PerformanceSample


class ExternalIntegrationResult:
    def __init__(self, samples=None, artifacts=None, warnings=None, tools=None):
        self.samples: list[PerformanceSample] = samples or []
        self.artifacts: list[str] = artifacts or []
        self.warnings: list[str] = warnings or []
        self.tools: dict[str, str] = tools or {}


def _target(step: dict) -> str:
    target = step.get("target") or {}
    if target.get("testid"):
        return f"page.getByTestId({json.dumps(target['testid'])})"
    if target.get("label"):
        return f"page.getByLabel({json.dumps(target['label'])})"
    if target.get("role"):
        return (
            f"page.getByRole({json.dumps(target['role'])}, "
            f"{{ name: {json.dumps(target.get('name', ''))} }})"
        )
    return f"page.getByText({json.dumps(target.get('text', ''))})"


def _k6_value(value: str | None) -> str:
    if value == "${TARGET_USER}":
        return "__ENV.TARGET_USER"
    if value == "${TARGET_PASSWORD}":
        return "__ENV.TARGET_PASSWORD"
    return json.dumps(value or "")


def render_k6_script(
    profile: PerformanceProfile, base_url: str, login_steps: list[dict] | None = None
) -> str:
    if profile.integrations.k6_protocol and not profile.integrations.k6_browser:
        method = str(profile.tool_options.get("method", "GET")).lower()
        path = str(profile.tool_options.get("path", profile.path or "/"))
        duration = str(profile.tool_options.get("duration", "30s"))
        vus = int(profile.tool_options.get("vus", 10))
        return f"""import http from 'k6/http';
import {{ check, sleep }} from 'k6';
const BASE_URL = __ENV.TARGET_BASE_URL || {json.dumps(base_url)};
export const options = {{
  scenarios: {{ protocol: {{ executor: 'constant-vus', vus: Number(__ENV.PERF_VUS || {vus}), duration: {json.dumps(duration)} }} }},
  thresholds: {{ http_req_failed: ['rate<0.01'], http_req_duration: ['p(95)<1000'] }}
}};
export default function () {{
  const response = http.{method}(BASE_URL + {json.dumps(path)});
  check(response, {{ 'status below 500': r => r.status < 500 }});
  sleep(Number(__ENV.PERF_SLEEP_SECONDS || 1));
}}
"""
    browser_steps = []
    for step in (login_steps or []) + profile.steps:
        action = step.get("action")
        if action == "goto":
            browser_steps.append(f"await page.goto(BASE_URL + {json.dumps(step.get('path', '/'))});")
        elif action == "click":
            browser_steps.append(f"await {_target(step)}.click();")
        elif action == "fill":
            browser_steps.append(f"await {_target(step)}.fill({_k6_value(step.get('value'))});")
        elif action == "select":
            value = step.get("values") or step.get("value")
            browser_steps.append(f"await {_target(step)}.selectOption({json.dumps(value)});")
    if not browser_steps and profile.path:
        browser_steps.append(f"await page.goto(BASE_URL + {json.dumps(profile.path)});")
    thresholds = {}
    for budget in profile.budgets:
        if budget.max_value is not None and budget.metric.startswith(("browser_", "http_")):
            thresholds[budget.metric] = [f"{budget.statistic.replace('median', 'med')}<{budget.max_value}"]
    journey_name = re.sub(r"[^A-Za-z0-9_]", "_", profile.id + "_journey_ms")
    return f"""import {{ browser }} from 'k6/browser';
import {{ Trend }} from 'k6/metrics';

const BASE_URL = __ENV.TARGET_BASE_URL || {json.dumps(base_url)};
const journey = new Trend({json.dumps(journey_name)}, true);
export const options = {{
  scenarios: {{
    browser: {{
      executor: 'shared-iterations',
      vus: Number(__ENV.PERF_VUS || 1),
      iterations: Number(__ENV.PERF_ITERATIONS || {profile.browser.iterations}),
      options: {{ browser: {{ type: 'chromium' }} }}
    }}
  }},
  thresholds: {json.dumps(thresholds)}
}};

export default async function () {{
  const page = await browser.newPage();
  const started = Date.now();
  try {{
    {' '.join(browser_steps)}
    await page.waitForLoadState('networkidle');
    journey.add(Date.now() - started, {{ profile_id: {json.dumps(profile.id)} }});
  }} finally {{
    await page.close();
  }}
}}
"""


def run_k6(
    profile: PerformanceProfile,
    base_url: str,
    out_dir: Path,
    *,
    login_steps: list[dict] | None = None,
    target_user: str = "",
    target_password: str = "",
) -> ExternalIntegrationResult:
    executable = str(profile.tool_options.get("k6_command") or shutil.which("k6") or "")
    script = out_dir / "k6.generated.js"
    script.write_text(render_k6_script(profile, base_url, login_steps), encoding="utf-8")
    if not executable:
        return ExternalIntegrationResult(
            artifacts=[str(script)],
            warnings=[f"{profile.id}: k6 is enabled but the k6 executable was not found"],
        )
    summary = out_dir / "k6-summary.json"
    command = [executable, "run", "--summary-export", str(summary)]
    remote_write = profile.tool_options.get("prometheus_remote_write_url")
    if remote_write:
        command += ["-o", "experimental-prometheus-rw"]
    command.append(str(script))
    environment = {
        "TARGET_BASE_URL": base_url,
        "TARGET_USER": target_user,
        "TARGET_PASSWORD": target_password,
        "PERF_ITERATIONS": str(profile.browser.iterations),
        "PERF_VUS": str(profile.tool_options.get("vus", 1)),
    }
    if remote_write:
        environment["K6_PROMETHEUS_RW_SERVER_URL"] = str(remote_write)
    import os
    proc = subprocess.run(
        command, cwd=out_dir, env={**os.environ, **environment},
        capture_output=True, text=True, timeout=int(profile.tool_options.get("timeout_seconds", 600)),
    )
    (out_dir / "k6.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    if proc.returncode:
        return ExternalIntegrationResult(
            artifacts=[str(script), str(out_dir / "k6.log")],
            warnings=[f"{profile.id}: k6 exited with code {proc.returncode}"],
            tools={"k6": executable},
        )
    return ExternalIntegrationResult(
        artifacts=[str(script), str(summary), str(out_dir / "k6.log")],
        tools={"k6": executable},
    )


def run_lighthouse(profile: PerformanceProfile, base_url: str, out_dir: Path) -> ExternalIntegrationResult:
    executable = str(profile.tool_options.get("lighthouse_command") or shutil.which("lhci") or "")
    assertions = {"categories:performance": ["warn", {"minScore": 0.8}]}
    audit_map = {
        "fcp_ms": "first-contentful-paint",
        "lcp_ms": "largest-contentful-paint",
        "cls": "cumulative-layout-shift",
        "ttfb_ms": "server-response-time",
    }
    for budget in profile.budgets:
        if budget.max_value is None:
            continue
        matched = next((audit for suffix, audit in audit_map.items() if suffix in budget.metric), None)
        if matched:
            assertions[matched] = [
                "error" if budget.severity == "fail" else "warn",
                {"maxNumericValue": budget.max_value},
            ]
    config = {
        "ci": {
            "collect": {
                "url": [base_url.rstrip("/") + (profile.path or "/")],
                "numberOfRuns": profile.browser.iterations,
                "settings": {"chromeFlags": "--headless --no-sandbox"},
            },
            "assert": {"assertions": assertions},
            "upload": {"target": "filesystem", "outputDir": str(out_dir / "lighthouse-results")},
        }
    }
    config_path = out_dir / "lighthouserc.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    if not executable:
        return ExternalIntegrationResult(
            artifacts=[str(config_path)],
            warnings=[f"{profile.id}: Lighthouse CI is enabled but lhci was not found"],
        )
    proc = subprocess.run(
        [executable, "autorun", "--config", str(config_path)],
        cwd=out_dir, capture_output=True, text=True,
        timeout=int(profile.tool_options.get("timeout_seconds", 600)),
    )
    log = out_dir / "lighthouse.log"
    log.write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    warnings = [] if proc.returncode == 0 else [
        f"{profile.id}: Lighthouse CI exited with code {proc.returncode}"
    ]
    return ExternalIntegrationResult(
        artifacts=[str(config_path), str(log), str(out_dir / "lighthouse-results")],
        warnings=warnings, tools={"lighthouse": executable},
    )


def import_benchmarkdotnet(profile: PerformanceProfile, out_dir: Path) -> ExternalIntegrationResult:
    configured = profile.tool_options.get("benchmarkdotnet_json")
    if not configured:
        return ExternalIntegrationResult(
            warnings=[f"{profile.id}: BenchmarkDotNet is enabled but no JSON artifact was configured"]
        )
    source = Path(str(configured))
    if not source.is_file():
        return ExternalIntegrationResult(
            warnings=[f"{profile.id}: BenchmarkDotNet artifact does not exist: {source}"]
        )
    payload = json.loads(source.read_text(encoding="utf-8"))
    destination = out_dir / "benchmarkdotnet.json"
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return ExternalIntegrationResult(
        artifacts=[str(destination)],
        tools={"benchmarkdotnet": str(payload.get("HostEnvironmentInfo", {}).get("BenchmarkDotNetCaption", "artifact"))},
    )

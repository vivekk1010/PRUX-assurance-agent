import json

from agent.config import Settings
from agent.performance.exporters import export_otlp_json, write_prometheus_text
from agent.performance.integrations import render_k6_script, run_k6
from agent.performance.models import PerformanceRun
from agent.performance.profiles import PerformanceProfileRegistry
from agent.performance.runner import PerformanceRunner
from agent.performance.statistics import build_summary
from tests.test_performance_foundation import profile, samples


def test_k6_script_is_generated_without_executable(tmp_path, monkeypatch):
    current = profile(
        integrations={"playwright": False, "k6_browser": True},
        steps=[{"action": "goto", "path": "/home"}],
    )
    script = render_k6_script(current, "https://example.test")
    assert "k6/browser" in script
    assert "https://example.test" in script
    monkeypatch.setattr("agent.performance.integrations.shutil.which", lambda _: None)
    result = run_k6(current, "https://example.test", tmp_path)
    assert result.warnings
    assert (tmp_path / "k6.generated.js").exists()


def test_otlp_and_prometheus_exports(monkeypatch, tmp_path):
    summary = build_summary(profile(), samples(), "env")
    run = PerformanceRun(run_id="run-1", summaries=[summary], samples=samples())
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, content, headers, timeout):
        captured["url"] = url
        captured["payload"] = json.loads(content)
        return Response()

    monkeypatch.setattr("agent.performance.exporters.httpx.post", fake_post)
    export_otlp_json(run, "http://collector:4318")
    assert captured["url"].endswith("/v1/metrics")
    assert captured["payload"]["resourceMetrics"]
    path = write_prometheus_text(run, tmp_path / "metrics.prom")
    assert "ui_quality_nav_wall_ms_warm_p95" in path.read_text(encoding="utf-8")


def test_disabled_runner_writes_artifact(tmp_path):
    settings = Settings()
    settings.performance_enabled = False
    settings.performance_config = tmp_path / "missing.json"
    runner = PerformanceRunner(settings, PerformanceProfileRegistry.from_file(settings.performance_config))
    result = runner.run(tmp_path, run_id="disabled")
    assert result.enabled is False
    assert (tmp_path / "performance.json").exists()

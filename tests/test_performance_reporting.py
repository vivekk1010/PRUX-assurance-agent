import json

from agent.performance.models import PerformanceRun
from agent.performance.statistics import build_summary
from agent.reporting.evaluate_run import evaluate_run
from agent.reporting.report import write_reports
from tests.test_performance_foundation import profile, samples


def performance_payload():
    summary = build_summary(profile(), samples(), "env")
    return PerformanceRun(
        run_id="perf-1", summaries=[summary], samples=samples()
    ).model_dump(mode="json")


def test_performance_is_rendered_and_evaluated(tmp_path):
    payload = performance_payload()
    meta = {
        "run_id": "perf-1", "author": "test", "stage_base_url": "https://example.test",
        "llm_provider": "none", "llm_model": "none", "ux_source": "n/a", "embedder": "n/a",
    }
    write_reports(tmp_path, [], meta, [], performance=payload)
    (tmp_path / "performance.json").write_text(json.dumps(payload), encoding="utf-8")
    evaluation = evaluate_run(tmp_path)
    assert evaluation["checks"]["performance"]["passed"] is True
    assert "Performance assurance" in (tmp_path / "report.html").read_text(encoding="utf-8")


def test_performance_eval_detects_tampered_results(tmp_path):
    payload = performance_payload()
    (tmp_path / "performance.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "results.json").write_text(json.dumps({
        "meta": {}, "stories": [], "figma_conformance": [],
        "performance": {**payload, "summaries": []},
    }), encoding="utf-8")
    (tmp_path / "report.html").write_text("report", encoding="utf-8")
    evaluation = evaluate_run(tmp_path)
    assert evaluation["checks"]["performance"]["passed"] is False

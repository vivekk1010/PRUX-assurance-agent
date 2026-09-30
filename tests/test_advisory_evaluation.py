import json

from agent.evaluation.exporters import export_advisory_otlp
from agent.evaluation.models import (
    AdvisoryEvaluationRun,
    AdvisoryScore,
    DashboardExportConfig,
)
from agent.evaluation.runner import run_advisory_evaluation
from agent.reporting.report import write_reports


class FakeJudge:
    def __init__(self, _config):
        pass

    def evaluate(self, *, metric, story_key, actual_output, **_kwargs):
        assert actual_output["deterministic_label"] == "DEFECT"
        assert story_key == "BLOG-1"
        return 0.91, f"{metric.id} is grounded in deterministic evidence"


def _write_results(run_dir):
    payload = {
        "meta": {"run_id": run_dir.name},
        "figma_conformance": [],
        "stories": [
            {
                "story_key": "BLOG-1",
                "title": "Example",
                "label": "DEFECT",
                "recommendation": "Fix AC-1.",
                "ac_verdicts": [
                    {
                        "ac_id": "AC-1",
                        "text": "Expected behavior",
                        "label": "DEFECT",
                        "rationale": "Observed behavior differs.",
                        "scenario_ids": ["SC-1"],
                        "evidence": ["BLOG-1/SC-1/trace.zip"],
                    }
                ],
                "scenario_results": [],
            }
        ],
    }
    (run_dir / "results.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_config(path, *, enabled=True):
    path.write_text(
        json.dumps(
            {
                "enabled": enabled,
                "authoritative": False,
                "judge": {
                    "provider": "ollama",
                    "model": "local-model",
                    "base_url": "http://127.0.0.1:11434/v1",
                },
                "metrics": [
                    {
                        "id": "consistency",
                        "name": "Consistency",
                        "criteria": "Stay consistent with deterministic labels.",
                        "threshold": 0.8,
                    }
                ],
                "dashboard_export": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )


def test_disabled_advisory_evaluation_has_no_side_effects(tmp_path):
    config = tmp_path / "config.json"
    _write_config(config, enabled=False)

    assert run_advisory_evaluation(tmp_path, config, judge_factory=FakeJudge) is None
    assert not (tmp_path / "advisory-eval.json").exists()


def test_advisory_evaluation_is_non_authoritative_and_persisted(tmp_path):
    config = tmp_path / "config.json"
    _write_config(config)
    _write_results(tmp_path)

    result = run_advisory_evaluation(tmp_path, config, judge_factory=FakeJudge)

    assert result["authoritative"] is False
    assert result["status"] == "COMPLETE"
    assert result["meets_advisory_threshold"] is True
    assert result["scores"][0]["score"] == 0.91
    assert json.loads((tmp_path / "advisory-eval.json").read_text()) == result


def test_advisory_scores_render_without_changing_report_verdicts(tmp_path):
    config = tmp_path / "config.json"
    _write_config(config)
    _write_results(tmp_path)
    advisory = run_advisory_evaluation(tmp_path, config, judge_factory=FakeJudge)
    meta = {
        "run_id": "run-1",
        "author": "Vivek",
        "stage_base_url": "https://example.test",
        "llm_provider": "none",
        "llm_model": "none",
        "ux_source": "fixture",
        "embedder": "hashing",
    }

    write_reports(tmp_path, [], meta, [], advisory_evaluation=advisory)

    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Advisory output evaluation" in html
    assert "non-authoritative" in html


def test_otlp_export_contains_bounded_scores_not_recommendation_text(monkeypatch):
    captured = {}

    class Response:
        @staticmethod
        def raise_for_status():
            return None

    def fake_post(url, *, content, headers, timeout):
        captured.update(
            url=url, payload=json.loads(content), headers=headers, timeout=timeout
        )
        return Response()

    monkeypatch.setattr("agent.evaluation.exporters.httpx.post", fake_post)
    run = AdvisoryEvaluationRun(
        run_id="run-1",
        engine="deepeval-geval",
        provider="ollama",
        model="local-model",
        status="COMPLETE",
        scores=[
            AdvisoryScore(
                story_key="BLOG-1",
                metric_id="consistency",
                metric_name="Consistency",
                score=0.91,
                threshold=0.8,
                meets_threshold=True,
                reason="sensitive narrative that must not be exported",
            )
        ],
    )

    exported = export_advisory_otlp(
        run,
        DashboardExportConfig(
            enabled=True,
            backend="langfuse",
            otlp_endpoint="http://127.0.0.1:4318",
        ),
    )

    assert exported == "langfuse:http://127.0.0.1:4318/v1/traces"
    encoded = json.dumps(captured["payload"])
    assert "sensitive narrative" not in encoded
    assert "BLOG-1" in encoded
    assert "evaluation.authoritative" in encoded

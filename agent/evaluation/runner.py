import json
from pathlib import Path
from typing import Any, Callable

from agent.evaluation.config import load_advisory_config
from agent.evaluation.exporters import export_advisory_otlp
from agent.evaluation.geval import DeepEvalGEvalJudge
from agent.evaluation.models import (
    AdvisoryEvaluationConfig,
    AdvisoryEvaluationRun,
    AdvisoryScore,
)

JudgeFactory = Callable[[Any], Any]


def _story_projection(story: dict[str, Any]) -> dict[str, Any]:
    return {
        "story_key": story.get("story_key"),
        "title": story.get("title"),
        "deterministic_label": story.get("label"),
        "recommendation": story.get("recommendation", ""),
        "acceptance_criteria": [
            {
                "id": verdict.get("ac_id"),
                "criterion": verdict.get("text"),
                "deterministic_label": verdict.get("label"),
                "rationale": verdict.get("rationale"),
                "scenario_ids": verdict.get("scenario_ids", []),
                "evidence_count": len(verdict.get("evidence", [])),
            }
            for verdict in story.get("ac_verdicts", [])
            if isinstance(verdict, dict)
        ],
    }


def _context(story: dict[str, Any]) -> list[str]:
    values = [
        (
            f"{verdict.get('ac_id')}: criterion={verdict.get('text')!r}; "
            f"label={verdict.get('label')}; rationale={verdict.get('rationale')!r}; "
            f"evidence_count={len(verdict.get('evidence', []))}"
        )
        for verdict in story.get("ac_verdicts", [])
        if isinstance(verdict, dict)
    ]
    values.append(
        "PASS, GAP, DEFECT, and RISK labels are authoritative deterministic outputs. "
        "The advisory evaluator must assess quality without changing those labels."
    )
    return values


def _expected_output() -> str:
    return (
        "The recommendation and rationale must be consistent with every deterministic "
        "acceptance-criterion label, must not claim unsupported evidence, and must direct "
        "uncertain or incomplete cases to human review. The evaluator is advisory and "
        "must not reinterpret PASS, GAP, DEFECT, or RISK."
    )


def run_advisory_evaluation(
    run_dir: Path,
    config_path: Path,
    *,
    force_enabled: bool = False,
    judge_factory: JudgeFactory | None = None,
) -> dict[str, Any] | None:
    config = load_advisory_config(config_path)
    if not (force_enabled or config.enabled):
        return None

    results_path = run_dir / "results.json"
    if not results_path.is_file():
        raise FileNotFoundError(f"advisory evaluation requires {results_path}")
    results = json.loads(results_path.read_text(encoding="utf-8"))
    stories = [
        story for story in results.get("stories", []) if isinstance(story, dict)
    ]
    output = AdvisoryEvaluationRun(
        run_id=run_dir.name,
        engine=config.engine,
        provider=config.judge.provider,
        model=config.judge.model,
        status="SKIPPED" if not stories else "COMPLETE",
    )
    if not stories:
        payload = output.model_dump(mode="json")
        (run_dir / "advisory-eval.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return payload

    try:
        judge = (judge_factory or DeepEvalGEvalJudge)(config.judge)
        for story in stories:
            projection = _story_projection(story)
            for metric in config.metrics:
                if not metric.enabled:
                    continue
                try:
                    score, reason = judge.evaluate(
                        metric=metric,
                        story_key=str(story.get("story_key", "")),
                        input_text=(
                            f"Evaluate the assurance output for {story.get('story_key')}: "
                            f"{story.get('title', '')}"
                        ),
                        actual_output=projection,
                        expected_output=_expected_output(),
                        context=_context(story),
                    )
                    bounded = min(1.0, max(0.0, float(score)))
                    output.scores.append(
                        AdvisoryScore(
                            story_key=str(story.get("story_key", "")),
                            metric_id=metric.id,
                            metric_name=metric.name,
                            score=bounded,
                            threshold=metric.threshold,
                            meets_threshold=bounded >= metric.threshold,
                            reason=reason,
                        )
                    )
                except Exception as exc:
                    if not config.fail_open:
                        raise
                    output.errors.append(
                        f"{story.get('story_key')}/{metric.id}: "
                        f"{type(exc).__name__}: {exc}"
                    )
    except Exception as exc:
        if not config.fail_open:
            raise
        output.errors.append(f"{type(exc).__name__}: {exc}")

    output.meets_advisory_threshold = (
        all(score.meets_threshold for score in output.scores)
        if output.scores
        else None
    )
    if output.errors and output.scores:
        output.status = "PARTIAL"
    elif output.errors:
        output.status = "ERROR"

    try:
        exported = export_advisory_otlp(output, config.dashboard_export)
        if exported:
            output.exports.append(exported)
    except Exception as exc:
        if not config.dashboard_export.fail_open:
            raise
        output.errors.append(f"dashboard export: {type(exc).__name__}: {exc}")
        output.status = "PARTIAL" if output.scores else "ERROR"

    payload = output.model_dump(mode="json")
    (run_dir / "advisory-eval.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload

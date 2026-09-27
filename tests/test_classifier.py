from pathlib import Path

from agent.classifier import classify, story_label
from agent.models import ACIntent, IntentModel, ScenarioResult, StepResult


def _scenario(tmp: Path, sid: str, ac: str, statuses: list[str]) -> ScenarioResult:
    d = tmp / sid
    d.mkdir()
    (d / "trace.zip").write_bytes(b"")
    steps = [StepResult(index=i, action="expect_text", description="", status=s, screenshot=f"step-{i}.png")
             for i, s in enumerate(statuses, 1)]
    return ScenarioResult(scenario_id=sid, ac_ids=[ac], title=sid, steps=steps, trace_path=str(d / "trace.zip"))


def _intent(*acs: ACIntent) -> IntentModel:
    return IntentModel(story_key="T-1", acs=list(acs))


def test_labels_follow_step_evidence(tmp_path):
    intent = _intent(*(ACIntent(id=f"AC-0{i}", text="x") for i in range(1, 5)))
    results = [
        _scenario(tmp_path, "S1", "AC-01", ["ok", "ok"]),
        _scenario(tmp_path, "S2", "AC-02", ["ok", "missing"]),
        _scenario(tmp_path, "S3", "AC-03", ["missing", "mismatch"]),
        _scenario(tmp_path, "S4", "AC-04", ["refused", "skipped"]),
    ]
    labels = {v.ac_id: v.label for v in classify(intent, results, tmp_path)}
    assert labels == {"AC-01": "PASS", "AC-02": "GAP", "AC-03": "DEFECT", "AC-04": "RISK"}


def test_ambiguous_ac_is_risk_even_when_checks_pass(tmp_path):
    intent = _intent(ACIntent(id="AC-01", text="loads fast", ambiguous=True, ambiguity_reason="no threshold"))
    verdict = classify(intent, [_scenario(tmp_path, "S1", "AC-01", ["ok"])], tmp_path)[0]
    assert verdict.label == "RISK" and "not specified" in verdict.rationale


def test_ac_without_scenario_or_evidence_cannot_pass(tmp_path):
    intent = _intent(ACIntent(id="AC-01", text="x"), ACIntent(id="AC-02", text="y"))
    no_trace = ScenarioResult(scenario_id="S2", ac_ids=["AC-02"], title="", steps=[
        StepResult(index=1, action="expect_text", description="", status="ok")])
    labels = {v.ac_id: v.label for v in classify(intent, [no_trace], tmp_path)}
    assert labels == {"AC-01": "RISK", "AC-02": "RISK"}


def test_story_label_precedence(tmp_path):
    intent = _intent(ACIntent(id="AC-01", text="x"), ACIntent(id="AC-02", text="y"))
    results = [_scenario(tmp_path, "S1", "AC-01", ["ok"]), _scenario(tmp_path, "S2", "AC-02", ["missing"])]
    assert story_label(classify(intent, results, tmp_path)) == "GAP"

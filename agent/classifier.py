"""Evidence -> PASS / GAP / DEFECT / RISK per acceptance criterion. Rules only; no LLM."""
from pathlib import Path

from agent.models import ACVerdict, IntentModel, ScenarioResult

PRECEDENCE = {"PASS": 0, "RISK": 1, "GAP": 2, "DEFECT": 3}
STATUS_LABEL = {"mismatch": "DEFECT", "missing": "GAP", "refused": "RISK", "error": "RISK", "recovered": "RISK"}


def story_label(verdicts: list[ACVerdict]) -> str:
    return max((v.label for v in verdicts), key=PRECEDENCE.get, default="RISK")


def classify(intent: IntentModel, results: list[ScenarioResult], run_dir: Path) -> list[ACVerdict]:
    verdicts = []
    for ac in intent.acs:
        related = [r for r in results if ac.id in r.ac_ids]
        findings: list[tuple[str, str]] = []
        evidence: list[str] = []
        notes: list[str] = []
        checks = 0

        if not related:
            findings.append(("RISK", "No executable scenario was generated for this AC."))
        for r in related:
            screenshots = [s.screenshot for s in r.steps if s.screenshot]
            if not r.trace_path or not screenshots:
                findings.append(("RISK", f"{r.scenario_id}: evidence incomplete (trace or screenshots missing)."))
            scenario_dir = Path(r.trace_path).parent if r.trace_path else None
            if r.trace_path:
                evidence.append(Path(r.trace_path).relative_to(run_dir).as_posix())
            for step in r.steps:
                if step.status in STATUS_LABEL:
                    findings.append((STATUS_LABEL[step.status], f"{r.scenario_id} step {step.index} ({step.action}): {step.detail}"))
                    if step.screenshot and scenario_dir:
                        evidence.append((scenario_dir / step.screenshot).relative_to(run_dir).as_posix())
                elif step.status == "ok":
                    checks += 1 if step.action.startswith(("expect", "check", "figma", "measure")) else 0
                    if "approved variance" in step.detail or "approved:" in step.detail:
                        notes.append(step.detail)
                    if step.action == "measure_load":
                        notes.append(f"Measured: {step.detail}")
            if scenario_dir:
                for extra in sorted(scenario_dir.glob("*.json")):
                    evidence.append(extra.relative_to(run_dir).as_posix())
            if related and screenshots and scenario_dir and not any(STATUS_LABEL.get(s.status) for s in r.steps):
                evidence.append((scenario_dir / screenshots[-1]).relative_to(run_dir).as_posix())

        if ac.ambiguous:
            findings.append(("RISK", f"Expected behavior not specified: {ac.ambiguity_reason}."))

        if findings:
            label = max((f[0] for f in findings), key=PRECEDENCE.get)
            reasons = [f[1] for f in findings if f[0] == label] + [f"(also {f[0]}) {f[1]}" for f in findings if f[0] != label]
            rationale = " ".join(reasons + notes)
        else:
            label = "PASS"
            rationale = f"{checks} check{'s' if checks != 1 else ''} passed in {', '.join(r.scenario_id for r in related)}." + (
                " " + " ".join(dict.fromkeys(notes)) if notes else "")
        verdicts.append(ACVerdict(
            ac_id=ac.id, text=ac.text, label=label, rationale=rationale.strip(),
            scenario_ids=[r.scenario_id for r in related], evidence=list(dict.fromkeys(evidence)),
        ))
    return verdicts

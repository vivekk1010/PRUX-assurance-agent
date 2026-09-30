"""Deterministically validate a completed assurance run's artifacts.

This module deliberately does not import the runtime models: it evaluates the
JSON that was actually emitted, and can therefore be used after a failed or
partially copied run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable


LABEL_PRECEDENCE = {"PASS": 0, "RISK": 1, "GAP": 2, "DEFECT": 3}
SECRET_ENV_VARS = (
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "STAGE_PASSWORD",
    "GITHUB_TOKEN",
    "GH_TOKEN",
)
SECRET_PATTERNS = (
    ("openai_key", re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
MAX_ZIP_MEMBER_BYTES = 20 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 100 * 1024 * 1024


def _check(passed: bool, **details: Any) -> dict[str, Any]:
    return {"passed": passed, **details}


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _resolve_reference(run_dir: Path, value: Any) -> Path | None:
    """Resolve relative, native absolute, and emitted Windows run paths."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    candidate = Path(raw)
    windows_path = PureWindowsPath(raw)
    if not candidate.is_absolute() and not windows_path.is_absolute():
        candidate = run_dir / candidate
    elif candidate.is_absolute() and _inside(run_dir, candidate):
        return candidate
    elif windows_path.is_absolute():
        parts = windows_path.parts
        try:
            marker = next(i for i, part in enumerate(parts) if part == run_dir.name)
        except StopIteration:
            return None
        candidate = run_dir.joinpath(*parts[marker + 1 :])
    if not _inside(run_dir, candidate):
        return None
    return candidate


def _add_reference(
    references: list[dict[str, Any]],
    run_dir: Path,
    value: Any,
    source: str,
    *,
    base: Path | None = None,
) -> Path | None:
    path = None
    if base is not None and isinstance(value, str) and value:
        local = base / value
        path = local if _inside(run_dir, local) else None
    if path is None:
        path = _resolve_reference(run_dir, value)
    references.append(
        {
            "source": source,
            "path": value if isinstance(value, str) else None,
            "exists": bool(path and path.is_file()),
            "resolved": path,
        }
    )
    return path


def _evaluate_results(run_dir: Path, data: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    story_mismatches: list[dict[str, Any]] = []
    structure_errors: list[str] = []
    references: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []

    if not isinstance(data, dict):
        return (
            _check(False, mismatches=[], errors=["results.json root must be an object"]),
            _check(False, referenced=0, existing=0, missing=[], incomplete=[]),
        )
    stories = data.get("stories")
    if not isinstance(stories, list):
        stories = []
        structure_errors.append("stories must be a list")

    seen_stories: set[str] = set()
    for story_index, story in enumerate(stories):
        if not isinstance(story, dict):
            structure_errors.append(f"stories[{story_index}] must be an object")
            continue
        story_key = story.get("story_key")
        if not isinstance(story_key, str) or not story_key:
            story_key = f"stories[{story_index}]"
            structure_errors.append(f"{story_key} has no story_key")
        elif story_key in seen_stories:
            structure_errors.append(f"duplicate story_key: {story_key}")
        seen_stories.add(story_key)

        verdicts = story.get("ac_verdicts")
        if not isinstance(verdicts, list):
            verdicts = []
            structure_errors.append(f"{story_key}.ac_verdicts must be a list")
        labels = [v.get("label") for v in verdicts if isinstance(v, dict)]
        invalid = sorted({str(label) for label in labels if label not in LABEL_PRECEDENCE})
        if invalid:
            structure_errors.append(
                f"{story_key} has invalid AC labels: {', '.join(invalid)}"
            )
        expected = (
            max(labels, key=LABEL_PRECEDENCE.get)
            if labels and not invalid
            else "RISK"
        )
        if story.get("label") != expected:
            story_mismatches.append(
                {"story": story_key, "actual": story.get("label"), "expected": expected}
            )

        scenario_results = story.get("scenario_results")
        if not isinstance(scenario_results, list):
            scenario_results = []
            structure_errors.append(f"{story_key}.scenario_results must be a list")
        scenario_ids = {
            scenario.get("scenario_id")
            for scenario in scenario_results
            if isinstance(scenario, dict) and isinstance(scenario.get("scenario_id"), str)
        }

        for field in ("intent_path", "scenarios_path"):
            if story.get(field):
                _add_reference(references, run_dir, story[field], f"{story_key}.{field}")

        for ac_index, verdict in enumerate(verdicts):
            if not isinstance(verdict, dict):
                structure_errors.append(f"{story_key}.ac_verdicts[{ac_index}] must be an object")
                continue
            ac_id = verdict.get("ac_id") or f"ac_verdicts[{ac_index}]"
            evidence = verdict.get("evidence")
            if not isinstance(evidence, list):
                evidence = []
                structure_errors.append(f"{story_key}/{ac_id}.evidence must be a list")
            resolved = [
                _add_reference(
                    references, run_dir, item, f"{story_key}/{ac_id}.evidence[{index}]"
                )
                for index, item in enumerate(evidence)
            ]
            existing = [path for path in resolved if path and path.is_file()]
            has_trace = any(path.name.lower().endswith("trace.zip") for path in existing)
            has_screenshot = any(path.suffix.lower() == ".png" for path in existing)
            linked_scenarios = [
                sid for sid in verdict.get("scenario_ids", []) if isinstance(sid, str)
            ]
            missing_scenarios = sorted(
                sid
                for sid in linked_scenarios
                if sid not in scenario_ids
            )
            reasons = []
            if not has_trace:
                reasons.append("missing trace.zip")
            if not has_screenshot:
                reasons.append("missing screenshot")
            for sid in linked_scenarios:
                scenario_evidence = [path for path in existing if sid in path.parts]
                if not any(path.name.lower().endswith("trace.zip") for path in scenario_evidence):
                    reasons.append(f"{sid}: missing trace.zip")
                if not any(path.suffix.lower() == ".png" for path in scenario_evidence):
                    reasons.append(f"{sid}: missing screenshot")
            if missing_scenarios:
                reasons.append(f"unknown scenarios: {', '.join(missing_scenarios)}")
            if reasons:
                incomplete.append({"story": story_key, "ac": ac_id, "reasons": reasons})

        for scenario_index, scenario in enumerate(scenario_results):
            if not isinstance(scenario, dict):
                structure_errors.append(
                    f"{story_key}.scenario_results[{scenario_index}] must be an object"
                )
                continue
            scenario_id = scenario.get("scenario_id") or f"scenario_results[{scenario_index}]"
            trace = None
            for field in ("trace_path", "network_path"):
                if scenario.get(field):
                    found = _add_reference(
                        references,
                        run_dir,
                        scenario[field],
                        f"{story_key}/{scenario_id}.{field}",
                    )
                    if field == "trace_path":
                        trace = found
            scenario_dir = trace.parent if trace else run_dir / story_key / str(scenario_id)
            steps = scenario.get("steps", [])
            if not isinstance(steps, list):
                structure_errors.append(f"{story_key}/{scenario_id}.steps must be a list")
                continue
            for step_index, step in enumerate(steps):
                if isinstance(step, dict) and step.get("screenshot"):
                    _add_reference(
                        references,
                        run_dir,
                        step["screenshot"],
                        f"{story_key}/{scenario_id}.steps[{step_index}].screenshot",
                        base=scenario_dir,
                    )

    frames = data.get("figma_conformance", [])
    if not isinstance(frames, list):
        frames = []
        structure_errors.append("figma_conformance must be a list")
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            structure_errors.append(f"figma_conformance[{index}] must be an object")
            continue
        name = frame.get("frame") or f"figma_conformance[{index}]"
        frame_paths: dict[str, Path | None] = {}
        for field in ("design_image", "live_image", "trace_path"):
            if frame.get(field):
                frame_paths[field] = _add_reference(
                    references, run_dir, frame[field], f"frame {name}.{field}"
                )
            else:
                frame_paths[field] = None
        absent = [
            field
            for field, path in frame_paths.items()
            if path is None or not path.is_file()
        ]
        if absent:
            incomplete.append(
                {"frame": name, "reasons": [f"missing {field}" for field in absent]}
            )

    missing = [
        {"source": item["source"], "path": item["path"]}
        for item in references
        if not item["exists"]
    ]
    story_check = _check(
        not story_mismatches and not structure_errors,
        mismatches=story_mismatches,
        errors=structure_errors,
    )
    evidence_check = _check(
        not missing and not incomplete,
        referenced=len(references),
        existing=len(references) - len(missing),
        missing=missing,
        incomplete=incomplete,
    )
    return story_check, evidence_check


def _secret_needles(secrets: Iterable[str] | None) -> list[tuple[str, bytes]]:
    values: list[tuple[str, str]] = []
    if secrets is not None:
        values.extend((f"provided_secret_{i}", value) for i, value in enumerate(secrets, 1))
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name)
        if value:
            values.append((name, value))
    unique: dict[bytes, str] = {}
    for name, value in values:
        if isinstance(value, str) and len(value) >= 4:
            unique.setdefault(value.encode("utf-8"), name)
    return sorted(((name, value) for value, name in unique.items()), key=lambda item: item[0])


def _scan_bytes(data: bytes, location: str, needles: list[tuple[str, bytes]]) -> list[dict[str, str]]:
    detectors = {name for name, pattern in SECRET_PATTERNS if pattern.search(data)}
    detectors.update(name for name, value in needles if value in data)
    return [{"path": location, "detector": name} for name in sorted(detectors)]


def _scan_secrets(run_dir: Path, secrets: Iterable[str] | None) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    errors: list[str] = []
    needles = _secret_needles(secrets)
    for path in sorted((p for p in run_dir.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
        relative = path.relative_to(run_dir).as_posix()
        if relative == "eval.json":
            continue
        if path.suffix.lower() == ".zip":
            try:
                total = 0
                with zipfile.ZipFile(path) as archive:
                    for member in sorted(archive.infolist(), key=lambda item: item.filename):
                        if member.is_dir():
                            continue
                        total += member.file_size
                        if member.file_size > MAX_ZIP_MEMBER_BYTES or total > MAX_ZIP_TOTAL_BYTES:
                            errors.append(f"{relative}: archive scan size limit exceeded")
                            break
                        findings.extend(
                            _scan_bytes(
                                archive.read(member),
                                f"{relative}!{member.filename}",
                                needles,
                            )
                        )
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                errors.append(f"{relative}: {type(exc).__name__}")
        else:
            try:
                findings.extend(_scan_bytes(path.read_bytes(), relative, needles))
            except OSError as exc:
                errors.append(f"{relative}: {type(exc).__name__}")
    return _check(not findings and not errors, findings=findings, errors=errors)


def _evaluate_gold(data: Any, gold_path: Path | None) -> dict[str, Any]:
    if gold_path is None:
        return {"enabled": False, "passed": True, "mismatches": [], "error": None}
    gold, error = _read_json(gold_path)
    if error or not isinstance(gold, dict):
        return {
            "enabled": True,
            "passed": False,
            "mismatches": [],
            "error": error or "gold root must be an object",
        }
    actual_stories: dict[str, dict[str, Any]] = {}
    actual_frames: dict[str, Any] = {}
    if isinstance(data, dict):
        for story in data.get("stories", []):
            if isinstance(story, dict) and isinstance(story.get("story_key"), str):
                actual_stories[story["story_key"]] = {
                    verdict.get("ac_id"): verdict.get("label")
                    for verdict in story.get("ac_verdicts", [])
                    if isinstance(verdict, dict)
                }
        actual_frames = {
            frame.get("frame"): frame.get("label")
            for frame in data.get("figma_conformance", [])
            if isinstance(frame, dict) and isinstance(frame.get("frame"), str)
        }
    mismatches = []
    for story, expected_acs in sorted(gold.get("stories", {}).items()):
        if not isinstance(expected_acs, dict):
            continue
        for ac, expected in sorted(expected_acs.items()):
            actual = actual_stories.get(story, {}).get(ac)
            if actual != expected:
                mismatches.append(
                    {"kind": "ac", "story": story, "ac": ac, "actual": actual, "expected": expected}
                )
    for frame, expected in sorted(gold.get("figma_frames", {}).items()):
        actual = actual_frames.get(frame)
        if actual != expected:
            mismatches.append(
                {"kind": "frame", "frame": frame, "actual": actual, "expected": expected}
            )
    return {
        "enabled": True,
        "passed": not mismatches,
        "mismatches": mismatches,
        "error": None,
    }


def _evaluate_approved_coverage(data: dict[str, Any]) -> dict[str, Any]:
    meta = data.get("meta", {})
    cases = meta.get("approved_cases", [])
    selector = meta.get("selector", {})
    executed: dict[str, set[str]] = {}
    verdict_acs: dict[str, set[str]] = {}
    for story in data.get("stories", []):
        key = story.get("story_key", "")
        executed[key] = {
            scenario.get("scenario_id") for scenario in story.get("scenario_results", [])
            if isinstance(scenario, dict)
        }
        verdict_acs[key] = {
            verdict.get("ac_id") for verdict in story.get("ac_verdicts", [])
            if isinstance(verdict, dict)
        }
    problems = []
    for case in cases:
        key, case_id = case.get("story_key", ""), case.get("id", "")
        if case_id not in executed.get(key, set()):
            problems.append(f"{case_id}: not executed")
        missing_acs = set(case.get("ac_ids", [])) - verdict_acs.get(key, set())
        if missing_acs:
            problems.append(f"{case_id}: ACs not classified {sorted(missing_acs)}")
        if not case.get("citations"):
            problems.append(f"{case_id}: no grounding citations")
        if selector.get("frame") and selector["frame"] not in case.get("figma_frames", []):
            problems.append(f"{case_id}: does not match frame selector")
        if selector.get("feature") and selector["feature"] not in case.get("feature_ids", []):
            problems.append(f"{case_id}: does not match feature selector")
    if not meta.get("plan_sources_fresh", False):
        problems.append("approved plan sources are stale")
    return _check(not problems, approved=len(cases), problems=problems)


def _evaluate_performance(run_dir: Path, results: Any) -> dict[str, Any] | None:
    if not isinstance(results, dict) or results.get("performance") is None:
        return None
    path = run_dir / "performance.json"
    payload, error = _read_json(path) if path.is_file() else (None, "missing")
    problems = []
    if error:
        problems.append(f"performance.json: {error}")
    elif not isinstance(payload, dict):
        problems.append("performance.json root must be an object")
    else:
        summaries = payload.get("summaries", [])
        samples = payload.get("samples", [])
        if not isinstance(summaries, list):
            problems.append("summaries must be a list")
            summaries = []
        if not isinstance(samples, list):
            problems.append("samples must be a list")
            samples = []
        sample_counts: dict[tuple[str, str], int] = {}
        for sample in samples:
            if not isinstance(sample, dict):
                problems.append("performance sample must be an object")
                continue
            profile_id = sample.get("profile_id")
            metric = sample.get("metric")
            if not isinstance(profile_id, str) or not isinstance(metric, str):
                problems.append("performance sample missing profile_id or metric")
                continue
            sample_counts[(profile_id, metric)] = sample_counts.get((profile_id, metric), 0) + 1
        for summary in summaries:
            profile_id = summary.get("profile_id", "<unknown>") if isinstance(summary, dict) else "<invalid>"
            if not isinstance(summary, dict):
                problems.append("performance summary must be an object")
                continue
            if summary.get("status") not in {"PASS", "WARN", "FAIL", "UNSTABLE", "NOT_MEASURED"}:
                problems.append(f"{profile_id}: invalid performance status")
            statistics = summary.get("statistics", {})
            if not isinstance(statistics, dict):
                problems.append(f"{profile_id}: statistics must be an object")
                continue
            for metric, values in statistics.items():
                if not isinstance(values, dict) or values.get("count", 0) < 1:
                    problems.append(f"{profile_id}/{metric}: no samples")
                    continue
                retained = sample_counts.get((profile_id, metric), 0)
                if retained < int(values.get("count", 0)):
                    problems.append(
                        f"{profile_id}/{metric}: summary count exceeds retained raw samples"
                    )
            for budget in summary.get("budgets", []):
                if not isinstance(budget, dict) or not isinstance(budget.get("passed"), bool):
                    problems.append(f"{profile_id}: malformed budget outcome")
        emitted = results.get("performance") or {}
        if emitted.get("summaries") != payload.get("summaries"):
            problems.append("results.json performance summary differs from performance.json")
    return _check(not problems, artifact=str(path.name), problems=problems)


def evaluate_run(
    run_dir: str | Path,
    gold_path: str | Path | None = None,
    secrets: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Evaluate ``run_dir`` and always write a deterministic ``eval.json``."""
    root = Path(run_dir)
    results_path = root / "results.json"
    report_path = root / "report.html"
    results, results_error = _read_json(results_path) if results_path.is_file() else (None, "missing")

    artifacts = _check(
        results_path.is_file() and report_path.is_file() and results_error is None,
        results_json={"exists": results_path.is_file(), "error": results_error},
        report_html={"exists": report_path.is_file()},
    )
    if results_error is None:
        story_labels, evidence = _evaluate_results(root, results)
    else:
        story_labels = _check(False, mismatches=[], errors=["results.json unavailable"])
        evidence = _check(False, referenced=0, existing=0, missing=[], incomplete=[])
    secret_check = _scan_secrets(root, secrets) if root.is_dir() else _check(
        False, findings=[], errors=["run directory is missing"]
    )
    gold = _evaluate_gold(results, Path(gold_path) if gold_path is not None else None)
    checks = {
        "artifacts": artifacts,
        "story_labels": story_labels,
        "evidence": evidence,
        "secrets": secret_check,
        "gold": gold,
    }
    if isinstance(results, dict) and "approved_cases" in results.get("meta", {}):
        checks["approved_coverage"] = _evaluate_approved_coverage(results)
    performance = _evaluate_performance(root, results)
    if performance is not None:
        checks["performance"] = performance
    passed_count = sum(bool(check["passed"]) for check in checks.values())
    evaluation = {
        "schema_version": 1,
        "run_id": root.name,
        "passed": passed_count == len(checks),
        "summary": {
            "checks": len(checks),
            "passed": passed_count,
            "failed": len(checks) - passed_count,
        },
        "checks": checks,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "eval.json").write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--gold", type=Path)
    parser.add_argument(
        "--secret-env",
        action="append",
        default=[],
        metavar="NAME",
        help="also scan for the value of this environment variable",
    )
    args = parser.parse_args(argv)
    extra_secrets = [os.environ[name] for name in args.secret_env if os.environ.get(name)]
    result = evaluate_run(args.run_dir, args.gold, extra_secrets)
    print(json.dumps({"passed": result["passed"], **result["summary"]}, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

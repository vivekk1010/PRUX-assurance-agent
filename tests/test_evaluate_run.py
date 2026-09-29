import json
import zipfile
from pathlib import Path

from agent.reporting.evaluate_run import evaluate_run, main


def _write(path: Path, content: str = "artifact") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_run(tmp_path: Path) -> tuple[Path, dict]:
    run_dir = tmp_path / "run-001"
    scenario_dir = run_dir / "BLOG-1" / "SC-1"
    scenario_dir.mkdir(parents=True)
    with zipfile.ZipFile(scenario_dir / "trace.zip", "w") as archive:
        archive.writestr("trace.trace", '{"event": "safe"}')
    _write(scenario_dir / "network.json", "{}")
    _write(scenario_dir / "step-01-expect_text.png")
    _write(run_dir / "BLOG-1" / "intent.json", "{}")
    _write(run_dir / "BLOG-1" / "scenarios.json", "{}")
    _write(run_dir / "report.html", "<html>safe</html>")
    payload = {
        "meta": {"run_id": "run-001"},
        "figma_conformance": [],
        "stories": [
            {
                "story_key": "BLOG-1",
                "title": "Story",
                "label": "DEFECT",
                "ac_verdicts": [
                    {
                        "ac_id": "AC-1",
                        "text": "criterion",
                        "label": "PASS",
                        "rationale": "ok",
                        "scenario_ids": ["SC-1"],
                        "evidence": [
                            "BLOG-1/SC-1/trace.zip",
                            "BLOG-1/SC-1/network.json",
                            "BLOG-1/SC-1/step-01-expect_text.png",
                        ],
                    },
                    {
                        "ac_id": "AC-2",
                        "text": "criterion",
                        "label": "DEFECT",
                        "rationale": "mismatch",
                        "scenario_ids": ["SC-1"],
                        "evidence": [
                            "BLOG-1/SC-1/trace.zip",
                            "BLOG-1/SC-1/step-01-expect_text.png",
                        ],
                    },
                ],
                "scenario_results": [
                    {
                        "scenario_id": "SC-1",
                        "ac_ids": ["AC-1", "AC-2"],
                        "title": "scenario",
                        "steps": [
                            {
                                "index": 1,
                                "action": "expect_text",
                                "status": "ok",
                                "description": "check",
                                "screenshot": "step-01-expect_text.png",
                                "data": {},
                            }
                        ],
                        # Exercise Windows paths emitted by the Windows runner.
                        "trace_path": rf"C:\runs\{run_dir.name}\BLOG-1\SC-1\trace.zip",
                        "network_path": rf"C:\runs\{run_dir.name}\BLOG-1\SC-1\network.json",
                    }
                ],
                "intent_path": "BLOG-1/intent.json",
                "scenarios_path": "BLOG-1/scenarios.json",
            }
        ],
    }
    (run_dir / "results.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_dir, payload


def test_valid_run_passes_and_writes_deterministic_eval(tmp_path: Path) -> None:
    run_dir, _ = _make_run(tmp_path)

    first = evaluate_run(run_dir)
    first_bytes = (run_dir / "eval.json").read_bytes()
    second = evaluate_run(run_dir)

    assert first["passed"] is True
    assert first == second
    assert (run_dir / "eval.json").read_bytes() == first_bytes
    assert first["checks"]["evidence"]["referenced"] == 10
    assert first["summary"] == {"checks": 5, "passed": 5, "failed": 0}


def test_reports_story_label_and_incomplete_or_missing_evidence(tmp_path: Path) -> None:
    run_dir, payload = _make_run(tmp_path)
    payload["stories"][0]["label"] = "PASS"
    payload["stories"][0]["ac_verdicts"][0]["scenario_ids"] = ["UNKNOWN"]
    (run_dir / "BLOG-1" / "SC-1" / "step-01-expect_text.png").unlink()
    (run_dir / "results.json").write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_run(run_dir)

    assert result["passed"] is False
    assert result["checks"]["story_labels"]["mismatches"] == [
        {"story": "BLOG-1", "actual": "PASS", "expected": "DEFECT"}
    ]
    assert any(
        item["path"].endswith(".png")
        for item in result["checks"]["evidence"]["missing"]
    )
    assert "unknown scenarios: UNKNOWN" in result["checks"]["evidence"]["incomplete"][0]["reasons"]


def test_detects_explicit_secrets_in_plain_files_and_zip_members(tmp_path: Path) -> None:
    run_dir, _ = _make_run(tmp_path)
    secret = "correct-horse-battery-staple"
    _write(run_dir / "debug.log", f"password={secret}")
    with zipfile.ZipFile(run_dir / "BLOG-1" / "SC-1" / "trace.zip", "a") as archive:
        archive.writestr("resources/request.txt", f"credential={secret}")

    result = evaluate_run(run_dir, secrets=[secret])

    findings = result["checks"]["secrets"]["findings"]
    assert result["checks"]["secrets"]["passed"] is False
    assert findings == [
        {
            "path": "BLOG-1/SC-1/trace.zip!resources/request.txt",
            "detector": "provided_secret_1",
        },
        {"path": "debug.log", "detector": "provided_secret_1"},
    ]
    assert secret not in json.dumps(result)
    assert secret not in (run_dir / "eval.json").read_text(encoding="utf-8")


def test_detects_high_confidence_secret_pattern_without_value(tmp_path: Path) -> None:
    run_dir, _ = _make_run(tmp_path)
    _write(run_dir / "debug.log", "token=sk-proj-abcdefghijklmnopqrstuvwxyz123456")

    result = evaluate_run(run_dir)

    assert result["checks"]["secrets"]["findings"] == [
        {"path": "debug.log", "detector": "openai_key"}
    ]


def test_optional_gold_compares_ac_and_frame_labels(tmp_path: Path) -> None:
    run_dir, _ = _make_run(tmp_path)
    gold = tmp_path / "gold.json"
    gold.write_text(
        json.dumps(
            {
                "stories": {"BLOG-1": {"AC-1": "PASS", "AC-2": "GAP"}},
                "figma_frames": {"Login": "PASS"},
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_run(run_dir, gold_path=gold)

    assert result["checks"]["gold"]["passed"] is False
    assert result["checks"]["gold"]["mismatches"] == [
        {
            "kind": "ac",
            "story": "BLOG-1",
            "ac": "AC-2",
            "actual": "DEFECT",
            "expected": "GAP",
        },
        {
            "kind": "frame",
            "frame": "Login",
            "actual": None,
            "expected": "PASS",
        },
    ]


def test_missing_results_and_report_still_write_eval_and_cli_fails(tmp_path: Path) -> None:
    run_dir = tmp_path / "partial"

    result = evaluate_run(run_dir)

    assert result["passed"] is False
    assert result["checks"]["artifacts"]["results_json"] == {
        "exists": False,
        "error": "missing",
    }
    assert (run_dir / "eval.json").is_file()
    assert main([str(run_dir)]) == 1

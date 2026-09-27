"""Evaluate the agent against human gold labels over N repeated runs.

  python -m evals.run_eval --runs 3 --start-stage

Metrics: coverage, label accuracy, known-issue detection, Figma frame accuracy, false positives, flake rate,
evidence completeness, latency per story, LLM calls/tokens and estimated cost.
"""
import argparse
import json
import statistics
import sys
from datetime import datetime

from agent.cli import run_stories, stage_session
from agent.config import ROOT, get_settings

GOLD = json.loads((ROOT / "evals" / "gold_labels.json").read_text(encoding="utf-8"))
PRICE_PER_M = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00), "gpt-4.1-mini": (0.40, 1.60)}


def evaluate(all_runs: list[list], model: str) -> dict:
    gold = GOLD["stories"]
    total_acs = sum(len(v) for v in gold.values())
    per_ac_labels: dict[tuple, list[str]] = {}
    covered = correct = false_pos = evidence_ok = 0
    latencies, calls, p_tok, c_tok = [], 0, 0, 0

    for results in all_runs:
        for r in results:
            latencies.append(r.duration_ms / 1000)
            calls += r.llm_usage.get("calls", 0)
            p_tok += r.llm_usage.get("prompt_tokens", 0)
            c_tok += r.llm_usage.get("completion_tokens", 0)
            for v in r.ac_verdicts:
                expected = gold.get(r.story_key, {}).get(v.ac_id)
                if expected is None:
                    continue
                per_ac_labels.setdefault((r.story_key, v.ac_id), []).append(v.label)
                covered += 1 if v.scenario_ids else 0
                correct += v.label == expected
                false_pos += v.label in {"GAP", "DEFECT"} and expected not in {"GAP", "DEFECT"}
                has_trace = any(e.endswith("trace.zip") for e in v.evidence)
                has_shot = any(e.endswith(".png") for e in v.evidence)
                evidence_ok += has_trace and has_shot

    n = len(all_runs)
    denom = total_acs * n
    flaky = [k for k, labels in per_ac_labels.items() if len(set(labels)) > 1]
    last = {(r.story_key, v.ac_id): v.label for r in all_runs[-1] for v in r.ac_verdicts}
    detected = [p for p in GOLD["known_issues"] if last.get((p["story"], p["ac"])) == p["expected"]]
    price_in, price_out = PRICE_PER_M.get(model, (0, 0))
    return {
        "runs": n,
        "acs_per_run": total_acs,
        "coverage": covered / denom,
        "label_accuracy": correct / denom,
        "known_issues_detected": f"{len(detected)}/{len(GOLD['known_issues'])}",
        "false_positives": false_pos,
        "flake_rate": len(flaky) / total_acs,
        "flaky_acs": [f"{k[0]} {k[1]}: {per_ac_labels[k]}" for k in flaky],
        "evidence_completeness": evidence_ok / denom,
        "story_latency_s_median": statistics.median(latencies) if latencies else 0,
        "story_latency_s_max": max(latencies) if latencies else 0,
        "llm_calls_per_run": calls / n,
        "tokens_per_run": (p_tok + c_tok) / n,
        "est_cost_usd_per_run": round((p_tok * price_in + c_tok * price_out) / 1_000_000 / n, 5),
    }


def evaluate_frames(all_frames: list[list]) -> dict:
    gold = GOLD.get("figma_frames", {})
    if not gold or not any(all_frames):
        return {}
    total = correct = 0
    labels: dict[str, set] = {}
    for frames in all_frames:
        for f in frames:
            if f.frame in gold:
                total += 1
                correct += f.label == gold[f.frame]
                labels.setdefault(f.frame, set()).add(f.label)
    return {
        "figma_frame_accuracy": correct / total if total else 0.0,
        "figma_frame_flake_rate": sum(len(v) > 1 for v in labels.values()) / len(gold),
    }


def to_markdown(metrics: dict, provider: str) -> str:
    rows = "\n".join(
        f"| {k} | {v:.0%} |" if isinstance(v, float) and k in {"coverage", "label_accuracy", "flake_rate", "evidence_completeness",
                                                              "figma_frame_accuracy", "figma_frame_flake_rate"}
        else f"| {k} | {v} |"
        for k, v in metrics.items() if k != "flaky_acs"
    )
    flaky = "\n".join(f"- {f}" for f in metrics["flaky_acs"]) or "- none"
    return f"# Eval results ({datetime.now():%Y-%m-%d %H:%M}, LLM={provider})\n\n| Metric | Value |\n|---|---|\n{rows}\n\nFlaky ACs:\n{flaky}\n"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--start-stage", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    stories = sorted(GOLD["stories"])
    all_runs, all_frames = [], []
    with stage_session(settings, args.start_stage) as up:
        if not up:
            return 2
        for i in range(args.runs):
            print(f"\n=== eval run {i + 1}/{args.runs} ===")
            _, results, frames = run_stories(settings, stories, reset=True, log=lambda *_: None)
            print("  " + " | ".join(f"{r.story_key}={r.label}" for r in results)
                  + " || " + " | ".join(f"{f.frame}={f.label}" for f in frames))
            all_runs.append(results)
            all_frames.append(frames)

    metrics = evaluate(all_runs, settings.llm_model)
    metrics.update(evaluate_frames(all_frames))
    md = to_markdown(metrics, settings.llm_provider)
    out = ROOT / "evals" / "results"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"eval-{datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text(md, encoding="utf-8")
    print("\n" + md + f"\nSaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

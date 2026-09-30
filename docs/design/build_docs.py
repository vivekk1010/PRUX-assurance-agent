"""Rebuild the design-reference figures from real runs, then render the PDF.

    python docs/design/build_docs.py [runs/<assurance-run>] [runs/<performance-run>]

1. Reads `results.json` and `eval.json` of the assurance run (default: newest run with stories)
   and `performance.json` of the performance run (default: newest `*-perf` run with samples).
2. Writes SVG charts and `run-summary.json` to `docs/design/assets/`.
3. Copies the My Blogs design and live screenshots and captures both reports.
4. Renders `prux-assurance-agent-complete-reference.md` to PDF.

Requires Playwright Chromium and network access to cdn.jsdelivr.net (marked, mermaid).
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

DESIGN = Path(__file__).resolve().parent
ROOT = DESIGN.parents[1]
ASSETS = DESIGN / "assets"
sys.path.insert(0, str(DESIGN))

from render_pdf import render  # noqa: E402

LABELS = ["PASS", "RISK", "GAP", "DEFECT"]
LABEL_COLOR = {"PASS": "#087443", "RISK": "#dc6803", "GAP": "#7a5af8", "DEFECT": "#b42318"}
STATUS_COLOR = {
    "matched": "#087443", "approved_variance": "#0f8b8d", "skipped": "#98a2b3",
    "missing": "#b42318", "mismatch": "#f04438",
}
PERF_COLOR = {"PASS": "#087443", "WARN": "#dc6803", "FAIL": "#b42318", "UNSTABLE": "#7a5af8"}
INK, MUTED, TRACK = "#18212f", "#64748b", "#e8eef5"
FONT = "font-family:Segoe UI,Inter,Arial,sans-serif"


def _svg(width: int, height: int, title: str, body: list[str]) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" style="{FONT}">'
        f'<text x="0" y="18" font-size="14" font-weight="700" fill="{INK}">{escape(title)}</text>'
        + "".join(body) + "</svg>"
    )


def _legend(keys: list[str], colors: dict[str, str], y: int = 30) -> list[str]:
    parts, x = [], 0
    for key in keys:
        parts.append(
            f'<rect x="{x}" y="{y}" width="10" height="10" fill="{colors[key]}"/>'
            f'<text x="{x + 14}" y="{y + 9}" font-size="11" fill="{MUTED}">{escape(key.replace("_", " "))}</text>'
        )
        x += 24 + 7 * len(key)
    return parts


def stacked_bars(title: str, rows: list[tuple[str, Counter]], keys: list[str],
                 colors: dict[str, str], width: int = 470, trailer: dict[str, str] | None = None) -> str:
    """One horizontal bar per row, split into segments by key; trailer text on the right."""
    row, top, label_w, right = 28, 54, 120, 76
    track = width - label_w - right
    body = _legend([k for k in keys if any(c[k] for _, c in rows)], colors)
    for i, (label, counts) in enumerate(rows):
        y, x, total = top + i * row, label_w, sum(counts.values()) or 1
        body.append(f'<text x="{label_w - 8}" y="{y + 14}" text-anchor="end" font-size="12" fill="{INK}">{escape(label)}</text>')
        for key in keys:
            if counts[key]:
                w = track * counts[key] / total
                body.append(f'<rect x="{x:.1f}" y="{y + 2}" width="{w:.1f}" height="16" fill="{colors[key]}"/>')
                if w > 16:
                    body.append(f'<text x="{x + w / 2:.1f}" y="{y + 14}" text-anchor="middle" font-size="11" '
                                f'font-weight="600" fill="white">{counts[key]}</text>')
                x += w
        tail = (trailer or {}).get(label, "")
        if tail:
            body.append(f'<text x="{label_w + track + 8}" y="{y + 14}" font-size="12" font-weight="700" '
                        f'fill="{LABEL_COLOR.get(tail, INK)}">{escape(tail)}</text>')
    return _svg(width, top + row * len(rows) + 6, title, body)


def value_bars(title: str, items: list[tuple[str, float, str]], suffix: str, width: int = 470,
               label_w: int = 120, limit: tuple[float, str] | None = None) -> str:
    """Horizontal bars scaled to the largest value; `limit` draws a dashed threshold line."""
    row, top = 26, 34
    track = width - label_w - 70
    peak = max([v for _, v, _ in items] + ([limit[0]] if limit else []), default=1) or 1
    body = []
    for i, (label, value, color) in enumerate(items):
        y, w = top + i * row, track * value / peak
        value_x = label_w + track + 6 if limit else label_w + w + 6
        body.append(
            f'<text x="{label_w - 8}" y="{y + 14}" text-anchor="end" font-size="12" fill="{INK}">{escape(label)}</text>'
            f'<rect x="{label_w}" y="{y + 2}" width="{track}" height="16" rx="3" fill="{TRACK}"/>'
            f'<rect x="{label_w}" y="{y + 2}" width="{w:.1f}" height="16" rx="3" fill="{color}"/>'
            f'<text x="{value_x:.1f}" y="{y + 14}" font-size="12" font-weight="600" fill="{INK}">'
            f"{value:g}{suffix}</text>"
        )
    bottom = top + row * len(items)
    if limit:
        x = label_w + track * limit[0] / peak
        body.append(
            f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{bottom}" stroke="{LABEL_COLOR["DEFECT"]}" '
            f'stroke-width="1.5" stroke-dasharray="4 3"/>'
            f'<text x="{x - 4:.1f}" y="{bottom + 14}" text-anchor="end" font-size="11" fill="{LABEL_COLOR["DEFECT"]}">'
            f"{escape(limit[1])}</text>"
        )
        bottom += 18
    return _svg(width, bottom + 8, title, body)


def budget_bars(title: str, budgets: list[tuple[str, float, float, bool]], width: int = 470) -> str:
    """One row per budget: actual value on a track scaled to its own limit, limit marked."""
    row, top, label_w = 40, 34, 170
    track = width - label_w - 20
    body = []
    for i, (label, actual, limit, passed) in enumerate(budgets):
        y = top + i * row
        scale = max(actual, limit) * 1.1 or 1
        w, lx = track * actual / scale, label_w + track * limit / scale
        color = LABEL_COLOR["PASS"] if passed else LABEL_COLOR["DEFECT"]
        body.append(
            f'<text x="{label_w - 8}" y="{y + 14}" text-anchor="end" font-size="11" fill="{INK}">{escape(label)}</text>'
            f'<rect x="{label_w}" y="{y + 2}" width="{track}" height="16" rx="3" fill="{TRACK}"/>'
            f'<rect x="{label_w}" y="{y + 2}" width="{w:.1f}" height="16" rx="3" fill="{color}"/>'
            f'<line x1="{lx:.1f}" y1="{y - 2}" x2="{lx:.1f}" y2="{y + 22}" stroke="{INK}" stroke-width="2"/>'
            f'<text x="{label_w}" y="{y + 32}" font-size="10" fill="{MUTED}">'
            f"actual {actual:.0f} ms · limit {limit:.0f} ms</text>"
        )
    return _svg(width, top + row * len(budgets) + 4, title, body)


def check_list(title: str, checks: dict[str, bool], width: int = 470) -> str:
    row, top = 26, 34
    body = []
    for i, (name, passed) in enumerate(checks.items()):
        y = top + i * row
        color, mark = ("#087443", "PASS") if passed else ("#b42318", "FAIL")
        body.append(
            f'<rect x="0" y="{y}" width="{width}" height="{row - 4}" rx="4" fill="{TRACK}"/>'
            f'<text x="10" y="{y + 16}" font-size="12" fill="{INK}">{escape(name.replace("_", " "))}</text>'
            f'<rect x="{width - 58}" y="{y + 3}" width="50" height="16" rx="8" fill="{color}"/>'
            f'<text x="{width - 33}" y="{y + 15}" text-anchor="middle" font-size="10" font-weight="700" fill="white">{mark}</text>'
        )
    return _svg(width, top + row * len(checks) + 4, title, body)


def _latest(predicate) -> Path:
    runs = sorted(p for p in (ROOT / "runs").iterdir() if p.is_dir() and (p / "results.json").is_file())
    for run in reversed(runs):
        if predicate(run):
            return run
    raise FileNotFoundError("no matching run under runs/")


def _has_stories(run: Path) -> bool:
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    return len(results.get("stories") or []) > 1 and bool(results.get("figma_conformance"))


def _has_samples(run: Path) -> bool:
    path = run / "performance.json"
    return path.is_file() and bool(json.loads(path.read_text(encoding="utf-8")).get("samples"))


def _screenshot(page, report: Path, target: str) -> None:
    page.goto(report.resolve().as_uri(), wait_until="load")
    page.screenshot(path=str(ASSETS / target))


def build_assets(run_dir: Path, perf_dir: Path) -> dict:
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    evaluation = json.loads((run_dir / "eval.json").read_text(encoding="utf-8"))
    performance = json.loads((perf_dir / "performance.json").read_text(encoding="utf-8"))
    perf_eval = json.loads((perf_dir / "eval.json").read_text(encoding="utf-8"))
    stories, frames = results["stories"], results["figma_conformance"]
    ASSETS.mkdir(parents=True, exist_ok=True)

    story_rows = [(s["story_key"], Counter(v["label"] for v in s["ac_verdicts"])) for s in stories]
    all_acs = Counter(v["label"] for s in stories for v in s["ac_verdicts"])
    frame_rows = [(f["frame"], Counter(c["status"] for c in f["components"])) for f in frames]
    summaries = {s["profile_id"]: s for s in performance["summaries"]}
    budgets = [
        (f'{pid} {b["statistic"]}', b["actual"], b["max_value"], b["passed"])
        for pid, s in summaries.items() for b in s["budgets"]
        if b["actual"] is not None and b["max_value"] is not None
    ]
    page_stats = summaries["blogs-page"]["statistics"]
    cold_warm = [
        (f"{metric} {mode}", round(page_stats[f"navigation.{metric}.{mode}"]["median"], 1),
         "#5235d1" if mode == "cold" else "#0f8b8d")
        for metric in ("wall_ms", "lcp_ms", "fcp_ms", "ttfb_ms") for mode in ("cold", "warm")
    ]
    max_cv = 0.35
    cv_rows = sorted(
        ((f'{pid}: {metric.split(".", 1)[1]}', round(stats["cv"], 2))
         for pid, s in summaries.items() for metric, stats in s["statistics"].items()
         if stats["cv"] > 0.05),
        key=lambda item: -item[1],
    )[:8]
    charts = {
        "run-ac-by-story.svg": stacked_bars(
            "Acceptance-criterion verdicts per story", story_rows, LABELS, LABEL_COLOR,
            trailer={s["story_key"]: s["label"] for s in stories}),
        "run-ac-labels.svg": value_bars(
            "All acceptance criteria by label", [(k, all_acs[k], LABEL_COLOR[k]) for k in LABELS], ""),
        "run-frame-components.svg": stacked_bars(
            "Figma components per frame by status", frame_rows, list(STATUS_COLOR), STATUS_COLOR,
            trailer={f["frame"]: f["label"] for f in frames}),
        "run-story-duration.svg": value_bars(
            "Story run time (seconds)",
            [(s["story_key"], round(s["duration_ms"] / 1000, 1), "#5235d1") for s in stories]
            + [(f["frame"], round(f["duration_ms"] / 1000, 1), "#0f8b8d") for f in frames], " s"),
        "run-eval-checks.svg": check_list(
            "eval.json artifact audit", {k: bool(v["passed"]) for k, v in evaluation["checks"].items()}),
        "perf-budgets.svg": budget_bars("Performance budgets (absolute limits)", budgets),
        "perf-cold-warm.svg": value_bars(
            "blogs-page medians, cold vs warm cache (ms)", cold_warm, " ms", label_w=110),
        "perf-cv.svg": value_bars(
            "Most variable metrics (coefficient of variation)",
            [(label, cv, LABEL_COLOR["DEFECT"] if cv > max_cv else "#0f8b8d") for label, cv in cv_rows],
            "", width=560, label_w=300, limit=(max_cv, f"max CV {max_cv}")),
    }
    for name, svg in charts.items():
        (ASSETS / name).write_text(svg, encoding="utf-8")

    for source, target in (("design.png", "my-blogs-design.png"), ("live.png", "my-blogs-live.png")):
        shutil.copyfile(run_dir / "figma" / "my-blogs" / source, ASSETS / target)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _screenshot(page, run_dir / "report.html", "report-overview.png")
        _screenshot(page, perf_dir / "report.html", "performance-report.png")
        browser.close()

    summary = {
        "run_id": results["meta"]["run_id"],
        "llm_provider": results["meta"]["llm_provider"],
        "embedder": results["meta"]["embedder"],
        "stories": {s["story_key"]: s["label"] for s in stories},
        "frames": {f["frame"]: f["label"] for f in frames},
        "ac_labels": dict(all_acs),
        "scenarios": sum(len(s["scenario_results"]) for s in stories),
        "steps": sum(len(r["steps"]) for s in stories for r in s["scenario_results"]),
        "eval_passed": evaluation["passed"],
        "evidence_references": evaluation["checks"]["evidence"].get("referenced"),
        "performance_run_id": performance["run_id"],
        "performance_samples": len(performance["samples"]),
        "performance_status": {pid: s["status"] for pid, s in summaries.items()},
        "performance_unstable": {pid: s["unstable_metrics"] for pid, s in summaries.items()},
        "performance_eval_passed": perf_eval["passed"],
    }
    (ASSETS / "run-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str]) -> int:
    run_dir = Path(argv[0]) if argv else _latest(_has_stories)
    perf_dir = Path(argv[1]) if len(argv) > 1 else _latest(_has_samples)
    print(json.dumps(build_assets(run_dir, perf_dir), indent=2))
    source = DESIGN / "prux-assurance-agent-complete-reference.md"
    render(source, source.with_suffix(".pdf"), "PR-UX Assurance Agent — complete reference")
    print(source.with_suffix(".pdf"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

import json
import re
import time
from pathlib import Path

import httpx

from agent.performance.models import PerformanceRun


def _metric_name(value: str) -> str:
    return "ui_quality_" + re.sub(r"[^a-zA-Z0-9_:]", "_", value)


def write_prometheus_text(run: PerformanceRun, path: Path) -> Path:
    lines = [
        "# UiQualityEvaluator performance metrics",
        "# Raw run and trace identifiers remain in artifacts to avoid high-cardinality labels.",
    ]
    for summary in run.summaries:
        for run_kind, statistics_by_metric in (
            ("current", summary.statistics), ("baseline", summary.baseline_statistics),
        ):
            for metric, stats in statistics_by_metric.items():
                labels = f'profile_id="{summary.profile_id}",scope="{summary.scope}",run_kind="{run_kind}"'
                name = _metric_name(metric)
                for statistic in ("median", "p90", "p95", "p99", "mean", "cv"):
                    lines.append(f"{name}_{statistic}{{{labels}}} {getattr(stats, statistic)}")
        lines.append(
            f'ui_quality_performance_status{{profile_id="{summary.profile_id}",'
            f'scope="{summary.scope}",status="{summary.status}"}} 1'
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_otlp_json(run: PerformanceRun, endpoint: str, timeout: float = 10.0) -> None:
    if not endpoint:
        return
    now = str(time.time_ns())
    metrics = []
    for summary in run.summaries:
        for run_kind, statistics_by_metric in (
            ("current", summary.statistics), ("baseline", summary.baseline_statistics),
        ):
            for metric, stats in statistics_by_metric.items():
                for statistic in ("median", "p90", "p95", "p99", "mean", "cv"):
                    attributes = [
                        {"key": "profile_id", "value": {"stringValue": summary.profile_id}},
                        {"key": "scope", "value": {"stringValue": summary.scope}},
                        {"key": "statistic", "value": {"stringValue": statistic}},
                        {"key": "run_kind", "value": {"stringValue": run_kind}},
                    ]
                    metrics.append({
                        "name": _metric_name(metric),
                        "gauge": {"dataPoints": [{
                            "attributes": attributes,
                            "timeUnixNano": now,
                            "asDouble": float(getattr(stats, statistic)),
                        }]},
                    })
    payload = {
        "resourceMetrics": [{
            "resource": {"attributes": [{
                "key": "service.name", "value": {"stringValue": "ui-quality-evaluator"}
            }]},
            "scopeMetrics": [{
                "scope": {"name": "ui-quality-evaluator.performance", "version": "1"},
                "metrics": metrics,
            }],
        }]
    }
    url = endpoint.rstrip("/")
    if not url.endswith("/v1/metrics"):
        url += "/v1/metrics"
    response = httpx.post(
        url, content=json.dumps(payload),
        headers={"Content-Type": "application/json"}, timeout=timeout,
    )
    response.raise_for_status()

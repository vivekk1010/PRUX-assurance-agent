import json
import secrets
import time

import httpx

from agent.evaluation.models import AdvisoryEvaluationRun, DashboardExportConfig


def _attribute(key: str, value) -> dict:
    if isinstance(value, bool):
        wrapped = {"boolValue": value}
    elif isinstance(value, (int, float)):
        wrapped = {"doubleValue": float(value)}
    else:
        wrapped = {"stringValue": str(value)}
    return {"key": key, "value": wrapped}


def export_advisory_otlp(
    run: AdvisoryEvaluationRun,
    config: DashboardExportConfig,
    timeout: float = 10.0,
) -> str | None:
    """Export advisory scores as OTLP spans for Opik, Langfuse, or another backend."""
    if not config.enabled or not config.otlp_endpoint:
        return None
    trace_id = secrets.token_hex(16)
    now = time.time_ns()
    spans = []
    for index, score in enumerate(run.scores):
        start = now + index
        spans.append(
            {
                "traceId": trace_id,
                "spanId": secrets.token_hex(8),
                "name": f"advisory.{score.metric_id}",
                "kind": 1,
                "startTimeUnixNano": str(start),
                "endTimeUnixNano": str(start + 1),
                "attributes": [
                    _attribute("assurance.run_id", run.run_id),
                    _attribute("assurance.story_key", score.story_key),
                    _attribute("evaluation.metric", score.metric_id),
                    _attribute("evaluation.score", score.score),
                    _attribute("evaluation.threshold", score.threshold),
                    _attribute("evaluation.meets_threshold", score.meets_threshold),
                    _attribute("evaluation.authoritative", False),
                    _attribute("evaluation.dashboard_backend", config.backend),
                ],
                "status": {"code": 1 if score.meets_threshold else 2},
            }
        )
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attribute("service.name", "prux-advisory-evaluator"),
                        _attribute("evaluation.engine", run.engine),
                        _attribute("evaluation.provider", run.provider),
                        _attribute("evaluation.model", run.model),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "prux.evaluation",
                            "version": str(run.schema_version),
                        },
                        "spans": spans,
                    }
                ],
            }
        ]
    }
    url = config.otlp_endpoint.rstrip("/")
    if not url.endswith("/v1/traces"):
        url += "/v1/traces"
    response = httpx.post(
        url,
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return f"{config.backend}:{url}"

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, model_validator

PerformanceScope = Literal["page", "feature", "component", "api", "load"]
PerformanceStatus = Literal["PASS", "WARN", "FAIL", "UNSTABLE", "NOT_MEASURED"]
CacheMode = Literal["cold", "warm"]


class PerformanceSelector(BaseModel):
    story: str | None = None
    test_case: str | None = None
    feature: str | None = None
    frame: str | None = None
    page: str | None = None
    component: str | None = None

    def specificity(self) -> int:
        return next((
            score for name, score in (
                ("test_case", 60), ("component", 50), ("feature", 40),
                ("frame", 35), ("page", 30), ("story", 20),
            ) if getattr(self, name)
        ), 0)


class PerformanceEndCondition(BaseModel):
    kind: Literal[
        "network-idle", "load", "dom-content-loaded", "visible",
        "hidden", "url", "response", "app-mark",
    ] = "network-idle"
    target: dict[str, str] | None = None
    value: str | None = None
    timeout_ms: int = Field(default=10000, ge=100, le=120000)


class PerformanceMeasurement(BaseModel):
    id: str
    start: Literal["navigation", "before-action", "app-mark"] = "before-action"
    end: PerformanceEndCondition = Field(default_factory=PerformanceEndCondition)
    action_index: int | None = Field(default=None, ge=0)
    metrics: list[str] = Field(default_factory=list)


class PerformanceBudget(BaseModel):
    metric: str
    statistic: Literal["median", "p75", "p90", "p95", "p99", "max", "mean"] = "p95"
    max_value: float | None = Field(default=None, ge=0)
    max_regression_percent: float | None = Field(default=None, ge=0)
    severity: Literal["warn", "fail"] = "fail"

    @model_validator(mode="after")
    def has_limit(self):
        if self.max_value is None and self.max_regression_percent is None:
            raise ValueError("performance budget requires max_value or max_regression_percent")
        return self


class BrowserPerformanceConfig(BaseModel):
    viewport: dict[str, int] = Field(default_factory=lambda: {"width": 1280, "height": 800})
    cache_modes: list[CacheMode] = Field(default_factory=lambda: ["cold", "warm"])
    warmups: int = Field(default=1, ge=0, le=20)
    iterations: int = Field(default=5, ge=1, le=100)
    cpu_slowdown: float = Field(default=1.0, ge=1.0, le=20.0)
    latency_ms: int = Field(default=0, ge=0, le=10000)
    download_kbps: int = Field(default=0, ge=0)
    upload_kbps: int = Field(default=0, ge=0)
    fresh_context_per_iteration: bool = True
    capture_trace_on_regression: bool = True


class PerformanceIntegrations(BaseModel):
    playwright: bool = True
    k6_browser: bool = False
    k6_protocol: bool = False
    lighthouse: bool = False
    opentelemetry: bool = False
    benchmarkdotnet: bool = False
    grafana_export: bool = False


class PerformanceProfile(BaseModel):
    id: str
    enabled: bool = True
    description: str = ""
    scope: PerformanceScope
    selector: PerformanceSelector = Field(default_factory=PerformanceSelector)
    path: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    measurements: list[PerformanceMeasurement] = Field(default_factory=list)
    browser: BrowserPerformanceConfig = Field(default_factory=BrowserPerformanceConfig)
    budgets: list[PerformanceBudget] = Field(default_factory=list)
    integrations: PerformanceIntegrations = Field(default_factory=PerformanceIntegrations)
    tool_options: dict[str, Any] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_scope(self):
        if self.scope in {"page", "component"} and not (self.path or self.steps):
            raise ValueError(f"{self.scope} profile requires path or steps")
        if self.scope == "load" and not self.integrations.k6_protocol:
            raise ValueError("load profile requires integrations.k6_protocol=true")
        return self


class PerformanceExportConfig(BaseModel):
    prometheus_remote_write_url: str = ""
    otlp_endpoint: str = ""
    grafana_url: str = "http://127.0.0.1:3000"
    export_raw_samples: bool = True


class PerformanceConfig(BaseModel):
    version: int = 1
    enabled: bool = False
    auto_run_with_approved_tests: bool = False
    fail_on_regression: bool = True
    require_baseline: bool = False
    profiles: list[PerformanceProfile] = Field(default_factory=list)
    export: PerformanceExportConfig = Field(default_factory=PerformanceExportConfig)


class PerformanceSample(BaseModel):
    profile_id: str
    measurement_id: str
    metric: str
    value: float
    unit: str = "ms"
    iteration: int
    cache_mode: CacheMode | Literal["n/a"] = "n/a"
    tags: dict[str, str] = Field(default_factory=dict)
    trace_id: str | None = None


class MetricStatistics(BaseModel):
    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    p75: float
    p90: float
    p95: float
    p99: float
    stddev: float
    mad: float
    cv: float


class BudgetOutcome(BaseModel):
    metric: str
    statistic: str
    actual: float | None = None
    baseline: float | None = None
    regression_percent: float | None = None
    max_value: float | None = None
    max_regression_percent: float | None = None
    passed: bool
    severity: Literal["warn", "fail"]
    reason: str


class PerformanceSummary(BaseModel):
    profile_id: str
    scope: PerformanceScope
    status: PerformanceStatus
    environment_fingerprint: str
    statistics: dict[str, MetricStatistics] = Field(default_factory=dict)
    budgets: list[BudgetOutcome] = Field(default_factory=list)
    unstable_metrics: list[str] = Field(default_factory=list)
    baseline_id: str | None = None
    baseline_statistics: dict[str, MetricStatistics] = Field(default_factory=dict)


class PerformanceRun(BaseModel):
    schema_version: int = 1
    run_id: str
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    enabled: bool = True
    summaries: list[PerformanceSummary] = Field(default_factory=list)
    samples: list[PerformanceSample] = Field(default_factory=list)
    tools: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def passed(self) -> bool:
        return all(item.status not in {"FAIL", "UNSTABLE"} for item in self.summaries)


class PerformanceBaseline(BaseModel):
    id: str
    profile_id: str
    approved_by: str
    approved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_run_id: str
    environment_fingerprint: str
    statistics: dict[str, MetricStatistics]

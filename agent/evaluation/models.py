from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AdvisoryMetricConfig(BaseModel):
    id: str
    name: str
    criteria: str
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    enabled: bool = True
    evaluation_steps: list[str] = Field(default_factory=list)


class JudgeConfig(BaseModel):
    provider: Literal["ollama", "vllm", "openai-compatible"] = "ollama"
    model: str = "qwen2.5:7b"
    base_url: str = "http://127.0.0.1:11434/v1"
    api_key_env: str = "ADVISORY_EVALUATION_API_KEY"
    timeout_seconds: float = Field(default=120.0, gt=0)


class DashboardExportConfig(BaseModel):
    enabled: bool = False
    backend: Literal["opik", "langfuse", "generic-otlp"] = "generic-otlp"
    otlp_endpoint: str = "http://127.0.0.1:4318"
    fail_open: bool = True


class AdvisoryEvaluationConfig(BaseModel):
    schema_version: int = 1
    enabled: bool = False
    engine: Literal["deepeval-geval"] = "deepeval-geval"
    authoritative: Literal[False] = False
    fail_open: bool = True
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    metrics: list[AdvisoryMetricConfig] = Field(default_factory=list)
    dashboard_export: DashboardExportConfig = Field(default_factory=DashboardExportConfig)

    @model_validator(mode="after")
    def validate_metrics(self):
        ids = [metric.id for metric in self.metrics]
        if len(ids) != len(set(ids)):
            raise ValueError("advisory metric ids must be unique")
        return self


class AdvisoryScore(BaseModel):
    story_key: str
    metric_id: str
    metric_name: str
    score: float = Field(ge=0.0, le=1.0)
    threshold: float
    meets_threshold: bool
    reason: str = ""


class AdvisoryEvaluationRun(BaseModel):
    schema_version: int = 1
    run_id: str
    enabled: bool = True
    authoritative: Literal[False] = False
    engine: str
    provider: str
    model: str
    status: Literal["COMPLETE", "PARTIAL", "ERROR", "SKIPPED"]
    meets_advisory_threshold: bool | None = None
    scores: list[AdvisoryScore] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)

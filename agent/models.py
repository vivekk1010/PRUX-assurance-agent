from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Label = Literal["PASS", "GAP", "DEFECT", "RISK"]
Check = Literal["ui", "api", "data", "calculation", "figma", "performance"]
Action = Literal[
    "goto", "fill", "click", "select",
    "expect_visible", "expect_hidden", "expect_text", "expect_value", "expect_readonly",
    "expect_url", "expect_rows",
    "check_calculation", "figma_check", "measure_load", "screenshot",
]
StepStatus = Literal["ok", "missing", "mismatch", "refused", "error", "recovered", "skipped"]
ReviewStatus = Literal["DRAFT", "APPROVED", "REJECTED", "NEEDS_CHANGE"]


class AcceptanceCriterion(BaseModel):
    id: str
    text: str


class Story(BaseModel):
    key: str
    title: str
    type: str = "Story"
    status: str = ""
    priority: str = ""
    actor: str = ""
    description: str = ""
    acceptance_criteria: list[AcceptanceCriterion]
    business_rules: list[str] = []
    figma_frames: list[str] = []
    labels: list[str] = []


class UIComponent(BaseModel):
    node_id: str
    kind: str
    label: str
    required: bool = True
    columns: Optional[list[str]] = None
    navigates_to: Optional[str] = None
    box: Optional[dict[str, float]] = None


class UXIntent(BaseModel):
    file_name: Optional[str] = None
    version: Optional[str] = None
    frames: dict[str, list[UIComponent]] = {}
    flows: list[dict[str, Any]] = []
    approved_variances: list[dict[str, Any]] = []
    frame_nodes: dict[str, str] = {}
    frame_routes: dict[str, dict[str, Any]] = {}
    frame_images: dict[str, dict[str, Any]] = {}
    features: list["UXFeature"] = []


class UXFeature(BaseModel):
    id: str
    name: str = ""
    frames: list[str] = []
    node_ids: list[str] = []
    story_keys: list[str] = []
    ac_ids: list[str] = []


class ACIntent(BaseModel):
    id: str
    text: str
    precondition: str = ""
    action: str = ""
    expected: str = ""
    checks: list[Check] = ["ui"]
    ambiguous: bool = False
    ambiguity_reason: str = ""


class IntentModel(BaseModel):
    story_key: str
    actor: str = ""
    acs: list[ACIntent]
    business_rules: list[str] = []
    ux_frames: list[str] = []
    context_sources: list[str] = []
    context_citations: list["CitationRef"] = []
    conflicts: list["ConflictNote"] = []


class Target(BaseModel):
    role: Optional[str] = None
    name: Optional[str] = None
    label: Optional[str] = None
    text: Optional[str] = None
    testid: Optional[str] = None

    def describe(self) -> str:
        parts = [f"{k}={v!r}" for k, v in self.model_dump(exclude_none=True).items()]
        return ", ".join(parts)


class Step(BaseModel):
    action: Action
    target: Optional[Target] = None
    value: Optional[str] = None
    values: Optional[list[str]] = None
    path: Optional[str] = None
    contains: Optional[str] = None
    text: Optional[str] = None
    name: Optional[str] = None
    frame: Optional[str] = None


class Scenario(BaseModel):
    id: str
    story_key: str
    ac_ids: list[str]
    title: str
    rationale: str = ""
    steps: list[Step]


class ScenarioPlan(BaseModel):
    scenarios: list[Scenario]


class CitationRef(BaseModel):
    id: str
    source: str
    chunk_id: str = ""
    score: float = 0.0
    excerpt: str = ""


class ConflictNote(BaseModel):
    kind: str
    severity: Literal["info", "warning", "error"] = "warning"
    detail: str


class TestCase(BaseModel):
    id: str
    story_key: str
    ac_ids: list[str]
    title: str
    rationale: str = ""
    steps: list[Step]
    feature_ids: list[str] = []
    figma_frames: list[str] = []
    figma_node_ids: list[str] = []
    citations: list[CitationRef] = []
    status: ReviewStatus = "DRAFT"
    reviewer: str = ""
    review_comment: str = ""
    reviewed_at: Optional[str] = None

    @classmethod
    def from_scenario(
        cls,
        scenario: Scenario,
        *,
        feature_ids: list[str] | None = None,
        frames: list[str] | None = None,
        node_ids: list[str] | None = None,
        citations: list[CitationRef] | None = None,
    ) -> "TestCase":
        return cls(
            **scenario.model_dump(),
            feature_ids=feature_ids or [],
            figma_frames=frames or [],
            figma_node_ids=node_ids or [],
            citations=citations or [],
        )

    def scenario(self) -> Scenario:
        return Scenario(**self.model_dump(include={"id", "story_key", "ac_ids", "title", "rationale", "steps"}))


class TestPlan(BaseModel):
    id: str
    version: int = 1
    story_key: str
    story_title: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_hashes: dict[str, str] = {}
    source_versions: dict[str, str] = {}
    cases: list[TestCase]
    citations: list[CitationRef] = []
    conflicts: list[ConflictNote] = []
    generator: str = ""

    @property
    def approved_cases(self) -> list[TestCase]:
        return [case for case in self.cases if case.status == "APPROVED"]

    def scenario_plan(self, approved_only: bool = True) -> ScenarioPlan:
        cases = self.approved_cases if approved_only else self.cases
        return ScenarioPlan(scenarios=[case.scenario() for case in cases])


class StepResult(BaseModel):
    index: int
    action: str
    description: str
    status: StepStatus
    detail: str = ""
    screenshot: Optional[str] = None
    data: dict[str, Any] = {}


class ScenarioResult(BaseModel):
    scenario_id: str
    ac_ids: list[str]
    title: str
    steps: list[StepResult]
    trace_path: Optional[str] = None
    network_path: Optional[str] = None
    duration_ms: int = 0


class ACVerdict(BaseModel):
    ac_id: str
    text: str
    label: Label
    rationale: str
    scenario_ids: list[str] = []
    evidence: list[str] = []


class FlowCheck(BaseModel):
    trigger_label: str
    to_frame: str
    expected_path: str
    observed_url: str = ""
    status: Literal["ok", "missing", "mismatch", "error"]
    detail: str = ""


class VisualObservation(BaseModel):
    area: str
    difference: str
    severity: Literal["low", "medium", "high"]


class VisualReview(BaseModel):
    summary: str
    observations: list[VisualObservation] = []


class FrameVerdict(BaseModel):
    frame: str
    node_id: str
    route: str
    label: Label
    rationale: str
    components: list[dict[str, Any]] = []
    flows: list[FlowCheck] = []
    design_image: Optional[str] = None
    live_image: Optional[str] = None
    design_size: dict[str, Any] = {}
    visual_review: Optional[VisualReview] = None
    trace_path: Optional[str] = None
    duration_ms: int = 0


class StoryResult(BaseModel):
    story_key: str
    title: str
    label: Label
    ac_verdicts: list[ACVerdict]
    recommendation: str = ""
    scenario_results: list[ScenarioResult] = []
    intent_path: Optional[str] = None
    scenarios_path: Optional[str] = None
    llm_usage: dict[str, Any] = {}
    duration_ms: int = 0
    error: Optional[str] = None

"""Canonical contracts shared by generation, review, export, and publication."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SourceKind(str, Enum):
    PRD = "prd"
    FIGMA = "figma"
    CONFLUENCE = "confluence"
    JIRA = "jira"
    REFERENCE = "reference"


class SourceDocument(BaseModel):
    id: str
    kind: SourceKind
    title: str
    text: str
    url: str | None = None
    metadata: dict = Field(default_factory=dict)


class Citation(BaseModel):
    source_id: str
    source_title: str
    locator: str = ""
    excerpt: str = ""


class AcceptanceCriterion(BaseModel):
    id: str
    title: str
    given: list[str] = Field(min_length=1)
    when: str
    then: list[str] = Field(min_length=1)
    negative: bool = False
    source_ids: list[str] = Field(default_factory=list)


class NonFunctionalRequirement(BaseModel):
    category: Literal[
        "accessibility",
        "availability",
        "compatibility",
        "observability",
        "performance",
        "privacy",
        "reliability",
        "security",
        "usability",
        "other",
    ]
    requirement: str
    measure: str
    source_ids: list[str] = Field(default_factory=list)


class GeneratedStory(BaseModel):
    local_id: str
    epic: str
    title: str
    persona: str
    capability: str
    benefit: str
    narrative: str
    business_value: str
    description: str
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    non_functional_requirements: list[NonFunctionalRequirement] = Field(default_factory=list)
    ux_requirements: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    analytics_requirements: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    test_notes: list[str] = Field(default_factory=list)
    definition_of_ready: list[str] = Field(default_factory=list)
    definition_of_done: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    story_points: int | None = Field(default=None, ge=1, le=100)
    priority: Literal["Highest", "High", "Medium", "Low", "Lowest"] = "Medium"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    citations: list[Citation] = Field(default_factory=list)
    review_status: Literal["DRAFT", "APPROVED", "REJECTED", "NEEDS_CHANGE"] = "DRAFT"
    reviewer: str = ""
    review_comment: str = ""
    jira_key: str | None = None

    @model_validator(mode="after")
    def narrative_matches_parts(self):
        expected = f"As a {self.persona}, I want {self.capability}, so that {self.benefit}."
        if not self.narrative.strip():
            self.narrative = expected
        return self


class StoryPackage(BaseModel):
    id: str
    title: str
    objective: str
    source_ids: list[str]
    stories: list[GeneratedStory] = Field(min_length=1)
    cross_cutting_requirements: list[str] = Field(default_factory=list)
    glossary: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    generator: str = "requirements-alchemist"


class GenerationInput(BaseModel):
    title: str = "Generated product backlog"
    objective: str = ""
    prd_text: str = ""
    source_urls: list[str] = Field(default_factory=list)
    figma_urls: list[str] = Field(default_factory=list)
    reference_query: str = ""


class PublishResult(BaseModel):
    local_id: str
    status: Literal["CREATED", "SKIPPED", "FAILED"]
    jira_key: str | None = None
    url: str | None = None
    reason: str = ""

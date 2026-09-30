"""Grounded structured generation and conversational analysis."""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

from agent.guardrails import mask_secrets
from requirements_alchemist.config import Settings
from requirements_alchemist.models import (
    AcceptanceCriterion,
    Citation,
    GeneratedStory,
    GenerationInput,
    SourceDocument,
    StoryPackage,
)
from requirements_alchemist.retrieval import RetrievedChunk

GENERATION_SYSTEM = """You are a principal product analyst and requirements engineer.
Transform only the supplied evidence into implementation-ready agile stories.

Rules:
- Do not invent business rules, UI behavior, limits, integrations, or compliance obligations.
- Put ambiguity in open_questions and assumptions; never silently resolve it.
- Make stories independently valuable and small enough for one team iteration.
- Include happy-path, negative, validation, authorization, data, and edge acceptance criteria when evidenced.
- Acceptance criteria must be observable and testable in Given/When/Then form.
- Add measurable non-functional requirements only when supported by evidence.
- Every story must cite source IDs; copied reference examples are style guidance, not product evidence.
- Keep all generated stories in DRAFT. A human owns approval and Jira publication.
- Return one JSON object matching the supplied schema exactly."""

CHAT_SYSTEM = """You are a requirements copilot. Answer from the supplied workspace context only.
Separate sourced facts from recommendations and unresolved questions. Cite source IDs in square
brackets. Never claim a Jira issue was created or a requirement approved unless the context says so.
If evidence is insufficient, say what is missing."""


class RequirementsLLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    @property
    def is_replay(self) -> bool:
        return self.settings.llm_provider == "replay"

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self.settings.llm_provider == "azure":
            from openai import AzureOpenAI

            self._client = AzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            )
        else:
            from openai import OpenAI

            key = os.getenv(self.settings.llm_api_key_env)
            if not key and "api.openai.com" in self.settings.llm_base_url:
                raise ValueError(f"{self.settings.llm_api_key_env} is required")
            self._client = OpenAI(
                api_key=key or "local-requirements-alchemist",
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout_seconds,
            )
        return self._client

    def _chat(self, messages: list[dict], *, json_mode: bool = False) -> str:
        kwargs: dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        model = (
            os.getenv("AZURE_OPENAI_DEPLOYMENT", self.settings.llm_model)
            if self.settings.llm_provider == "azure"
            else self.settings.llm_model
        )
        response = self._get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.settings.llm_temperature,
            **kwargs,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("The LLM returned an empty response")
        return content

    def generate(
        self,
        request: GenerationInput,
        sources: list[SourceDocument],
        references: list[RetrievedChunk],
    ) -> StoryPackage:
        if self.is_replay:
            return self._offline_example(request, sources)
        evidence = [
            {
                "id": source.id,
                "kind": source.kind.value,
                "title": source.title,
                "url": source.url,
                "text": source.text,
            }
            for source in sources
        ]
        examples = [
            {
                "id": item.source_id,
                "title": item.title,
                "text": item.text,
                "license": item.metadata.get("license"),
            }
            for item in references
        ]
        prompt = {
            "requested_title": request.title,
            "objective": request.objective,
            "product_evidence": evidence,
            "exemplary_story_patterns": examples,
            "output_schema": StoryPackage.model_json_schema(),
        }
        raw = self._chat(
            [
                {"role": "system", "content": GENERATION_SYSTEM},
                {
                    "role": "user",
                    "content": mask_secrets(
                        json.dumps(prompt), self.settings.secret_values()
                    ),
                },
            ],
            json_mode=True,
        )
        package = StoryPackage.model_validate_json(raw)
        return self._normalize(package, sources)

    def chat(
        self,
        question: str,
        context: list[RetrievedChunk],
        history: list[dict] | None = None,
    ) -> str:
        if self.is_replay:
            if not context:
                return "Keyless replay mode found no grounded workspace evidence for this question."
            evidence = "\n".join(
                f"- [{item.source_id}] {item.title}: "
                + " ".join(item.text.split())[:360]
                for item in context[:3]
            )
            return (
                "Keyless replay mode retrieved the following grounded evidence. "
                "Configure a live or local LLM for a synthesized answer:\n"
                f"{evidence}"
            )
        grounded = "\n\n".join(
            f"[{item.source_id}] {item.title}\n{item.text}" for item in context
        )
        messages = [{"role": "system", "content": CHAT_SYSTEM}]
        secrets = self.settings.secret_values()
        messages.extend(
            {
                **message,
                "content": mask_secrets(str(message.get("content", "")), secrets),
            }
            for message in (history or [])[-8:]
        )
        messages.append(
            {
                "role": "user",
                "content": mask_secrets(
                    f"Workspace context:\n{grounded}\n\nQuestion:\n{question}",
                    secrets,
                ),
            }
        )
        return self._chat(messages)

    @staticmethod
    def _normalize(package: StoryPackage, sources: list[SourceDocument]) -> StoryPackage:
        package.id = package.id or f"pkg-{uuid.uuid4().hex[:10]}"
        valid_sources = {source.id for source in sources}
        package.source_ids = sorted(set(package.source_ids) & valid_sources) or sorted(valid_sources)
        for story_index, story in enumerate(package.stories, 1):
            story.local_id = f"STORY-{story_index:03d}"
            story.review_status = "DRAFT"
            story.jira_key = None
            for criterion_index, criterion in enumerate(story.acceptance_criteria, 1):
                criterion.id = f"AC-{criterion_index:02d}"
                criterion.source_ids = sorted(set(criterion.source_ids) & valid_sources)
            story.citations = [
                citation for citation in story.citations if citation.source_id in valid_sources
            ]
        return package

    @staticmethod
    def _offline_example(
        request: GenerationInput, sources: list[SourceDocument]
    ) -> StoryPackage:
        source_ids = [source.id for source in sources]
        objective = request.objective or "Review supplied product intent"
        title = request.title or "Generated backlog"
        story = GeneratedStory(
            local_id="STORY-001",
            epic=title,
            title=f"Clarify and deliver {objective[:70]}",
            persona="product user",
            capability=objective.lower().rstrip("."),
            benefit="the evidenced product outcome can be achieved",
            narrative="",
            business_value="Derived from the supplied product objective.",
            description=(
                "Offline replay example. Configure a live LLM to decompose all supplied "
                "requirements into production stories."
            ),
            acceptance_criteria=[
                AcceptanceCriterion(
                    id="AC-01",
                    title="Evidence-backed outcome",
                    given=["the supplied requirement sources are available"],
                    when="the user performs the described capability",
                    then=["the evidenced outcome is observable"],
                    source_ids=source_ids,
                )
            ],
            open_questions=["Which source details define the complete expected behavior?"],
            definition_of_ready=["Open questions are resolved", "Acceptance criteria are reviewed"],
            definition_of_done=["Acceptance criteria pass", "Evidence is attached"],
            confidence=0.2,
            citations=[
                Citation(source_id=s.id, source_title=s.title, excerpt=s.text[:180])
                for s in sources[:3]
            ],
        )
        return StoryPackage(
            id=f"pkg-{uuid.uuid4().hex[:10]}",
            title=title,
            objective=objective,
            source_ids=source_ids,
            stories=[story],
            generation_notes=["Generated in replay mode; human refinement is required."],
        )

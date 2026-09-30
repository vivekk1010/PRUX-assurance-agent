"""Auditable local BM25 retrieval over source material and exemplary stories."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from rag.lexical import BM25
from requirements_alchemist.models import GeneratedStory, SourceDocument, SourceKind


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    source_id: str
    title: str
    text: str
    score: float
    metadata: dict


def _chunks(text: str, size: int = 1_600, overlap: int = 240) -> list[str]:
    clean = re.sub(r"\r\n?", "\n", text).strip()
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        if end < len(clean):
            boundary = max(clean.rfind("\n", start, end), clean.rfind(". ", start, end))
            if boundary > start + size // 2:
                end = boundary + 1
        chunks.append(clean[start:end].strip())
        if end >= len(clean):
            break
        start = max(start + 1, end - overlap)
    return chunks


class ReferenceCorpus:
    def __init__(self, reference_dir: Path):
        self.reference_dir = reference_dir
        self.documents: list[SourceDocument] = []
        self._entries: list[dict] = []
        self._index = BM25([])

    def rebuild(self, source_documents: list[SourceDocument] | None = None) -> None:
        documents = list(source_documents or [])
        for path in sorted(self.reference_dir.rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for item in payload if isinstance(payload, list) else [payload]:
                text = item.get("text") or json.dumps(item.get("story", item), indent=2)
                documents.append(
                    SourceDocument(
                        id=item.get("id", f"reference-{path.stem}"),
                        kind=SourceKind.REFERENCE,
                        title=item.get("title", path.stem),
                        text=text,
                        url=item.get("source_url"),
                        metadata={
                            "license": item.get("license", "user-supplied"),
                            "provenance": item.get("provenance", str(path.name)),
                        },
                    )
                )
        self.documents = documents
        self._entries = []
        for document in documents:
            for index, text in enumerate(_chunks(document.text), 1):
                self._entries.append(
                    {
                        "id": f"{document.id}#chunk-{index}",
                        "source_id": document.id,
                        "title": document.title,
                        "text": text,
                        "metadata": document.metadata,
                    }
                )
        self._index = BM25(entry["text"] for entry in self._entries)

    def search(self, query: str, k: int = 6) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(score=hit.score, **self._entries[hit.index])
            for hit in self._index.search(query, k=k)
        ]

    def add_exemplary_story(
        self,
        story: GeneratedStory,
        *,
        reviewer: str,
        provenance: str = "human-approved",
    ) -> Path:
        if story.review_status != "APPROVED":
            raise ValueError("Only APPROVED stories can enter the exemplary-story corpus")
        target = self.reference_dir / "user"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{uuid.uuid4().hex}.json"
        path.write_text(
            json.dumps(
                {
                    "id": f"user-reference-{story.local_id}",
                    "title": story.title,
                    "text": json.dumps(story.model_dump(), indent=2),
                    "license": "user-supplied",
                    "provenance": provenance,
                    "reviewer": reviewer,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

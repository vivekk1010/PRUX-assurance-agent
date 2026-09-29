import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from rag.freshness import SCHEMA_VERSION


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    meta: dict = field(default_factory=dict)


@dataclass
class Hit:
    chunk: Chunk
    score: float
    scores: dict[str, float] = field(default_factory=dict)
    rank: int = 0


def _values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def matches_filters(chunk: Chunk, filters: dict[str, Any] | None = None) -> bool:
    """Return whether a chunk matches all supplied metadata filters.

    Singular and plural spellings are accepted to keep the public retrieval API
    convenient (`doc_type`/`doc_types`, `rule_id`/`rule_ids`, and so on).
    Values within one filter are ORed; separate filters are ANDed.
    """
    if not filters:
        return True
    source_prefix = filters.get("source_prefix")
    if source_prefix and not chunk.source.startswith(str(source_prefix)):
        return False
    aliases = {
        "doc_types": "doc_type",
        "stories": "story",
        "acs": "ac",
        "rule_ids": "rule_id",
        "frames": "frame",
        "features": "feature",
        "labels": "labels",
    }
    ignored = {"source_prefix", "exclude_doc_types"}
    for requested_key, requested_value in filters.items():
        if requested_key in ignored or requested_value is None:
            continue
        key = aliases.get(requested_key, requested_key)
        actual = _values(chunk.meta.get(key))
        requested = _values(requested_value)
        if requested and not actual.intersection(requested):
            return False
    excluded = _values(filters.get("exclude_doc_types"))
    if excluded and str(chunk.meta.get("doc_type", "")) in excluded:
        return False
    return True


class VectorStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.chunks: list[Chunk] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self.embedder_name = ""
        self.schema_version = SCHEMA_VERSION
        self.manifest: dict[str, Any] = {}

    @property
    def exists(self) -> bool:
        return (self.directory / "chunks.json").exists()

    def build(self, chunks: list[Chunk], vectors: np.ndarray, embedder_name: str) -> None:
        self.chunks, self.vectors, self.embedder_name = chunks, vectors, embedder_name

    def save(self, manifest: dict[str, Any] | None = None) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        np.save(self.directory / "vectors.npy", self.vectors)
        (self.directory / "chunks.json").write_text(
            json.dumps({
                "schema_version": self.schema_version,
                "embedder": self.embedder_name,
                "chunks": [asdict(c) for c in self.chunks],
            }, indent=1),
            encoding="utf-8",
        )
        if manifest is not None:
            self.manifest = manifest
            (self.directory / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )

    def load(self) -> "VectorStore":
        data = json.loads((self.directory / "chunks.json").read_text(encoding="utf-8"))
        self.schema_version = int(data.get("schema_version", 1))
        self.embedder_name = data["embedder"]
        self.chunks = [Chunk(**c) for c in data["chunks"]]
        self.vectors = np.load(self.directory / "vectors.npy")
        manifest_path = self.directory / "manifest.json"
        self.manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {}
        )
        return self

    def candidate_indexes(
        self,
        source_prefix: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[int]:
        combined = dict(filters or {})
        if source_prefix is not None:
            combined["source_prefix"] = source_prefix
        return [
            index for index, chunk in enumerate(self.chunks)
            if matches_filters(chunk, combined)
        ]

    def search(
        self,
        query_vec: np.ndarray,
        k: int = 5,
        source_prefix: str | None = None,
        *,
        filters: dict[str, Any] | None = None,
        min_score: float | None = None,
    ) -> list[Hit]:
        if not self.chunks:
            return []
        scores = self.vectors @ query_vec.reshape(-1)
        candidates = self.candidate_indexes(source_prefix, filters)
        order = sorted(candidates, key=lambda index: (-float(scores[index]), index))
        hits = []
        for i in order:
            chunk = self.chunks[int(i)]
            score = float(scores[i])
            if min_score is not None and score < min_score:
                continue
            hits.append(Hit(chunk, score, {"dense": score}, len(hits) + 1))
            if len(hits) == k:
                break
        return hits

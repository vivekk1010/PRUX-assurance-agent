from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from rag.embeddings import HashingEmbedder, get_embedder
from rag.freshness import FreshnessReport, check_freshness
from rag.lexical import BM25, tokenize
from rag.store import Hit, VectorStore


@dataclass(frozen=True)
class FilterSpec:
    source_prefix: str | None = None
    doc_types: set[str] | None = None
    story: str | None = None
    ac: str | None = None
    rule_ids: set[str] | None = None
    frames: set[str] | None = None
    features: set[str] | None = None
    labels: set[str] | None = None
    exclude_doc_types: set[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class Retriever:
    def __init__(
        self, index_dir: Path, *, default_mode: str = "hybrid",
        default_min_score: float | None = None, default_rrf_k: int = 60,
    ):
        self.index_dir = index_dir
        self.default_mode = default_mode
        self.default_min_score = default_min_score
        self.default_rrf_k = default_rrf_k
        self.store = VectorStore(index_dir).load()
        if self.store.embedder_name.startswith("openai:"):
            self.embedder = get_embedder("openai", self.store.embedder_name.split(":", 1)[1])
        else:
            match = re.search(r"hashing-(\d+)", self.store.embedder_name)
            self.embedder = HashingEmbedder(int(match.group(1)) if match else 512)
        self.bm25 = BM25(chunk.text for chunk in self.store.chunks)

    def search(
        self,
        query: str,
        k: int = 5,
        source_prefix: str | None = None,
        *,
        filters: dict[str, Any] | FilterSpec | None = None,
        min_score: float | None = None,
        threshold: float | None = None,
        mode: str | None = None,
        rrf_k: int | None = None,
    ) -> list[Hit]:
        """Search the index.

        The original positional arguments remain unchanged. New callers can
        select dense, lexical, or hybrid retrieval and apply metadata filters.
        Hybrid is deterministic reciprocal-rank fusion of BM25 and dense ranks.
        """
        if k <= 0:
            return []
        mode = mode or self.default_mode
        rrf_k = rrf_k or self.default_rrf_k
        if mode not in {"hybrid", "dense", "lexical"}:
            raise ValueError("mode must be 'hybrid', 'dense', or 'lexical'")
        if min_score is not None and threshold is not None and min_score != threshold:
            raise ValueError("use either min_score or threshold, not conflicting values")
        minimum = threshold if threshold is not None else (
            min_score if min_score is not None else self.default_min_score
        )
        filter_dict = filters.to_dict() if isinstance(filters, FilterSpec) else dict(filters or {})
        if source_prefix is not None:
            filter_dict["source_prefix"] = source_prefix
        candidates = self.store.candidate_indexes(filters=filter_dict)
        if not candidates:
            return []

        query_vector = self.embedder.embed([query])[0]
        dense_values = self.store.vectors @ query_vector.reshape(-1)
        dense_order = sorted(candidates, key=lambda index: (-float(dense_values[index]), index))
        lexical_values = self.bm25.scores(query, candidates)
        lexical_order = sorted(
            (index for index in candidates if lexical_values[index] > 0.0),
            key=lambda index: (-lexical_values[index], index),
        )

        if mode == "dense":
            return self._single_channel_hits(
                dense_order, dense_values, "dense", k, minimum
            )
        if mode == "lexical":
            return self._single_channel_hits(
                lexical_order, lexical_values, "lexical", k, minimum
            )

        dense_ranks = {index: rank for rank, index in enumerate(dense_order, 1)}
        lexical_ranks = {index: rank for rank, index in enumerate(lexical_order, 1)}
        query_tokens = set(tokenize(query))
        exact_rule_ids = {token.upper() for token in re.findall(
            r"\bBR-[A-Z0-9]+-\d+\b", query, re.IGNORECASE
        )}
        scored: list[tuple[int, float, dict[str, float]]] = []
        maximum_rrf = 2.0 / (rrf_k + 1)
        for index in candidates:
            rrf = 1.0 / (rrf_k + dense_ranks[index])
            if index in lexical_ranks:
                rrf += 1.0 / (rrf_k + lexical_ranks[index])
            rrf_normalized = rrf / maximum_rrf
            heading_tokens = set(tokenize(str(self.store.chunks[index].meta.get("heading", ""))))
            overlap = len(query_tokens.intersection(heading_tokens)) / max(1, len(query_tokens))
            exact = (
                1.0
                if str(self.store.chunks[index].meta.get("rule_id", "")).upper() in exact_rule_ids
                else 0.0
            )
            final = min(1.0, 0.90 * rrf_normalized + 0.05 * overlap + 0.05 * exact)
            scored.append((index, final, {
                "dense": float(dense_values[index]),
                "lexical": float(lexical_values[index]),
                "rrf": rrf,
                "final": final,
            }))
        scored.sort(key=lambda item: (-item[1], self.store.chunks[item[0]].id))
        hits = []
        for index, score, scores in scored:
            if minimum is not None and score < minimum:
                continue
            hits.append(Hit(self.store.chunks[index], score, scores, len(hits) + 1))
            if len(hits) == k:
                break
        return hits

    def _single_channel_hits(
        self,
        order: Iterable[int],
        values: Any,
        channel: str,
        k: int,
        minimum: float | None,
    ) -> list[Hit]:
        hits = []
        for index in order:
            score = float(values[index])
            if minimum is not None and score < minimum:
                continue
            hits.append(Hit(
                self.store.chunks[index], score, {channel: score}, len(hits) + 1
            ))
            if len(hits) == k:
                break
        return hits

    def lookup_rule(self, rule_id: str):
        wanted = rule_id.strip().upper()
        return next(
            (
                chunk for chunk in self.store.chunks
                if str(chunk.meta.get("rule_id", "")).upper() == wanted
            ),
            None,
        )

    def search_exact_rules(self, rule_ids: str | Iterable[str]) -> list[Hit]:
        requested = [rule_ids] if isinstance(rule_ids, str) else list(rule_ids)
        hits = []
        for rule_id in requested:
            chunk = self.lookup_rule(rule_id)
            if chunk is not None:
                hits.append(Hit(
                    chunk,
                    1.0,
                    {"exact": 1.0},
                    len(hits) + 1,
                ))
        return hits

    exact_rule_lookup = lookup_rule

    def freshness(
        self,
        stories_dir: Path,
        knowledge_dir: Path,
        *,
        ux: dict[str, Any] | None = None,
        embedder_name: str | None = None,
    ) -> FreshnessReport:
        return check_freshness(
            self.index_dir,
            stories_dir,
            knowledge_dir,
            ux=ux,
            embedder_name=embedder_name or self.store.embedder_name,
        )

    @staticmethod
    def format(hits: list[Hit]) -> str:
        return "\n\n".join(
            f"[C{index}] {hit.chunk.source} (score {hit.score:.3f})\n{hit.chunk.text}"
            for index, hit in enumerate(hits, 1)
        )

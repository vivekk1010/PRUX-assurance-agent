"""Small, deterministic BM25 implementation used by the local RAG index."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Tokenize consistently across platforms and without external packages."""
    return TOKEN_RE.findall(text.lower())


@dataclass(frozen=True)
class BM25Hit:
    index: int
    score: float


class BM25:
    """Okapi BM25 over an in-memory collection.

    The project corpus is intentionally small, so a compact in-memory index is
    faster to load and easier to audit than a native search dependency.
    """

    def __init__(self, documents: Iterable[str], k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.term_frequencies = [Counter(tokenize(text)) for text in documents]
        self.lengths = [sum(tf.values()) for tf in self.term_frequencies]
        self.document_count = len(self.term_frequencies)
        self.average_length = (
            sum(self.lengths) / self.document_count if self.document_count else 0.0
        )
        self.document_frequencies: Counter[str] = Counter()
        for frequencies in self.term_frequencies:
            self.document_frequencies.update(frequencies.keys())

    def scores(self, query: str, candidates: Iterable[int] | None = None) -> dict[int, float]:
        terms = list(dict.fromkeys(tokenize(query)))
        indexes = range(self.document_count) if candidates is None else candidates
        result: dict[int, float] = {}
        for index in indexes:
            score = 0.0
            frequencies = self.term_frequencies[index]
            length = self.lengths[index]
            for term in terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self.document_frequencies[term]
                inverse_document_frequency = math.log(
                    1.0 + (self.document_count - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                normalization = frequency + self.k1 * (
                    1.0 - self.b
                    + self.b * length / (self.average_length or 1.0)
                )
                score += inverse_document_frequency * frequency * (self.k1 + 1.0) / normalization
            result[index] = score
        return result

    def search(
        self, query: str, k: int = 10, candidates: Iterable[int] | None = None
    ) -> list[BM25Hit]:
        scores = self.scores(query, candidates)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [BM25Hit(index, score) for index, score in ranked[:k] if score > 0.0]

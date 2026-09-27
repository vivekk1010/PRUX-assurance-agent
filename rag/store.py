import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np


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


class VectorStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.chunks: list[Chunk] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self.embedder_name = ""

    @property
    def exists(self) -> bool:
        return (self.directory / "chunks.json").exists()

    def build(self, chunks: list[Chunk], vectors: np.ndarray, embedder_name: str) -> None:
        self.chunks, self.vectors, self.embedder_name = chunks, vectors, embedder_name

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        np.save(self.directory / "vectors.npy", self.vectors)
        (self.directory / "chunks.json").write_text(
            json.dumps({"embedder": self.embedder_name, "chunks": [asdict(c) for c in self.chunks]}, indent=1),
            encoding="utf-8",
        )

    def load(self) -> "VectorStore":
        data = json.loads((self.directory / "chunks.json").read_text(encoding="utf-8"))
        self.embedder_name = data["embedder"]
        self.chunks = [Chunk(**c) for c in data["chunks"]]
        self.vectors = np.load(self.directory / "vectors.npy")
        return self

    def search(self, query_vec: np.ndarray, k: int = 5, source_prefix: str | None = None) -> list[Hit]:
        if not self.chunks:
            return []
        scores = self.vectors @ query_vec.reshape(-1)
        order = np.argsort(-scores)
        hits = []
        for i in order:
            chunk = self.chunks[int(i)]
            if source_prefix and not chunk.source.startswith(source_prefix):
                continue
            hits.append(Hit(chunk, float(scores[i])))
            if len(hits) == k:
                break
        return hits

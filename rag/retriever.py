from pathlib import Path

from rag.embeddings import HashingEmbedder, get_embedder
from rag.store import Hit, VectorStore


class Retriever:
    def __init__(self, index_dir: Path):
        self.store = VectorStore(index_dir).load()
        if self.store.embedder_name.startswith("openai:"):
            self.embedder = get_embedder("openai", self.store.embedder_name.split(":", 1)[1])
        else:
            self.embedder = HashingEmbedder()

    def search(self, query: str, k: int = 5, source_prefix: str | None = None) -> list[Hit]:
        return self.store.search(self.embedder.embed([query])[0], k=k, source_prefix=source_prefix)

    @staticmethod
    def format(hits: list[Hit]) -> str:
        return "\n\n".join(f"[{h.chunk.source}] (score {h.score:.2f})\n{h.chunk.text}" for h in hits)

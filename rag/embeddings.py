import hashlib
import re

import numpy as np


class HashingEmbedder:
    """Offline embedder: hashed unigrams + bigrams. No key, no model download, deterministic."""

    name = "hashing-512"

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _tokens(self, text: str) -> list[str]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for tok in self._tokens(text):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


class OpenAIEmbedder:
    def __init__(self, model: str):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model
        self.name = f"openai:{model}"

    def embed(self, texts: list[str]) -> np.ndarray:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        vecs = np.array([d.embedding for d in resp.data], dtype=np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def get_embedder(provider: str, model: str = "text-embedding-3-small"):
    if provider == "openai":
        return OpenAIEmbedder(model)
    return HashingEmbedder()

"""
Embedding adapters.

Defines an EmbeddingAdapter protocol and ships two implementations:

    MockEmbedder    - deterministic hash-based vectors. No network calls.
                      Good enough for tests and the demo.
    OpenAIEmbedder  - thin wrapper around openai.embeddings (optional dep).

Domain integrators are expected to plug their own adapter (a hosted embeddings
service, a local sentence-transformers model, etc.) by implementing `embed`.
"""

from __future__ import annotations

import hashlib
import os
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Anything that can turn a list of texts into a 2D ndarray of floats."""

    def embed(self, texts: list[str]) -> np.ndarray:
        ...


class MockEmbedder:
    """
    Deterministic, no-network embedder.

    For each input text we draw `dim` floats from a numpy random stream seeded
    from a stable hash of the text. Same text -> same vector across runs and
    across machines. Decent for clustering toy data; useless for real semantics.
    """

    def __init__(self, dim: int = 128):
        if dim < 8:
            raise ValueError("dim must be >= 8")
        self.dim = dim

    def _seed(self, text: str) -> int:
        h = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(h, byteorder="big", signed=False)

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            rng = np.random.default_rng(self._seed(t))
            v = rng.standard_normal(self.dim).astype(np.float32)
            # L2-normalize so distances behave like cosine.
            n = np.linalg.norm(v)
            out[i] = v / n if n > 0 else v
        return out


class OpenAIEmbedder:
    """Optional adapter for OpenAI embeddings. Requires `openai` package."""

    def __init__(
        self,
        model:   str = "text-embedding-3-small",
        api_key: str | None = None,
        batch:   int = 100,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "OpenAIEmbedder requires the `openai` package. "
                "Install with: pip install beliefstack[openai]"
            ) from e
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.model  = model
        self.batch  = batch

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 1536), dtype=np.float32)
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            chunk = texts[i : i + self.batch]
            resp  = self.client.embeddings.create(model=self.model, input=chunk)
            out.extend(d.embedding for d in resp.data)
        return np.asarray(out, dtype=np.float32)


def get_default_embedder() -> EmbeddingAdapter:
    """
    Return OpenAIEmbedder if `OPENAI_API_KEY` is set and the openai package is
    importable; otherwise return MockEmbedder. Lets the demo run anywhere.
    """
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAIEmbedder()
        except ImportError:
            pass
    return MockEmbedder()

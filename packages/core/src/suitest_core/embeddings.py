"""Local text embeddings (M4-2) — fastembed BAAI/bge-small, deterministic mock fallback.

Embeddings power semantic search over test cases WITHOUT a cloud LLM — they run
in the ``ZERO + fastembed`` combo (``SUITEST_EMBEDDINGS=fastembed``). The model
is the 384-dimensional ``BAAI/bge-small-en-v1.5`` which fastembed runs on CPU via
ONNX, so an air-gapped / ZERO-tier deploy gets semantic search with no API key.

ZERO-safe: ``fastembed`` is lazy-imported only when the env opts in. With
``SUITEST_EMBEDDINGS`` unset/``none`` there is no embedder and callers degrade to
lexical search. Tests + deterministic eval use :class:`MockEmbedder`, a
hash-seeded embedder that needs no model download.

The :class:`Embedder` Protocol is intentionally tiny (``dimension`` + ``embed``)
so a future provider (OpenAI embeddings, a different local model) drops in
without touching call sites.
"""

from __future__ import annotations

import hashlib
import math
import os
from itertools import pairwise
from typing import Final, Protocol, runtime_checkable

EMBED_DIM: Final[int] = 384
DEFAULT_MODEL: Final[str] = "BAAI/bge-small-en-v1.5"


@runtime_checkable
class Embedder(Protocol):
    """Maps text to a fixed-dimension unit-ish vector."""

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class MockEmbedder:
    """Deterministic, dependency-free embedder for ZERO eval + tests.

    Hashes token shingles into a fixed vector so similar strings land near each
    other under cosine. NOT semantically meaningful — only stable + cheap. Real
    semantic quality requires :class:`FastEmbedEmbedder`.
    """

    def __init__(self, dimension: int = EMBED_DIM) -> None:
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = text.lower().split()
        # Unigrams + bigrams hashed into buckets — gives lexical overlap a
        # cosine signal without any model.
        grams = tokens + [f"{a}_{b}" for a, b in pairwise(tokens)]
        for gram in grams:
            h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=4).digest(), "big")
            vec[h % self._dim] += 1.0
        return _l2_normalize(vec)


class FastEmbedEmbedder:
    """Local CPU embeddings via fastembed (ONNX). Model downloaded once + cached.

    Lazy: the ``fastembed`` import + model load happen on first ``embed`` so
    importing this module stays cheap and ZERO-safe.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: object | None = None

    @property
    def dimension(self) -> int:
        return EMBED_DIM

    def _ensure_model(self) -> object:
        if self._model is None:
            from fastembed import TextEmbedding  # lazy — heavy import

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        # fastembed yields numpy arrays; normalise to plain float lists so the
        # rest of the stack never depends on numpy types.
        embed_fn = model.embed  # type: ignore[attr-defined]
        return [list(map(float, vec)) for vec in embed_fn(texts)]


def get_embedder() -> Embedder | None:
    """Resolve the configured embedder from env, or ``None`` (lexical fallback).

    ``SUITEST_EMBEDDINGS``: ``fastembed`` → real local model; ``mock`` →
    deterministic test embedder; unset / ``none`` / ``disabled`` → ``None``.
    """
    choice = os.environ.get("SUITEST_EMBEDDINGS", "none").strip().lower()
    if choice in {"", "none", "disabled"}:
        return None
    if choice == "mock":
        return MockEmbedder()
    if choice == "fastembed":
        return FastEmbedEmbedder(os.environ.get("SUITEST_EMBEDDINGS_MODEL", DEFAULT_MODEL))
    raise ValueError(f"unknown SUITEST_EMBEDDINGS={choice!r} (expected fastembed|mock|none)")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 if either is zero."""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]

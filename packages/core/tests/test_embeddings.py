"""Tests for local embeddings + semantic search ranking (M4-2)."""

from __future__ import annotations

import pytest
from suitest_core.embeddings import (
    EMBED_DIM,
    MockEmbedder,
    cosine_similarity,
    get_embedder,
)


def test_mock_embedder_is_deterministic_and_dimensioned() -> None:
    e = MockEmbedder()
    a = e.embed(["login flow checkout"])[0]
    b = e.embed(["login flow checkout"])[0]
    assert len(a) == EMBED_DIM
    assert a == b


def test_cosine_similar_text_scores_higher() -> None:
    e = MockEmbedder()
    vecs = e.embed(["user can log in with email", "user login email password", "delete account"])
    query, near, far = vecs
    assert cosine_similarity(query, near) > cosine_similarity(query, far)


def test_get_embedder_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUITEST_EMBEDDINGS", raising=False)
    assert get_embedder() is None
    monkeypatch.setenv("SUITEST_EMBEDDINGS", "mock")
    assert isinstance(get_embedder(), MockEmbedder)
    monkeypatch.setenv("SUITEST_EMBEDDINGS", "bogus")
    with pytest.raises(ValueError, match="unknown SUITEST_EMBEDDINGS"):
        get_embedder()


def test_cosine_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity([1.0, 0.0], [1.0])

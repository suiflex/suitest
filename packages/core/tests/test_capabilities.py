"""Capability primitives are driven by workspace LLM readiness."""

import pytest
from suitest_core.capabilities import (
    AutonomyLevel,
    compute_autonomy,
    compute_features,
    resolve_capabilities,
    resolve_embeddings,
)


def test_embeddings_env_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITEST_EMBEDDINGS_BACKEND", "fastembed")
    config = resolve_embeddings()
    assert config.enabled is False
    assert config.backend == "none"


def test_base_capabilities_are_manual_only() -> None:
    snapshot = resolve_capabilities()
    assert snapshot.features["manual_tcm"] is True
    assert snapshot.features["deterministic_runner"] is False
    assert snapshot.features["ai_generation"] is False
    assert snapshot.autonomy.available == [AutonomyLevel.MANUAL]
    assert "tier" not in snapshot.model_dump()


def test_validated_llm_enables_execution_and_ai() -> None:
    features = compute_features(True, resolve_embeddings())
    assert features["manual_tcm"] is True
    assert features["deterministic_runner"] is True
    assert features["ai_generation"] is True
    assert features["semantic_search"] is False

    autonomy = compute_autonomy(True)
    assert autonomy.default is AutonomyLevel.ASSIST
    assert AutonomyLevel.AUTO in autonomy.available

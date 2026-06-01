"""M3-5 prompt loader + drift guard tests — pure filesystem, no DB."""

from __future__ import annotations

import pytest
from suitest_agent.prompts.loader import (
    PromptDriftError,
    PromptNotFoundError,
    load,
    prompt_hash,
    prompt_id,
    read_prompt,
)

_CORE_PROMPTS = ["generate-from-prd", "translate-step", "diagnose-failure", "converse"]


@pytest.mark.parametrize("name", _CORE_PROMPTS)
def test_core_prompts_exist_and_load(name: str) -> None:
    text = read_prompt(name, "v1")
    assert text.strip()


def test_prompt_hash_is_stable() -> None:
    assert prompt_hash("abc") == prompt_hash("abc")
    assert prompt_hash("abc") != prompt_hash("abd")
    assert len(prompt_hash("abc")) == 64


def test_prompt_id_canonical_format() -> None:
    content = read_prompt("generate-from-prd", "v1")
    pid = prompt_id("generate-from-prd", "v1", content)
    assert pid.startswith("v1/generate-from-prd@sha256:")
    assert pid.endswith(prompt_hash(content))


def test_load_passes_when_stored_hash_matches() -> None:
    content = read_prompt("converse", "v1")
    assert load("converse", "v1", stored_hash=prompt_hash(content)) == content


def test_load_raises_drift_on_hash_mismatch() -> None:
    with pytest.raises(PromptDriftError) as exc:
        load("converse", "v1", stored_hash="deadbeef")
    assert "Bump the version (create v2)" in str(exc.value)


def test_read_missing_prompt_raises() -> None:
    with pytest.raises(PromptNotFoundError):
        read_prompt("does-not-exist", "v1")

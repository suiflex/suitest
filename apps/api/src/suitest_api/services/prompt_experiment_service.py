"""Prompt A/B selection (M5-4).

:func:`choose_variant` is a pure, deterministic, ratio-preserving selector — it
serves whichever variant is currently under its target impression share, so over
many calls the B:A ratio converges to ``split_pct`` without any RNG (keeping runs
reproducible). The resolver calls it, records an impression, and returns the
chosen variant's content.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from suitest_db.models.prompt_experiment import PromptExperiment

Variant = Literal["A", "B"]


def choose_variant(a_impressions: int, b_impressions: int, split_pct: int) -> Variant:
    """Return ``"A"`` or ``"B"`` keeping B's share near ``split_pct`` percent."""
    if split_pct <= 0:
        return "A"
    if split_pct >= 100:
        return "B"
    total = a_impressions + b_impressions
    # Serve B while it is below its target share of impressions.
    if b_impressions * 100 < split_pct * total:
        return "B"
    return "A"


def variant_override_id(experiment: PromptExperiment, variant: Variant) -> str | None:
    """The override id backing ``variant`` (``None`` means the file default)."""
    return experiment.variant_a_override_id if variant == "A" else experiment.variant_b_override_id

"""Autonomy resolver (M3-15 / M3-16, docs/AUTONOMY.md §3, §5).

Autonomy is orthogonal to capability tier: the tier decides what *exists*, the
autonomy level + per-feature overrides decide how much the agent does without a
human. This module owns the canonical override-key set and the level→effective
resolution (``effective(key) = override.get(key, default_for_level(key))``).

The booleans here are the machine-readable contract gating logic consumes; the
richer §3 matrix (enum-valued, e.g. ``exec_agentic_step = "confirm"``) is a UI
presentation concern derived from the same levels.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from suitest_core.capabilities import AutonomyLevel

# Canonical override keys an admin may flip within a level (AUTONOMY.md §5).
# ``auto_pr_fix`` is v2.x (opt-in even in ``auto``); kept here so the key
# validates today and the toggle can render disabled.
KNOWN_OVERRIDE_KEYS: frozenset[str] = frozenset(
    {
        "gen_finalize_p2p3",
        "gen_dedupe_auto_merge",
        "exec_agentic_no_prompt",
        "exec_self_heal_enabled",
        "diagnose_auto_categorize",
        "defect_auto_file",
        "defect_close_flaky",
        "flaky_auto_rerun",
        "code_export_on_failure",
        "auto_pr_fix",
    }
)

# Per-level default for each override key (AUTONOMY.md §3 matrix, projected to
# booleans). ``manual`` is all-off; higher levels switch behaviors on. Safety
# rails (AUTONOMY.md §9) are enforced separately and always win.
_LEVEL_DEFAULTS: dict[AutonomyLevel, dict[str, bool]] = {
    AutonomyLevel.MANUAL: dict.fromkeys(KNOWN_OVERRIDE_KEYS, False),
    AutonomyLevel.ASSIST: {
        **dict.fromkeys(KNOWN_OVERRIDE_KEYS, False),
        "defect_auto_file": True,  # AI files, human edits severity
    },
    AutonomyLevel.SEMI_AUTO: {
        **dict.fromkeys(KNOWN_OVERRIDE_KEYS, False),
        "gen_finalize_p2p3": True,
        "exec_agentic_no_prompt": True,
        "diagnose_auto_categorize": True,
        "defect_auto_file": True,
        "flaky_auto_rerun": True,
    },
    AutonomyLevel.AUTO: {
        **dict.fromkeys(KNOWN_OVERRIDE_KEYS, True),
        "auto_pr_fix": False,  # still opt-in even in auto (v2.x)
    },
}


class UnknownOverrideKeyError(ValueError):
    """An override map contained a key outside :data:`KNOWN_OVERRIDE_KEYS`."""

    def __init__(self, key: str) -> None:
        super().__init__(f"unknown autonomy override key: {key!r}")
        self.key = key


class AutonomyConfig(BaseModel):
    """A workspace's autonomy dial: a level + per-feature override flags."""

    level: AutonomyLevel
    overrides: dict[str, bool] = Field(default_factory=dict)


def validate_overrides(overrides: dict[str, bool]) -> None:
    """Raise :class:`UnknownOverrideKeyError` for any out-of-set key."""
    for key in overrides:
        if key not in KNOWN_OVERRIDE_KEYS:
            raise UnknownOverrideKeyError(key)


def level_defaults(level: AutonomyLevel) -> dict[str, bool]:
    """Return a copy of the default override flags for ``level``."""
    return dict(_LEVEL_DEFAULTS[level])


def compute_effective(config: AutonomyConfig) -> dict[str, bool]:
    """Resolve the effective flag for every known key (override wins over level)."""
    effective = level_defaults(config.level)
    for key, value in config.overrides.items():
        if key in KNOWN_OVERRIDE_KEYS:
            effective[key] = value
    return effective


def is_enabled(config: AutonomyConfig, key: str) -> bool:
    """Resolve one key: ``override.get(key, default_for_level(key))``."""
    if key in config.overrides:
        return config.overrides[key]
    return _LEVEL_DEFAULTS[config.level].get(key, False)

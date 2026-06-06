"""M3-15 / M3-16 autonomy resolver tests."""

from __future__ import annotations

import pytest
from suitest_core.autonomy import (
    KNOWN_OVERRIDE_KEYS,
    AutonomyConfig,
    UnknownOverrideKeyError,
    compute_effective,
    is_enabled,
    validate_overrides,
)
from suitest_core.capabilities import AutonomyLevel


def test_manual_disables_everything() -> None:
    eff = compute_effective(AutonomyConfig(level=AutonomyLevel.MANUAL))
    assert set(eff) == set(KNOWN_OVERRIDE_KEYS)
    assert all(v is False for v in eff.values())


def test_auto_enables_most_but_not_auto_pr_fix() -> None:
    eff = compute_effective(AutonomyConfig(level=AutonomyLevel.AUTO))
    assert eff["defect_auto_file"] is True
    assert eff["exec_agentic_no_prompt"] is True
    assert eff["auto_pr_fix"] is False  # opt-in even in auto (v2.x)


def test_assist_only_files_defects() -> None:
    eff = compute_effective(AutonomyConfig(level=AutonomyLevel.ASSIST))
    assert eff["defect_auto_file"] is True
    assert eff["exec_agentic_no_prompt"] is False
    assert eff["gen_finalize_p2p3"] is False


def test_semi_auto_matrix() -> None:
    eff = compute_effective(AutonomyConfig(level=AutonomyLevel.SEMI_AUTO))
    assert eff["gen_finalize_p2p3"] is True
    assert eff["diagnose_auto_categorize"] is True
    assert eff["defect_close_flaky"] is False  # auto-only


def test_override_wins_over_level_default() -> None:
    cfg = AutonomyConfig(level=AutonomyLevel.AUTO, overrides={"defect_close_flaky": False})
    eff = compute_effective(cfg)
    assert eff["defect_close_flaky"] is False
    # An override can also enable a key above its level default.
    cfg2 = AutonomyConfig(level=AutonomyLevel.MANUAL, overrides={"defect_auto_file": True})
    assert is_enabled(cfg2, "defect_auto_file") is True


def test_validate_overrides_rejects_unknown_key() -> None:
    with pytest.raises(UnknownOverrideKeyError):
        validate_overrides({"not_a_key": True})
    validate_overrides({"defect_auto_file": False})  # known → ok

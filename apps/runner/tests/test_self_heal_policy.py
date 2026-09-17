from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_runner.jobs.run_test_case import _auto_self_heal_enabled
from suitest_shared.domain.enums import AutonomyLevel


def _cap(level: AutonomyLevel, overrides: dict[str, bool]) -> WorkspaceCapability:
    return WorkspaceCapability(
        workspace_id="ws-1",
        autonomy_level=level,
        features_json={"autonomy_overrides": overrides},
    )


def test_full_self_heal_requires_auto_and_effective_flag() -> None:
    assert _auto_self_heal_enabled(_cap(AutonomyLevel.AUTO, {}))
    assert not _auto_self_heal_enabled(_cap(AutonomyLevel.AUTO, {"exec_self_heal_enabled": False}))
    assert not _auto_self_heal_enabled(
        _cap(AutonomyLevel.SEMI_AUTO, {"exec_self_heal_enabled": True})
    )

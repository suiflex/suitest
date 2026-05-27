"""Sanity tests for the shared enum registry + computed domain methods."""

from suitest_shared.domain.case import TestStep
from suitest_shared.domain.enums import (
    AutonomyLevel,
    CaseSource,
    IntegrationKind,
    Tier,
)


def test_tier_and_autonomy_reexported_from_core() -> None:
    """Tier/AutonomyLevel are canonical in suitest_core and re-exported here."""
    from suitest_core.capabilities import AutonomyLevel as CoreAutonomy
    from suitest_core.capabilities import Tier as CoreTier

    assert Tier is CoreTier
    assert AutonomyLevel is CoreAutonomy


def test_case_source_includes_oss_pivot_values() -> None:
    values = {s.value for s in CaseSource}
    assert {"RECORDER", "HEURISTIC_CRAWL"} <= values


def test_integration_kind_includes_all_mcp_variants() -> None:
    values = {k.value for k in IntegrationKind}
    assert {
        "MCP_API",
        "MCP_POSTGRES",
        "MCP_KUBERNETES",
        "MCP_GRAPHQL",
        "MCP_GRPC",
        "MCP_APPIUM",
        "MCP_MONGO",
        "MCP_MYSQL",
    } <= values


def test_step_executable_zero_tier_action_only_is_false() -> None:
    step = TestStep(id="s1", case_id="c1", order=1, action="click login", expected="ok")
    assert step.executable(Tier.ZERO) is False


def test_step_executable_with_code_is_true_any_tier() -> None:
    step = TestStep(
        id="s1", case_id="c1", order=1, action="", expected="ok", code="await page.click()"
    )
    assert step.executable(Tier.ZERO) is True
    assert step.executable(Tier.CLOUD) is True


def test_step_executable_cloud_tier_action_only_is_true() -> None:
    step = TestStep(id="s1", case_id="c1", order=1, action="click login", expected="ok")
    assert step.executable(Tier.CLOUD) is True
    assert step.executable(Tier.LOCAL) is True

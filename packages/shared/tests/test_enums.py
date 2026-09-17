"""Sanity tests for the shared enum registry + computed domain methods."""

from suitest_shared.domain.case import TestStep
from suitest_shared.domain.enums import (
    AutonomyLevel,
    CaseSource,
    IntegrationKind,
    LlmStatus,
)


def test_llm_status_and_autonomy_reexported_from_core() -> None:
    from suitest_core.capabilities import AutonomyLevel as CoreAutonomy
    from suitest_core.capabilities import LlmStatus as CoreLlmStatus

    assert LlmStatus is CoreLlmStatus
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


def test_step_executable_requires_llm_for_action_only() -> None:
    step = TestStep(id="s1", case_id="c1", order=1, action="click login", expected="ok")
    assert step.executable(False) is False


def test_step_executable_with_code_does_not_require_llm() -> None:
    step = TestStep(
        id="s1", case_id="c1", order=1, action="", expected="ok", code="await page.click()"
    )
    assert step.executable(False) is True
    assert step.executable(True) is True


def test_step_executable_action_only_with_llm_is_true() -> None:
    step = TestStep(id="s1", case_id="c1", order=1, action="click login", expected="ok")
    assert step.executable(True) is True

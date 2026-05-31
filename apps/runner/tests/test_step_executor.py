"""Tests for :func:`suitest_runner.executors.step_executor.execute_step`.

We mock the :class:`suitest_mcp.invoker.McpInvoker` entirely — the executor's
job is just envelope parsing, dispatch, and outcome mapping, so the test
surface is the four-way decision tree:

* no code at ZERO → SKIP with ``NO_LLM_FOR_AGENTIC_STEP``;
* well-formed code + happy invoker → PASS;
* invoker raises :class:`McpToolFailed` → FAIL;
* unparseable code → ERROR.

Each test asserts both the outcome and the diagnostic ``error_message`` so a
regression that changes the surfaced reason string fails loudly rather than
silently degrading the run record.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_mcp.errors import McpToolFailed
from suitest_mcp.models import McpToolResult
from suitest_runner.executors.step_executor import execute_step
from suitest_shared.domain.enums import StepOutcome, TargetKind, Tier

pytestmark = pytest.mark.asyncio


def _step(
    code: str | None,
    provider: str = "api-http-mcp",
    target: TargetKind = TargetKind.BE_REST,
) -> MagicMock:
    """Build a stand-in for a TestStep ORM row that satisfies the executor.

    The executor only reads ``id`` / ``code`` / ``mcp_provider`` / ``target_kind``,
    so a :class:`MagicMock` with those attributes is enough — we deliberately
    do not instantiate the ORM model to keep the test free of DB plumbing.
    """
    step = MagicMock()
    step.id = "s1"
    step.code = code
    step.mcp_provider = provider
    step.target_kind = target.value
    return step


async def test_no_code_zero_skip() -> None:
    """ZERO tier + no code = skip with the documented marker reason."""
    inv = MagicMock()
    inv.invoke = AsyncMock()
    result = await execute_step(
        invoker=inv,
        test_step=_step(None),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        tier=Tier.ZERO,
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.SKIP
    assert result.error_message is not None
    assert "NO_LLM_FOR_AGENTIC_STEP" in result.error_message
    inv.invoke.assert_not_awaited()


async def test_with_code_passes() -> None:
    """Happy path: invoker returns ok → step outcome is PASS, stdout passes through."""
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="{}", duration_ms=42)
    )
    code = json.dumps({"tool": "http.request", "arguments": {"method": "GET", "url": "x"}})
    result = await execute_step(
        invoker=inv,
        test_step=_step(code),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        tier=Tier.ZERO,
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    assert result.stdout == "{}"
    assert result.mcp_result is not None
    inv.invoke.assert_awaited_once()


async def test_failed_assertion_marks_fail() -> None:
    """Invoker raising :class:`McpToolFailed` lifts to step outcome FAIL."""
    inv = MagicMock()
    inv.invoke = AsyncMock(side_effect=McpToolFailed("status 200 != 404"))
    code = json.dumps({"tool": "http.request", "arguments": {}})
    result = await execute_step(
        invoker=inv,
        test_step=_step(code),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        tier=Tier.ZERO,
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.FAIL
    assert result.error_message is not None
    assert "MCP_TOOL_FAILED" in result.error_message


async def test_invalid_json_marks_error() -> None:
    """Garbage ``code`` short-circuits to ERROR with ``INVALID_STEP_CODE``."""
    inv = MagicMock()
    inv.invoke = AsyncMock()
    result = await execute_step(
        invoker=inv,
        test_step=_step("not json"),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        tier=Tier.ZERO,
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.ERROR
    assert result.error_message is not None
    assert "INVALID_STEP_CODE" in result.error_message
    inv.invoke.assert_not_awaited()


async def test_legacy_browser_tools_are_normalized() -> None:
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=42)
    )
    code = json.dumps({"tool": "browser.navigate", "arguments": {"url": "https://example.com"}})
    result = await execute_step(
        invoker=inv,
        test_step=_step(code, provider="playwright-mcp", target=TargetKind.FE_WEB),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        tier=Tier.ZERO,
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    assert inv.invoke.await_args.kwargs["tool"] == "browser_navigate"


async def test_legacy_browser_assert_text_uses_snapshot() -> None:
    inv = MagicMock()
    inv.invoke = AsyncMock(
        side_effect=[
            McpToolResult(ok=True, output={}, stdout="page loaded", duration_ms=42),
            McpToolResult(ok=True, output={}, stdout="Hello Suitest", duration_ms=42),
        ]
    )
    code = json.dumps(
        {
            "tool": "browser.navigate",
            "arguments": {"url": "https://example.com"},
            "assertions": [
                {"tool": "browser.assert_text", "arguments": {"contains": "Hello Suitest"}}
            ],
        }
    )
    result = await execute_step(
        invoker=inv,
        test_step=_step(code, provider="playwright-mcp", target=TargetKind.FE_WEB),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        tier=Tier.ZERO,
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    assert inv.invoke.await_args_list[1].kwargs["tool"] == "browser_snapshot"

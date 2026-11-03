from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_mcp.errors import McpToolFailed
from suitest_mcp.invoker import InvokeContext
from suitest_mcp.models import McpToolResult
from suitest_runner.executors.step_executor import _invoke_tool


@pytest.mark.asyncio
async def test_auto_heal_uncollapse_clicks_parent_toggle_and_retries_target() -> None:
    invoker = MagicMock()
    ctx = MagicMock(spec=InvokeContext)

    # Call 1: initial click throws element not visible
    # Call 2: browser_run_code_unsafe returns found=True, toggleSelector='.kt-menu__toggle'
    # Call 3: browser_click on toggle (single-click)
    # Call 4: retry target click -> success
    invoker.invoke = AsyncMock(
        side_effect=[
            McpToolFailed(
                "TimeoutError: 10000ms exceeded waiting for locator('a:has-text(\"Submenu\")')"
            ),
            McpToolResult(
                output={
                    "result": {
                        "found": True,
                        "isHidden": True,
                        "toggleSelector": ".kt-menu__toggle",
                    }
                },
                ok=True,
            ),
            McpToolResult(output={}, ok=True),
            McpToolResult(stdout="Clicked Submenu", output={"status": "clicked"}, ok=True),
        ]
    )

    res = await _invoke_tool(
        invoker=invoker,
        explicit_provider=None,
        tool="browser_click",
        arguments={"target": 'a:has-text("Submenu")'},
        ctx=ctx,
    )

    assert res.ok is True
    assert res.stdout == "Clicked Submenu"
    assert invoker.invoke.call_count == 4


@pytest.mark.asyncio
async def test_auto_heal_synthetic_dispatch_fallback() -> None:
    invoker = MagicMock()
    ctx = MagicMock(spec=InvokeContext)

    invoker.invoke = AsyncMock(
        side_effect=[
            McpToolFailed("element is not visible"),
            McpToolResult(
                output={
                    "result": {
                        "found": True,
                        "isHidden": True,
                        "toggleSelector": None,
                        "dispatched": True,
                    }
                },
                ok=True,
            ),
            Exception("still obscured"),
        ]
    )

    res = await _invoke_tool(
        invoker=invoker,
        explicit_provider=None,
        tool="browser_click",
        arguments={"target": ".obscured-btn"},
        ctx=ctx,
    )

    assert res.ok is True
    assert (res.output or {}).get("healed") == "synthetic_dispatch_click"
    assert invoker.invoke.call_count == 3


@pytest.mark.asyncio
async def test_auto_heal_re_raises_when_element_not_in_dom() -> None:
    invoker = MagicMock()
    ctx = MagicMock(spec=InvokeContext)

    invoker.invoke = AsyncMock(
        side_effect=[
            McpToolFailed("TimeoutError: 10000ms exceeded"),
            McpToolResult(
                output={"result": {"found": False, "reason": "not_in_dom"}},
                ok=True,
            ),
        ]
    )

    with pytest.raises(McpToolFailed, match="TimeoutError"):
        await _invoke_tool(
            invoker=invoker,
            explicit_provider=None,
            tool="browser_click",
            arguments={"target": "#non-existent"},
            ctx=ctx,
        )

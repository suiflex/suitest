from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_mcp.errors import McpToolFailed
from suitest_mcp.invoker import InvokeContext
from suitest_mcp.models import McpToolResult
from suitest_runner.executors.step_executor import _invoke_tool


@pytest.mark.asyncio
async def test_auto_heal_invokes_single_click_on_toggle() -> None:
    invoker = MagicMock()
    ctx = MagicMock(spec=InvokeContext)

    invoker.invoke = AsyncMock(
        side_effect=[
            McpToolFailed("element is not visible"),
            # Polling detects toggleSelector
            McpToolResult(
                output={
                    "result": {"found": True, "isHidden": True, "toggleSelector": "#acc-toggle"}
                },
                ok=True,
            ),
            # Single browser_click on toggle
            McpToolResult(stdout="Clicked toggle", ok=True),
            # Target click succeeds
            McpToolResult(stdout="Clicked Inner Item", output={"status": "ok"}, ok=True),
        ]
    )

    res = await _invoke_tool(
        invoker=invoker,
        explicit_provider=None,
        tool="browser_click",
        arguments={"target": "#inner-item"},
        ctx=ctx,
    )

    assert res.ok is True
    # Ensure browser_click was invoked on toggleSelector exactly once
    toggle_clicks = [
        c
        for c in invoker.invoke.call_args_list
        if c.kwargs.get("arguments", {}).get("target") == "#acc-toggle"
    ]
    assert len(toggle_clicks) == 1
    # Verify no raw toggle_script JS click preceded the browser_click
    js_toggle_evals = [
        c
        for c in invoker.invoke.call_args_list
        if "toggle.scrollIntoView" in c.kwargs.get("arguments", {}).get("code", "")
    ]
    assert len(js_toggle_evals) == 0


@pytest.mark.asyncio
async def test_pointer_interception_waits_for_overlay_dismissal_rather_than_instant_pass() -> None:
    invoker = MagicMock()
    ctx = MagicMock(spec=InvokeContext)

    invoker.invoke = AsyncMock(
        side_effect=[
            McpToolFailed("element <div class='spinner'> intercepts pointer events"),
            # Overlay poll detects spinner gone
            McpToolResult(output={"result": {"overlayActive": False}}, ok=True),
            # Retry target click succeeds
            McpToolResult(stdout="Clicked target after overlay gone", ok=True),
        ]
    )

    res = await _invoke_tool(
        invoker=invoker,
        explicit_provider=None,
        tool="browser_click",
        arguments={"target": "#submit-btn"},
        ctx=ctx,
    )
    assert res.ok is True
    assert "after overlay gone" in res.stdout

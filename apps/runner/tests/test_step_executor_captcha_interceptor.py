import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_db.models.case import TestStep as TestStepRow
from suitest_runner.executors.step_executor import McpToolResult, execute_step
from suitest_shared.domain.enums import StepOutcome, TargetKind


def _step(code: str, provider: str = "playwright-mcp", action: str = "act") -> TestStepRow:
    return TestStepRow(
        id="s1",
        case_id="c1",
        order=1,
        action=action,
        expected="ok",
        code=code,
        mcp_provider=provider,
        target_kind=TargetKind.FE_WEB,
    )


@pytest.mark.asyncio
async def test_execute_step_intercepts_browser_type_on_captcha_field():
    test_image_bytes = b"real-captcha-png"
    b64_snap = base64.b64encode(test_image_bytes).decode("ascii")

    inv = MagicMock()

    async def _invoke(
        *, tool: str, arguments: dict[str, object], **kwargs: object
    ) -> McpToolResult:
        if tool == "browser_run_code_unsafe":
            code_str = str(arguments.get("code", ""))
            if "isCaptchaField" in code_str and "findNearestCaptchaImage" in code_str:
                return McpToolResult(
                    ok=True,
                    output={
                        "result": {
                            "is_captcha": True,
                            "image_selector": "#img-captcha",
                            "refresh_target": "#img-captcha",
                        }
                    },
                    stdout="",
                    duration_ms=10,
                )
            if "target.screenshot" in code_str:
                return McpToolResult(
                    ok=True, output={"result": b64_snap}, stdout="", duration_ms=20
                )
        return McpToolResult(ok=True, output={}, stdout="ok", duration_ms=5)

    inv.invoke = AsyncMock(side_effect=_invoke)
    mock_solver = AsyncMock(return_value="SOLVED99")

    # Legacy recorded step that hardcoded stale text into captcha input
    step = _step(
        json.dumps(
            {
                "tool": "browser_type",
                "arguments": {"target": "#input-captcha", "text": "OLD_STALE_CODE"},
            }
        ),
        action="Fill CAPTCHA with OLD_STALE_CODE",
    )

    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r1",
        workspace_id="w1",
        actor_user_id="u1",
        routing_overrides=None,
        captcha_solver=mock_solver,
    )

    assert result.outcome == StepOutcome.PASS
    mock_solver.assert_awaited_once()
    assert result.mcp_result is not None
    assert result.mcp_result.output.get("auto_healed_captcha") is True
    assert result.mcp_result.output.get("solved_text") == "SOLVED99"

    # Verify browser_type typed the solved text, not OLD_STALE_CODE
    type_calls = [c for c in inv.invoke.call_args_list if c.kwargs.get("tool") == "browser_type"]
    assert len(type_calls) == 1
    assert type_calls[0].kwargs["arguments"]["text"] == "SOLVED99"


@pytest.mark.asyncio
async def test_execute_step_pre_submit_intercept_solves_unfilled_captcha():
    test_image_bytes = b"pre-submit-captcha-png"
    b64_snap = base64.b64encode(test_image_bytes).decode("ascii")

    inv = MagicMock()

    async def _invoke(
        *, tool: str, arguments: dict[str, object], **kwargs: object
    ) -> McpToolResult:
        if tool == "browser_run_code_unsafe":
            code_str = str(arguments.get("code", ""))
            if "isCaptchaField" in code_str and "findNearestCaptchaImage" in code_str:
                return McpToolResult(
                    ok=True,
                    output={
                        "result": {
                            "is_captcha": True,
                            "is_empty": True,
                            "image_selector": "#img-captcha",
                            "input_selector": "#captcha",
                            "refresh_target": "#img-captcha",
                        }
                    },
                    stdout="",
                    duration_ms=10,
                )
            if "target.screenshot" in code_str:
                return McpToolResult(
                    ok=True, output={"result": b64_snap}, stdout="", duration_ms=20
                )
        return McpToolResult(ok=True, output={}, stdout="ok", duration_ms=5)

    inv.invoke = AsyncMock(side_effect=_invoke)
    mock_solver = AsyncMock(return_value="PRE_SUBMIT_123")

    # Step is clicking the Login / Submit button
    step = _step(
        json.dumps({"tool": "browser_click", "arguments": {"target": "#btn-login"}}),
        action="Click Login button",
    )

    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r1",
        workspace_id="w1",
        actor_user_id="u1",
        routing_overrides=None,
        captcha_solver=mock_solver,
    )

    assert result.outcome == StepOutcome.PASS
    mock_solver.assert_awaited_once()
    assert result.mcp_result is not None
    assert "pre_submit_injected_captcha" in result.mcp_result.output
    injected_info = result.mcp_result.output["pre_submit_injected_captcha"]
    assert injected_info["solved_text"] == "PRE_SUBMIT_123"
    assert injected_info["input_selector"] == "#captcha"

    # Both browser_type (for captcha) and browser_click (for submit button) were executed
    tools_called = [c.kwargs.get("tool") for c in inv.invoke.call_args_list]
    assert "browser_type" in tools_called
    assert "browser_click" in tools_called

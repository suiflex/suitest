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
async def test_execute_step_skips_captcha_detect_on_normal_field():
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=5)
    )
    mock_solver = AsyncMock(return_value="SOLVED")

    # Regular typing into email field
    step = _step(
        json.dumps(
            {
                "tool": "browser_type",
                "arguments": {"target": "#input-email", "text": "user@example.com"},
            }
        ),
        action="Type user email",
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
    mock_solver.assert_not_called()
    # Ensure browser_run_code_unsafe was never invoked
    run_code_calls = [
        c for c in inv.invoke.call_args_list if c.kwargs.get("tool") == "browser_run_code_unsafe"
    ]
    assert len(run_code_calls) == 0


@pytest.mark.asyncio
async def test_execute_step_pre_submit_intercept_solves_unfilled_captcha_on_hint():
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

    # Step has a captcha hint in target selector
    step = _step(
        json.dumps({"tool": "browser_click", "arguments": {"target": "#btn-login-captcha"}}),
        action="Click Login button with captcha",
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


@pytest.mark.asyncio
async def test_execute_step_post_failure_submit_intercept_solves_and_retries():
    test_image_bytes = b"post-fail-captcha-png"
    b64_snap = base64.b64encode(test_image_bytes).decode("ascii")

    inv = MagicMock()
    click_attempt = 0

    async def _invoke(
        *, tool: str, arguments: dict[str, object], **kwargs: object
    ) -> McpToolResult:
        nonlocal click_attempt
        if tool == "browser_click":
            click_attempt += 1
            if click_attempt == 1:
                # First submit click fails because captcha was not solved
                return McpToolResult(
                    ok=False, output={"error": "CAPTCHA required"}, stdout="blocked", duration_ms=5
                )
            # Retry click succeeds
            return McpToolResult(
                ok=True, output={"status": "submitted"}, stdout="ok", duration_ms=5
            )
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
    mock_solver = AsyncMock(return_value="RETRY_SOLVED")

    # Regular submit button with no captcha hint initially
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
    assert injected_info["solved_text"] == "RETRY_SOLVED"
    assert injected_info["input_selector"] == "#captcha"
    assert click_attempt == 2

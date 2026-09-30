"""Tests for :func:`suitest_runner.executors.step_executor.execute_step`.

We mock the :class:`suitest_mcp.invoker.McpInvoker` entirely — the executor's
job is just envelope parsing, dispatch, and outcome mapping, so the test
surface is the four-way decision tree:

* no code and no translator (LLM not ready) → ERROR with ``LLM_NOT_READY``;
* well-formed code + happy invoker → PASS;
* invoker raises :class:`McpToolFailed` → FAIL;
* unparseable code → ERROR.

Each test asserts both the outcome and the diagnostic ``error_message`` so a
regression that changes the surfaced reason string fails loudly rather than
silently degrading the run record.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_mcp.errors import McpToolFailed
from suitest_mcp.models import McpToolResult
from suitest_runner.executors.step_executor import execute_step
from suitest_shared.domain.enums import StepOutcome, TargetKind

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


async def test_no_code_without_translator_fails_llm_not_ready() -> None:
    inv = MagicMock()
    inv.invoke = AsyncMock()
    result = await execute_step(
        invoker=inv,
        test_step=_step(None),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.ERROR
    assert result.error_message is not None
    assert result.error_message.startswith("LLM_NOT_READY")
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
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    assert inv.invoke.await_args_list[1].kwargs["tool"] == "browser_snapshot"


# ---------------------------------------------------------------------------
# M3-10 — agentic action→code translation at execution time
# ---------------------------------------------------------------------------


def _agentic_step(provider: str = "playwright-mcp") -> MagicMock:
    step = _step(None, provider=provider, target=TargetKind.FE_WEB)
    step.action = "click the Buy button"
    return step


async def test_agentic_step_without_translator_fails_llm_not_ready() -> None:
    """Readiness vanished after queueing → ERROR LLM_NOT_READY, no MCP call."""
    inv = MagicMock()
    inv.invoke = AsyncMock()
    result = await execute_step(
        invoker=inv,
        test_step=_agentic_step(),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
        translator=None,
    )
    assert result.outcome == StepOutcome.ERROR
    assert result.error_message is not None
    assert result.error_message.startswith("LLM_NOT_READY")
    inv.invoke.assert_not_awaited()


async def test_translator_translates_then_invokes() -> None:
    """Translator returns a tool envelope → executor invokes it → PASS."""
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="clicked", duration_ms=10)
    )

    async def translator(action: str) -> dict[str, object]:
        assert action == "click the Buy button"
        return {"tool": "browser_click", "arguments": {"selector": "#buy"}}

    result = await execute_step(
        invoker=inv,
        test_step=_agentic_step(),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
        translator=translator,
    )
    assert result.outcome == StepOutcome.PASS
    assert inv.invoke.await_args.kwargs["tool"] == "browser_click"
    assert inv.invoke.await_args.kwargs["arguments"] == {"selector": "#buy"}


async def test_translator_returns_none_skips() -> None:
    """Untranslatable action → SKIP with AGENTIC_TRANSLATE_FAILED, no invoke."""
    inv = MagicMock()
    inv.invoke = AsyncMock()

    async def translator(_action: str) -> None:
        return None

    result = await execute_step(
        invoker=inv,
        test_step=_agentic_step(),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
        translator=translator,
    )
    assert result.outcome == StepOutcome.SKIP
    assert result.error_message is not None
    assert "AGENTIC_TRANSLATE_FAILED" in result.error_message
    inv.invoke.assert_not_awaited()


async def test_translator_raises_errors() -> None:
    """Translator exception is contained → ERROR, run keeps going."""
    inv = MagicMock()
    inv.invoke = AsyncMock()

    async def translator(_action: str) -> dict[str, object]:
        raise RuntimeError("provider down")

    result = await execute_step(
        invoker=inv,
        test_step=_agentic_step(),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
        translator=translator,
    )
    assert result.outcome == StepOutcome.ERROR
    assert result.error_message is not None
    assert "AGENTIC_TRANSLATE_ERROR" in result.error_message


async def test_classify_mcp_error_browser_lock() -> None:
    """Browser lock error lifts to StepOutcome.ERROR and flags is_fatal_infra."""
    from suitest_runner.executors.step_executor import classify_mcp_error

    raw = (
        "### Error\n"
        "Error: Browser is already in use for /Users/test/Library/Caches/ms-playwright-mcp/chrome, "
        "use --isolated to run multiple instances of the same browser"
    )
    outcome, clean_msg, is_fatal = classify_mcp_error(raw)
    assert outcome == StepOutcome.ERROR
    assert is_fatal is True
    assert "MCP_TOOL_ERROR: Browser is already in use" in clean_msg
    assert "###" not in clean_msg


async def test_classify_mcp_error_assertion_failure() -> None:
    """Normal element failure stays StepOutcome.FAIL and is_fatal_infra is False."""
    from suitest_runner.executors.step_executor import classify_mcp_error

    raw = 'Error: "#submit-btn" does not match any elements.'
    outcome, clean_msg, is_fatal = classify_mcp_error(raw)
    assert outcome == StepOutcome.FAIL
    assert is_fatal is False
    assert clean_msg == 'MCP_TOOL_FAILED: "#submit-btn" does not match any elements.'


async def test_browser_lock_step_execution_marks_error_and_fatal_infra() -> None:
    """execute_step with browser lock error returns StepOutcome.ERROR with is_fatal_infra=True."""
    inv = MagicMock()
    lock_err = (
        "### Error\n"
        "Error: Browser is already in use for /Users/rohmnsa/Library/Caches/ms-playwright-mcp/mcp-chrome, "
        "use --isolated to run multiple instances of the same browser"
    )
    inv.invoke = AsyncMock(side_effect=McpToolFailed(lock_err))
    code = json.dumps({"tool": "browser_navigate", "arguments": {"url": "https://example.com"}})
    result = await execute_step(
        invoker=inv,
        test_step=_step(code, provider="playwright-mcp", target=TargetKind.FE_WEB),
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.ERROR
    assert result.is_fatal_infra is True
    assert result.error_message is not None
    assert "MCP_TOOL_ERROR: Browser is already in use" in result.error_message


@pytest.mark.asyncio
async def test_execute_step_blank_action_skips_without_translator() -> None:
    inv = MagicMock()
    translator = AsyncMock()
    step = SimpleNamespace(
        id="step-blank",
        case_id="tc-blank",
        step_order=1,
        action="   ",
        code=None,
        step_type="agentic",
        expected=None,
        notes=None,
        tags=[],
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,  # type: ignore[arg-type]
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        translator=translator,
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.SKIP
    assert result.error_message == "EMPTY_STEP: step action is blank"
    translator.assert_not_called()
    inv.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_execute_step_resolves_password_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUITEST_PASSWORD", "super-secret-pw")
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=10)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_type",
                "arguments": {"target": "input#pass", "text": "{{password}}"},
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    step.data = {"masked": True}
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["arguments"]["text"] == "super-secret-pw"


@pytest.mark.asyncio
async def test_execute_step_unresolved_password_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUITEST_PASSWORD", raising=False)
    monkeypatch.delenv("TEST_PASSWORD", raising=False)
    monkeypatch.delenv("SUITEST_TEST_PASSWORD", raising=False)
    monkeypatch.delenv("SECRET_PASSWORD", raising=False)
    monkeypatch.delenv("PASSWORD", raising=False)
    inv = MagicMock()
    inv.invoke = AsyncMock()
    step = _step(
        json.dumps(
            {
                "tool": "browser_type",
                "arguments": {"target": "input#pass", "text": "{{password}}"},
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.FAIL
    assert "SUITEST_PASSWORD" in (result.error_message or "")
    inv.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_execute_step_decodes_base64_env_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "secret_sauce" in base64 is "c2VjcmV0X3NhdWNl"
    monkeypatch.setenv("SUITEST_PASSWORD", "base64:c2VjcmV0X3NhdWNl")
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=10)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_type",
                "arguments": {"target": "input#pass", "text": "{{password}}"},
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["arguments"]["text"] == "secret_sauce"


@pytest.mark.asyncio
async def test_execute_step_decodes_step_data_encoded_value_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUITEST_PASSWORD", raising=False)
    monkeypatch.delenv("TEST_PASSWORD", raising=False)
    monkeypatch.delenv("SUITEST_TEST_PASSWORD", raising=False)
    monkeypatch.delenv("SECRET_PASSWORD", raising=False)
    monkeypatch.delenv("PASSWORD", raising=False)
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=10)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_type",
                "arguments": {"target": "input#pass", "text": "{{password}}"},
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    # Stored encoded_value in step metadata: base64("my-vault-secret") -> "bXktdmF1bHQtc2VjcmV0"
    step.data = {"masked": True, "encoded_value": "bXktdmF1bHQtc2VjcmV0"}
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["arguments"]["text"] == "my-vault-secret"


@pytest.mark.asyncio
async def test_execute_step_upload_file_translates_to_run_code_unsafe(
    tmp_path: pytest.TempPathFactory,
) -> None:
    test_file = tmp_path / "test.png"  # type: ignore[operator]
    test_file.write_text("dummy")
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=15)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_upload_file",
                "arguments": {"target": "input[type=file]", "file": str(test_file)},
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["tool"] == "browser_run_code_unsafe"
    assert "setInputFiles" in call_kwargs["arguments"]["code"]
    assert str(test_file) in call_kwargs["arguments"]["code"]


@pytest.mark.asyncio
async def test_execute_step_legacy_browser_type_upload_compat(
    tmp_path: pytest.TempPathFactory,
) -> None:
    test_file = tmp_path / "test.png"  # type: ignore[operator]
    test_file.write_text("dummy")
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=15)
    )
    # Legacy recorded step: tool is browser_type, has file & files, text is absent
    step = _step(
        json.dumps(
            {
                "tool": "browser_type",
                "arguments": {
                    "target": '[data-testid="file-input"]',
                    "file": str(test_file),
                    "files": [str(test_file)],
                },
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["tool"] == "browser_run_code_unsafe"
    assert "setInputFiles" in call_kwargs["arguments"]["code"]


@pytest.mark.asyncio
async def test_execute_step_skips_fakepath_typing() -> None:
    inv = MagicMock()
    inv.invoke = AsyncMock()
    step = _step(
        json.dumps(
            {
                "tool": "browser_type",
                "arguments": {
                    "target": '[data-testid="file-input"]',
                    "text": "C:\\fakepath\\sample.png",
                },
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    # Invoker should not even have been called because fakepath typing was skipped cleanly
    inv.invoke.assert_not_awaited()
    assert "fakepath" in (result.stdout or "").lower()


@pytest.mark.asyncio
async def test_execute_step_multi_file_upload(
    tmp_path: pytest.TempPathFactory,
) -> None:
    f1 = tmp_path / "doc1.pdf"  # type: ignore[operator]
    f2 = tmp_path / "doc2.pdf"  # type: ignore[operator]
    f1.write_text("file 1")
    f2.write_text("file 2")
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=20)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_upload_file",
                "arguments": {
                    "target": "input[type=file]",
                    "files": [str(f1), str(f2)],
                },
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["tool"] == "browser_run_code_unsafe"
    code = call_kwargs["arguments"]["code"]
    assert str(f1) in code
    assert str(f2) in code


async def test_execute_step_with_frame_selector_click() -> None:
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=20)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_click",
                "arguments": {
                    "target": "button#submit",
                    "frame_selector": "iframe#login-frame",
                },
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["tool"] == "browser_run_code_unsafe"
    code = call_kwargs["arguments"]["code"]
    assert 'frameLocator("iframe#login-frame")' in code
    assert 'locator("button#submit").click()' in code


async def test_execute_step_with_browser_select_option_sanitizes_args() -> None:
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=20)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_select_option",
                "arguments": {
                    "target": "select#country",
                    "selector": "select#country",
                    "values": ["ID"],
                    "value": "ID",
                },
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["tool"] == "browser_select_option"
    assert call_kwargs["arguments"] == {"target": "select#country", "values": ["ID"]}


async def test_execute_step_with_frame_selector_assert() -> None:
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=25)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_evaluate",
                "arguments": {
                    "selector": "#success-msg",
                    "text": "Payment complete",
                    "frame_selector": "iframe#checkout-frame",
                },
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["tool"] == "browser_run_code_unsafe"
    code = call_kwargs["arguments"]["code"]
    assert 'frameLocator("iframe#checkout-frame")' in code
    assert 'locator("#success-msg")' in code
    assert "Payment complete" in code


async def test_execute_step_with_nested_chained_frame_selector() -> None:
    inv = MagicMock()
    inv.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, output={}, stdout="ok", duration_ms=25)
    )
    step = _step(
        json.dumps(
            {
                "tool": "browser_evaluate",
                "arguments": {
                    "selector": "button#nested-submit",
                    "text": "Submit Nested",
                    "frame_selector": "iframe#outer-frame >>> iframe#inner-frame",
                },
            }
        ),
        provider="playwright-mcp",
        target=TargetKind.FE_WEB,
    )
    result = await execute_step(
        invoker=inv,
        test_step=step,
        run_id="r",
        workspace_id="w",
        actor_user_id="u",
        routing_overrides=None,
    )
    assert result.outcome == StepOutcome.PASS
    inv.invoke.assert_awaited_once()
    call_kwargs = inv.invoke.call_args.kwargs
    assert call_kwargs["tool"] == "browser_run_code_unsafe"
    code = call_kwargs["arguments"]["code"]
    assert 'page.frameLocator("iframe#outer-frame").frameLocator("iframe#inner-frame")' in code
    assert 'locator("button#nested-submit")' in code
    assert "Submit Nested" in code

"""Single-step executor — parses ``TestStep.code`` and dispatches via MCP.

The runner's orchestrator hands one :class:`TestStep` row to :func:`execute_step`
at a time. The executor is intentionally narrow: it owns the JSON envelope
parsing, the per-step timing, the outcome decision tree, and the bridging from
:class:`McpInvoker` errors to :class:`StepOutcome` values. Everything richer
(per-step DB row persistence, artifact upload, event publish) belongs to the
orchestrator so the executor stays trivially unit-testable with a mocked
invoker.

Step ``code`` envelope (DATA_MODEL.md §3.4):

.. code-block:: json

    {
      "tool": "browser.navigate",
      "arguments": {"url": "{{base_url}}/login"},
      "assertions": [
        {"tool": "browser.assert_text",
         "arguments": {"selector": "h1", "contains": "Welcome"}}
      ]
    }

Empty ``code`` is valid for manual TCM. During a run the validated workspace LLM
translates the prose ``action`` into a tool call; if readiness disappeared after
queueing, execution fails closed.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_mcp.invoker import InvokeContext
from suitest_mcp.models import McpToolResult
from suitest_shared.domain.enums import StepOutcome, TargetKind

if TYPE_CHECKING:
    from suitest_db.models.case import TestStep as TestStepRow
    from suitest_mcp.invoker import McpInvoker

# Translates a prose ``action`` into a ``{"tool", "arguments"}`` envelope, or
# ``None`` when it cannot be expressed as one tool call (M3-10). The runner binds
# the workspace's LLM provider/model into this closure before per-step dispatch.
StepTranslator = Callable[[str], Awaitable[dict[str, object] | None]]


log = structlog.get_logger(__name__)


_LEGACY_TOOL_ALIASES: dict[str, str] = {
    "browser.navigate": "browser_navigate",
    "browser.click": "browser_click",
    "browser.type": "browser_type",
    "browser.screenshot": "browser_take_screenshot",
    "browser.evaluate": "browser_evaluate",
    "browser.wait_for": "browser_wait_for",
    "browser.assert_text": "browser.assert_text",
    "browser.upload_file": "browser_upload_file",
}


@dataclass
class StepResult:
    """Normalized outcome of one :func:`execute_step` dispatch.

    The orchestrator turns this into a ``run_steps`` row + a
    ``run.step.completed`` event. ``mcp_result`` is preserved only on the PASS
    path so the orchestrator can fan out artifacts; on FAIL / ERROR it is
    ``None`` because the underlying MCP call raised before returning a
    :class:`McpToolResult`.
    """

    outcome: StepOutcome
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    stdout: str
    stderr: str
    error_message: str | None
    mcp_result: McpToolResult | None
    is_fatal_infra: bool = False


_INFRA_ERROR_PATTERNS: tuple[str, ...] = (
    "browser is already in use",
    "target page, context or browser has been closed",
    "target closed",
    "browser has been closed",
    "browser closed",
    "page has been closed",
    "connection refused",
    "econnrefused",
    "spawn enoent",
    "auto-disabled (down past threshold)",
    "failed to connect to mcp",
    "transport died",
    "connection reset by peer",
)


def classify_mcp_error(raw_msg: str) -> tuple[StepOutcome, str, bool]:
    """Classify an MCP tool error string into StepOutcome, clean message, and fatal flag.

    Distinguishes application test failures (e.g. selector missing, assertion mismatch)
    from infrastructure/environment crashes (e.g. browser locked, target closed, provider down).
    """
    clean_msg = raw_msg.strip()
    clean_msg = re.sub(r"^(?:MCP_TOOL_FAILED:\s*)?(?:###\s*Error\s*\n*)?", "", clean_msg).strip()
    clean_msg = re.sub(r"^Error:\s*", "", clean_msg).strip()

    lowered = clean_msg.lower()
    is_infra = any(pat in lowered for pat in _INFRA_ERROR_PATTERNS)
    if is_infra:
        return StepOutcome.ERROR, f"MCP_TOOL_ERROR: {clean_msg}", True
    return StepOutcome.FAIL, f"MCP_TOOL_FAILED: {clean_msg}", False


def _normalize_tool_name(tool: str) -> str:
    return _LEGACY_TOOL_ALIASES.get(tool, tool)


def _resolve_fixture_path(file_path: str) -> Path:
    p = Path(file_path)
    if p.is_absolute() and p.exists():
        return p
    # Try resolving relative to current working directory
    cand = p.resolve()
    if cand.exists():
        return cand
    # Try searching up from current working directory
    for parent in [Path.cwd(), *Path.cwd().parents]:
        cand = parent / file_path
        if cand.exists():
            return cand.resolve()
    # Try searching relative to this file's repo root
    try:
        repo_root = Path(__file__).resolve().parents[4]
        cand = repo_root / file_path
        if cand.exists():
            return cand.resolve()
    except (IndexError, ValueError, OSError) as exc:
        log.debug("step_executor.resolve_fixture_path_failed", error=str(exc))
    return p.resolve()


async def _handle_upload_operation(
    *,
    invoker: McpInvoker,
    explicit_provider: str | None,
    normalized_tool: str,
    arguments: dict[str, object],
    ctx: InvokeContext,
) -> McpToolResult:
    target = str(
        arguments.get("target") or arguments.get("selector") or arguments.get("element") or ""
    )
    raw_files = arguments.get("files")
    if isinstance(raw_files, list) and raw_files:
        file_candidates = [str(f) for f in raw_files]
    elif arguments.get("file"):
        file_candidates = [str(arguments["file"])]
    else:
        raise McpToolFailed(f"{normalized_tool}: missing 'file' or 'files' in arguments")

    resolved_files: list[str] = []
    for raw_path in file_candidates:
        p = _resolve_fixture_path(raw_path)
        if not p.exists():
            raise McpToolFailed(f"Upload file not found: {raw_path} (resolved to {p})")
        resolved_files.append(str(p))

    payload_arg = resolved_files[0] if len(resolved_files) == 1 else resolved_files
    code = f"""async (page) => {{
    const locator = page.locator({json.dumps(target)});
    await locator.setInputFiles({json.dumps(payload_arg)});
}}"""
    return await invoker.invoke(
        explicit_provider=explicit_provider,
        tool="browser_run_code_unsafe",
        arguments={"code": code},
        ctx=ctx,
    )


def _build_frame_chain_js(frame_selector: str) -> str:
    """Build chained page.frameLocator(...) calls for nested iframes delimited by ' >>> '."""
    parts = [s.strip() for s in frame_selector.split(">>>") if s.strip()]
    if not parts:
        parts = [frame_selector.strip() or "iframe"]
    chain = "page"
    for part in parts:
        chain += f".frameLocator({json.dumps(part)})"
    return chain


async def _handle_frame_operation(
    *,
    invoker: McpInvoker,
    explicit_provider: str | None,
    normalized_tool: str,
    frame_selector: str,
    arguments: dict[str, object],
    ctx: InvokeContext,
) -> McpToolResult:
    target = str(
        arguments.get("target") or arguments.get("selector") or arguments.get("element") or ""
    )
    frame_chain = _build_frame_chain_js(frame_selector)
    if normalized_tool == "browser_click":
        code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).click();
}}"""
    elif normalized_tool == "browser_type":
        text = str(arguments.get("text", ""))
        code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).fill({json.dumps(text)});
}}"""
    elif normalized_tool == "browser_select_option":
        raw_vals = arguments.get("values")
        if isinstance(raw_vals, list):
            vals = [str(v) for v in raw_vals]
        elif arguments.get("value"):
            vals = [str(arguments["value"])]
        else:
            vals = []
        code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).selectOption({json.dumps(vals)});
}}"""
    elif normalized_tool in ("browser_evaluate", "browser_assert"):
        expected_text = str(arguments.get("text") or "")
        if target and expected_text:
            code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).waitFor({{ state: "visible", timeout: 8000 }});
    const txt = await frame.locator({json.dumps(target)}).textContent();
    if (!txt || !txt.includes({json.dumps(expected_text)})) {{
        throw new Error(`Expected frame text "${{expected_text}}" but got "${{txt}}"`);
    }}
}}"""
        elif target:
            code = f"""async (page) => {{
    const frame = {frame_chain};
    await frame.locator({json.dumps(target)}).waitFor({{ state: "visible", timeout: 8000 }});
}}"""
        else:
            func_code = arguments.get("function") or "() => true"
            code = f"""async (page) => {{
    const frame = {frame_chain};
    return await frame.locator(":root").evaluate({func_code});
}}"""
    else:
        return await invoker.invoke(
            explicit_provider=explicit_provider,
            tool=normalized_tool,
            arguments=arguments,
            ctx=ctx,
        )

    return await invoker.invoke(
        explicit_provider=explicit_provider,
        tool="browser_run_code_unsafe",
        arguments={"code": code},
        ctx=ctx,
    )


async def _invoke_tool(
    *,
    invoker: McpInvoker,
    explicit_provider: str | None,
    tool: str,
    arguments: dict[str, object],
    ctx: InvokeContext,
) -> McpToolResult:
    normalized_tool = _normalize_tool_name(tool)
    if normalized_tool == "browser.assert_text":
        snapshot = await invoker.invoke(
            explicit_provider=explicit_provider,
            tool="browser_snapshot",
            arguments={},
            ctx=ctx,
        )
        contains = str(arguments.get("contains", ""))
        if contains and contains not in snapshot.stdout:
            raise McpToolFailed(f"browser.assert_text: expected {contains!r} in snapshot output")
        return snapshot

    is_upload = normalized_tool in ("browser_upload_file", "browser.upload_file") or (
        normalized_tool == "browser_type"
        and ("file" in arguments or "files" in arguments)
        and "text" not in arguments
    )
    if is_upload:
        return await _handle_upload_operation(
            invoker=invoker,
            explicit_provider=explicit_provider,
            normalized_tool=normalized_tool,
            arguments=arguments,
            ctx=ctx,
        )

    frame_selector = str(arguments.get("frame_selector") or arguments.get("frameSelector") or "")
    if frame_selector:
        return await _handle_frame_operation(
            invoker=invoker,
            explicit_provider=explicit_provider,
            normalized_tool=normalized_tool,
            frame_selector=frame_selector,
            arguments=arguments,
            ctx=ctx,
        )

    if normalized_tool == "browser_select_option":
        target = str(arguments.get("target") or arguments.get("selector") or "")
        raw_vals = arguments.get("values")
        if isinstance(raw_vals, list):
            vals = [str(v) for v in raw_vals]
        elif arguments.get("value"):
            vals = [str(arguments["value"])]
        else:
            vals = []
        clean_args: dict[str, Any] = {
            "target": target,
            "values": vals,
        }
        if "element" in arguments:
            clean_args["element"] = str(arguments["element"])
        return await invoker.invoke(
            explicit_provider=explicit_provider,
            tool=normalized_tool,
            arguments=clean_args,
            ctx=ctx,
        )

    if normalized_tool == "browser_type":
        type_text = str(arguments.get("text", ""))
        if type_text.startswith(("C:\\fakepath\\", "fakepath/")):
            log.info("step_executor.skip_fakepath_type", text=type_text)
            return McpToolResult(
                ok=True,
                output={},
                stdout="Skipped redundant fakepath typing into file input",
                duration_ms=1,
            )

    return await invoker.invoke(
        explicit_provider=explicit_provider,
        tool=normalized_tool,
        arguments=arguments,
        ctx=ctx,
    )


async def _parse_or_translate_step(
    test_step: TestStepRow,
    translator: StepTranslator | None,
) -> tuple[dict[str, object] | None, StepOutcome | None, str | None]:
    """Parse deterministic step JSON or translate an agentic prose action."""
    if not test_step.code:
        action = (test_step.action or "").strip()
        if not action:
            return None, StepOutcome.SKIP, "EMPTY_STEP: step action is blank"
        if translator is None:
            # Readiness vanished after queueing: an agentic step cannot run without
            # the workspace LLM, so it fails closed rather than silently skipping.
            return (
                None,
                StepOutcome.ERROR,
                "LLM_NOT_READY: agentic step needs a validated workspace LLM",
            )
        try:
            translated = await translator(action)
        except Exception as exc:
            log.exception("step.executor.translate_error", step_id=test_step.id)
            return None, StepOutcome.ERROR, f"AGENTIC_TRANSLATE_ERROR: {exc}"
        if translated is None:
            return (
                None,
                StepOutcome.SKIP,
                "AGENTIC_TRANSLATE_FAILED: action not expressible as one tool call",
            )
        parsed: object = translated
    else:
        try:
            parsed = json.loads(test_step.code)
        except json.JSONDecodeError as exc:
            return None, StepOutcome.ERROR, f"INVALID_STEP_CODE: {exc}"

    if not isinstance(parsed, dict) or "tool" not in parsed:
        return None, StepOutcome.ERROR, "INVALID_STEP_CODE: envelope missing 'tool' key"
    return parsed, None, None


async def _run_assertions(
    *,
    invoker: McpInvoker,
    explicit_provider: str,
    assertions: list[dict[str, object]],
    result: McpToolResult,
    ctx: InvokeContext,
) -> None:
    """Invoke assertion tools sequentially against the primary tool result."""
    for assertion in assertions:
        a_args_raw = assertion.get("arguments", {})
        a_args: dict[str, object] = dict(a_args_raw) if isinstance(a_args_raw, dict) else {}
        if result.stdout.startswith("{"):
            try:
                a_args["result"] = json.loads(result.stdout)
            except json.JSONDecodeError:
                a_args["result"] = {}
        else:
            a_args["result"] = {}
        await _invoke_tool(
            invoker=invoker,
            explicit_provider=explicit_provider,
            tool=str(assertion["tool"]),
            arguments=a_args,
            ctx=ctx,
        )


def _decode_and_resolve_secret(step_data: dict[str, Any]) -> str | None:
    """Resolve and decode secret passwords from environment, step metadata, or encoded fallback."""
    candidate = (
        os.environ.get("SUITEST_PASSWORD")
        or os.environ.get("TEST_PASSWORD")
        or os.environ.get("SUITEST_TEST_PASSWORD")
        or os.environ.get("SECRET_PASSWORD")
        or os.environ.get("PASSWORD")
        or step_data.get("default_value")
        or step_data.get("raw_value")
    )
    if candidate is not None:
        candidate_str = str(candidate).strip()
        # Decode base64 prefixes e.g. base64:c2VjcmV0 or b64:c2VjcmV0
        if candidate_str.startswith("base64:") or candidate_str.startswith("b64:"):
            prefix_len = 7 if candidate_str.startswith("base64:") else 4
            try:
                return base64.b64decode(candidate_str[prefix_len:]).decode("utf-8")
            except Exception as exc:
                log.debug("step_executor.base64_decode_failed", error=str(exc))
                return candidate_str[prefix_len:]
        return candidate_str

    # Fallback to encoded_value in step_data if present
    encoded_val = step_data.get("encoded_value")
    if encoded_val and isinstance(encoded_val, str):
        try:
            return base64.b64decode(encoded_val).decode("utf-8")
        except Exception as exc:
            log.warning("step_executor.decode_fallback_failed", error=str(exc))
            return None

    return None


async def execute_step(
    *,
    invoker: McpInvoker,
    test_step: TestStepRow,
    run_id: str,
    workspace_id: str,
    actor_user_id: str | None,
    routing_overrides: dict[str, object] | None,
    translator: StepTranslator | None = None,
) -> StepResult:
    """Dispatch one :class:`TestStep` via the MCP invoker and return its outcome.

    Decision tree:

    * ``code`` empty + no translator (workspace LLM not ready) → ``ERROR`` with
      ``LLM_NOT_READY``.
    * ``code`` empty + translator → translate ``action`` → tool call
      (M3-10); untranslatable → ``SKIP`` ``AGENTIC_TRANSLATE_FAILED``.
    * ``code`` not valid JSON → ``ERROR`` with ``INVALID_STEP_CODE``.
    * Tool call raises :class:`McpToolTimeout` → ``ERROR`` ``MCP_TOOL_TIMEOUT``.
    * Tool call raises :class:`McpToolFailed` → ``FAIL`` ``MCP_TOOL_FAILED``.
    * Other exception → ``ERROR`` ``INTERNAL: ...``.
    * Success path → ``PASS``; ``mcp_result`` carries artifacts for the
      orchestrator to upload.

    Assertions: each entry in ``assertions`` is invoked sequentially after the
    main tool; failed assertions raise :class:`McpToolFailed` from inside the
    MCP server, which we surface as ``FAIL`` on the parent step.
    """
    started = datetime.now(UTC)
    t0 = time.perf_counter()

    def _done(
        outcome: StepOutcome,
        *,
        msg: str | None = None,
        mcp: McpToolResult | None = None,
        stdout: str = "",
        stderr: str = "",
        is_fatal_infra: bool = False,
    ) -> StepResult:
        return StepResult(
            outcome=outcome,
            started_at=started,
            completed_at=datetime.now(UTC),
            duration_ms=int((time.perf_counter() - t0) * 1000),
            stdout=stdout,
            stderr=stderr,
            error_message=msg,
            mcp_result=mcp,
            is_fatal_infra=is_fatal_infra,
        )

    parsed, error_outcome, error_msg = await _parse_or_translate_step(test_step, translator)
    if error_outcome is not None:
        return _done(error_outcome, msg=error_msg)
    assert parsed is not None

    tool = str(parsed["tool"])
    raw_args = parsed.get("arguments", {})
    arguments: dict[str, object] = dict(raw_args) if isinstance(raw_args, dict) else {}

    # Resolve placeholder variables like {{password}}
    raw_text = arguments.get("text")
    if isinstance(raw_text, str) and (
        "{{password}}" in raw_text or "${SECRET_PASSWORD}" in raw_text
    ):
        step_data = test_step.data if isinstance(test_step.data, dict) else {}
        resolved_pw = _decode_and_resolve_secret(step_data)
        if resolved_pw:
            arguments["text"] = raw_text.replace("{{password}}", str(resolved_pw)).replace(
                "${SECRET_PASSWORD}", str(resolved_pw)
            )
        else:
            return _done(
                StepOutcome.FAIL,
                msg=(
                    "Step requires secret password placeholder {{password}}, but no password was provided. "
                    "Set SUITEST_PASSWORD in your environment or configure test credentials."
                ),
            )

    raw_assertions = parsed.get("assertions", [])
    assertions: list[dict[str, object]] = (
        [a for a in raw_assertions if isinstance(a, dict)]
        if isinstance(raw_assertions, list)
        else []
    )

    ctx = InvokeContext(
        workspace_id=workspace_id,
        run_id=run_id,
        step_id=test_step.id,
        actor_user_id=actor_user_id,
        target_kind=TargetKind(test_step.target_kind),
        routing_overrides=routing_overrides,
    )

    try:
        result = await _invoke_tool(
            invoker=invoker,
            explicit_provider=test_step.mcp_provider,
            tool=tool,
            arguments=arguments,
            ctx=ctx,
        )
        await _run_assertions(
            invoker=invoker,
            explicit_provider=test_step.mcp_provider,
            assertions=assertions,
            result=result,
            ctx=ctx,
        )
        return _done(
            StepOutcome.PASS,
            mcp=result,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except McpToolTimeout as exc:
        return _done(StepOutcome.ERROR, msg=f"MCP_TOOL_TIMEOUT: {exc}", is_fatal_infra=True)
    except McpToolFailed as exc:
        outcome, clean_msg, is_fatal = classify_mcp_error(str(exc))
        return _done(
            outcome,
            msg=clean_msg,
            stderr=clean_msg,
            is_fatal_infra=is_fatal,
        )
    except Exception as exc:
        # Last-resort safety net: anything other than the two MCP exceptions
        # we already handle becomes an ERROR rather than crashing the worker.
        log.exception("step.executor.error", step_id=test_step.id)
        return _done(StepOutcome.ERROR, msg=f"INTERNAL: {exc}", is_fatal_infra=True)

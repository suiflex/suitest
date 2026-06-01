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

Empty ``code`` is *allowed* at ZERO tier: such steps are descriptive-only
(manual TCM), so we ``SKIP`` them with a stable reason string. At LOCAL/CLOUD
the same shape is reserved for the M3 agentic translator which converts the
prose ``action`` into a tool call on the fly — for now we ``SKIP`` with a
``TODO(M3)`` marker so the orchestrator keeps a clean run record without
fabricating a synthetic tool call.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_mcp.invoker import InvokeContext
from suitest_shared.domain.enums import StepOutcome, TargetKind, Tier

if TYPE_CHECKING:
    from suitest_db.models.case import TestStep as TestStepRow
    from suitest_mcp.invoker import McpInvoker
    from suitest_mcp.models import McpToolResult

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


def _normalize_tool_name(tool: str) -> str:
    return _LEGACY_TOOL_ALIASES.get(tool, tool)


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
    return await invoker.invoke(
        explicit_provider=explicit_provider,
        tool=normalized_tool,
        arguments=arguments,
        ctx=ctx,
    )


async def execute_step(
    *,
    invoker: McpInvoker,
    test_step: TestStepRow,
    run_id: str,
    workspace_id: str,
    actor_user_id: str | None,
    tier: Tier,
    routing_overrides: dict[str, object] | None,
    translator: StepTranslator | None = None,
) -> StepResult:
    """Dispatch one :class:`TestStep` via the MCP invoker and return its outcome.

    Decision tree:

    * ``code`` empty + (``tier=ZERO`` or no translator) → ``SKIP`` with
      ``NO_LLM_FOR_AGENTIC_STEP``.
    * ``code`` empty + LLM tier + translator → translate ``action`` → tool call
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
        )

    parsed: object
    if not test_step.code:
        # Agentic step: no deterministic code. At ZERO (or when no translator was
        # wired) it stays descriptive-only → SKIP. At LOCAL/CLOUD the M3-10
        # translator converts the prose ``action`` into a tool call on the fly.
        if tier == Tier.ZERO or translator is None:
            return _done(
                StepOutcome.SKIP,
                msg="NO_LLM_FOR_AGENTIC_STEP: step has no code",
            )
        try:
            translated = await translator(test_step.action)
        except Exception as exc:  # translator failure must not crash the run
            log.exception("step.executor.translate_error", step_id=test_step.id)
            return _done(StepOutcome.ERROR, msg=f"AGENTIC_TRANSLATE_ERROR: {exc}")
        if translated is None:
            return _done(
                StepOutcome.SKIP,
                msg="AGENTIC_TRANSLATE_FAILED: action not expressible as one tool call",
            )
        parsed = translated
    else:
        try:
            parsed = json.loads(test_step.code)
        except json.JSONDecodeError as exc:
            return _done(StepOutcome.ERROR, msg=f"INVALID_STEP_CODE: {exc}")

    if not isinstance(parsed, dict) or "tool" not in parsed:
        return _done(
            StepOutcome.ERROR,
            msg="INVALID_STEP_CODE: envelope missing 'tool' key",
        )

    tool = str(parsed["tool"])
    raw_args = parsed.get("arguments", {})
    arguments: dict[str, object] = dict(raw_args) if isinstance(raw_args, dict) else {}
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
        for assertion in assertions:
            a_args_raw = assertion.get("arguments", {})
            a_args: dict[str, object] = dict(a_args_raw) if isinstance(a_args_raw, dict) else {}
            # Forward the upstream tool's parsed stdout to the assertion so
            # checks like ``assert_status`` / ``assert_json_path`` can run
            # against the previous tool's normalized output.
            if result.stdout.startswith("{"):
                try:
                    a_args["result"] = json.loads(result.stdout)
                except json.JSONDecodeError:
                    a_args["result"] = {}
            else:
                a_args["result"] = {}
            await _invoke_tool(
                invoker=invoker,
                explicit_provider=test_step.mcp_provider,
                tool=str(assertion["tool"]),
                arguments=a_args,
                ctx=ctx,
            )
        return _done(
            StepOutcome.PASS,
            mcp=result,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except McpToolTimeout as exc:
        return _done(StepOutcome.ERROR, msg=f"MCP_TOOL_TIMEOUT: {exc}")
    except McpToolFailed as exc:
        return _done(
            StepOutcome.FAIL,
            msg=f"MCP_TOOL_FAILED: {exc}",
            stderr=str(exc),
        )
    except Exception as exc:
        # Last-resort safety net: anything other than the two MCP exceptions
        # we already handle becomes an ERROR rather than crashing the worker.
        log.exception("step.executor.error", step_id=test_step.id)
        return _done(StepOutcome.ERROR, msg=f"INTERNAL: {exc}")

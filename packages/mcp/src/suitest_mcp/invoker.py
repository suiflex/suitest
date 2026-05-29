"""High-level orchestrator combining pool + routing + audit (M1c Task 9).

:class:`McpInvoker` is the single entry point the runner (and later, the agent)
uses to execute one MCP tool call. It folds together every concern that wants
to live around a tool invocation:

* **Routing** — :func:`suitest_mcp.routing.resolve_provider` picks the provider
  from ``(explicit, workspace overrides, default mapping)``.
* **Health gating** — when a :class:`HealthMonitor` is wired in, the invoker
  refuses to dispatch to a provider that has been ``DOWN`` past the
  auto-disable threshold; the runner can then retry against a fallback.
* **Pooling** — sessions are leased via :class:`McpPool` so concurrent steps
  on the same provider share a small set of long-lived connections.
* **Redis events** — ``mcp.tool.start`` and ``mcp.tool.end`` are published on
  ``run:<run_id>`` so the M1c WS gateway can fan-out per-step telemetry to
  live UIs. Out-of-run invocations (no ``run_id``) skip publish.
* **Audit log** — every call appends one row via :func:`write_audit` with
  outcome + duration + sha256 ``arg_hash`` (we hash arguments rather than
  storing them verbatim so secrets in payloads don't leak into ``audit_logs``).
* **OpenTelemetry** — one ``mcp.invoke`` span per call carries provider, tool,
  workspace_id, run_id, step_id so distributed tracing can stitch a step back
  to its originating request.

Failure handling: :class:`McpToolTimeout` / :class:`McpToolFailed` raised by
the underlying :class:`McpSession` are caught, recorded (event + audit),
re-raised verbatim. The runner translates them into ``run_step`` status.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import structlog
from opentelemetry import trace
from suitest_db.audit import write_audit

from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_mcp.routing import resolve_provider

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from redis.asyncio import Redis as AsyncRedis
    from suitest_shared.domain.enums import TargetKind

    from suitest_mcp.health import HealthMonitor
    from suitest_mcp.models import McpProviderConfig, McpToolResult
    from suitest_mcp.pool import McpPool
    from suitest_mcp.registry import McpRegistry


log = structlog.get_logger(__name__)
tracer = trace.get_tracer("suitest.mcp.invoker")


class _AuditSession(Protocol):
    """Subset of :class:`AsyncSession` the invoker depends on.

    Declared as a Protocol so the invoker's signature stays free of
    SQLAlchemy specifics — tests inject a tiny recording stub and production
    wiring passes a real :class:`AsyncSession`.
    """

    def add(self, instance: object) -> None: ...

    async def commit(self) -> None: ...


class _AuditSessionFactory(Protocol):
    """Callable returning an async-context-managed audit session.

    Matches ``async_sessionmaker[AsyncSession]`` at runtime and ``__call__``
    returns an ``async with``-capable session. We type the inner value as
    :class:`_AuditSession` (a Protocol) rather than the concrete
    ``AsyncSession`` so test doubles satisfy the contract without inheriting
    SQLAlchemy.
    """

    def __call__(self) -> AbstractAsyncContextManager[_AuditSession]: ...


@dataclass
class InvokeContext:
    """Per-call attribution carried with one MCP tool invocation.

    ``workspace_id`` is required (multi-tenant gate). ``run_id`` / ``step_id``
    are optional because the invoker is also used outside a Run (e.g. agent
    tool calls during generation). ``actor_user_id`` is the human-or-system
    actor that triggered the call — recorded on the audit row.

    ``routing_overrides`` is the resolved ``workspace_capabilities``
    ``routing_overrides`` blob; the caller fetches it once per workspace and
    threads it through here so the invoker stays free of DB lookups.
    """

    workspace_id: str
    target_kind: TargetKind
    run_id: str | None = None
    step_id: str | None = None
    actor_user_id: str | None = None
    routing_overrides: dict[str, object] | None = field(default=None)


class McpInvoker:
    """Single entry point for one MCP tool call."""

    def __init__(
        self,
        *,
        registry: McpRegistry,
        pool: McpPool,
        health: HealthMonitor | None,
        redis_client: AsyncRedis,
        audit_session_factory: _AuditSessionFactory,
    ) -> None:
        self.registry = registry
        self.pool = pool
        self.health = health
        self.redis = redis_client
        self.audit_session_factory = audit_session_factory

    async def invoke(
        self,
        *,
        explicit_provider: str | None,
        tool: str,
        arguments: dict[str, object],
        ctx: InvokeContext,
    ) -> McpToolResult:
        """Dispatch one tool call end-to-end (routing → pool → publish → audit).

        Returns the :class:`McpToolResult` on success. Re-raises
        :class:`McpToolTimeout` / :class:`McpToolFailed` after publishing the
        ``mcp.tool.end`` event and writing the audit row so the runner gets
        observability + persistence for the failure path too.
        """
        provider = resolve_provider(
            self.registry,
            workspace_id=ctx.workspace_id,
            target_kind=ctx.target_kind,
            explicit=explicit_provider,
            overrides=ctx.routing_overrides,
        )
        if self.health is not None and not self.health.is_routable(provider.id):
            # We DO NOT publish / audit this branch: the provider was never
            # actually dispatched against. The caller (runner) will translate
            # the McpToolFailed into a step-level fault, and that step row's
            # mutation listener will pick up the audit naturally.
            raise McpToolFailed(f"provider {provider.name} auto-disabled (DOWN past threshold)")

        arg_hash = hashlib.sha256(
            json.dumps(arguments, sort_keys=True, default=str).encode()
        ).hexdigest()
        await self._publish(ctx, "mcp.tool.start", {"provider": provider.name, "tool": tool})

        start = time.perf_counter()
        with tracer.start_as_current_span("mcp.invoke") as span:
            span.set_attribute("mcp.provider", provider.name)
            span.set_attribute("mcp.tool", tool)
            span.set_attribute("suitest.workspace_id", ctx.workspace_id)
            span.set_attribute("suitest.run_id", ctx.run_id or "")
            span.set_attribute("suitest.step_id", ctx.step_id or "")

            try:
                async with self.pool.acquire(provider) as sess:
                    result = await sess.call_tool(
                        tool, arguments, timeout_seconds=provider.call_timeout_seconds
                    )
            except McpToolTimeout as exc:
                span.record_exception(exc)
                duration_ms = int((time.perf_counter() - start) * 1000)
                await self._finalize(
                    ctx, provider, tool, arg_hash, "timeout", duration_ms, str(exc)
                )
                raise
            except McpToolFailed as exc:
                span.record_exception(exc)
                duration_ms = int((time.perf_counter() - start) * 1000)
                await self._finalize(ctx, provider, tool, arg_hash, "failed", duration_ms, str(exc))
                raise

        await self._finalize(ctx, provider, tool, arg_hash, "ok", result.duration_ms, None)
        return result

    async def _publish(self, ctx: InvokeContext, event_name: str, data: dict[str, object]) -> None:
        """Publish one event on ``run:<run_id>`` (skipped when no run binds the call).

        Event payload shape mirrors the rest of the M1c WS protocol:
        ``{"event": "<name>", "data": {"runId": ..., "stepId": ..., ...}}``.
        """
        if not ctx.run_id:
            return
        payload: dict[str, object] = {
            "event": event_name,
            "data": {"runId": ctx.run_id, "stepId": ctx.step_id, **data},
        }
        await self.redis.publish(f"run:{ctx.run_id}", json.dumps(payload))

    async def _finalize(
        self,
        ctx: InvokeContext,
        provider: McpProviderConfig,
        tool: str,
        arg_hash: str,
        outcome: str,
        duration_ms: int,
        error: str | None,
    ) -> None:
        """Publish ``mcp.tool.end`` + append the audit row for one invocation."""
        await self._publish(
            ctx,
            "mcp.tool.end",
            {
                "provider": provider.name,
                "tool": tool,
                "outcome": outcome,
                "durationMs": duration_ms,
                "error": error,
            },
        )
        async with self.audit_session_factory() as session:
            await write_audit(
                session,
                workspace_id=ctx.workspace_id,
                user_id=ctx.actor_user_id,
                action="mcp.invoke",
                resource_type="mcp_provider",
                resource_id=provider.name,
                metadata={
                    "tool": tool,
                    "arg_hash": arg_hash,
                    "outcome": outcome,
                    "duration_ms": duration_ms,
                    "run_id": ctx.run_id,
                    "step_id": ctx.step_id,
                },
            )
            await session.commit()

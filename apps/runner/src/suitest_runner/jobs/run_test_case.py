"""``run_test_case`` ARQ job — orchestrates one full test run end-to-end.

The orchestrator owns the run lifecycle:

1. Load the run + its step selection (M1c implicit selection: every active case
   in the project's suites, in suite/case/step order).
2. Resolve the workspace capability tier + routing overrides.
3. Mark the run ``RUNNING``, publish ``run.started``.
4. For each step: publish ``run.step.started`` → dispatch via
   :func:`suitest_runner.executors.step_executor.execute_step` →
   persist a ``run_steps`` row → upload artifacts → publish
   ``run.step.completed``.
5. Aggregate per-outcome counters, update the run with terminal status,
   publish ``run.completed``.
6. On each ``StepOutcome.FAIL``, dispatch to
   :func:`suitest_runner.handlers.step_handler.on_run_step_failed`, which
   hands the row to the M1d-10 :class:`DefectAutoFiler` (categorise →
   dedup-aware insert → ``defect.created`` WS broadcast → enqueue downstream
   notifier / issue-tracker jobs). The hook is wrapped in try/except so a
   degraded defect pipeline never blocks run completion.

Everything that touches the DB happens inside a fresh ``session_factory()``
context manager so the worker's job-level concurrency doesn't share an
``AsyncSession`` across coroutines (SQLAlchemy sessions are not safe for that).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

import structlog
from suitest_agent.graphs.execution import translate_single_step
from suitest_agent.providers.litellm_router import get_provider
from suitest_db.models.project import Project
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.run_step_logs import RunStepLogRepo
from suitest_db.repositories.runs import RunRepo, RunStepRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_mcp.invoker import McpInvoker
from suitest_mcp.registry import McpRegistry
from suitest_shared.domain.enums import RunStatus, StepOutcome, Tier

from suitest_runner.executors.step_executor import StepTranslator, execute_step
from suitest_runner.handlers.step_handler import on_run_step_failed
from suitest_runner.observability import get_tracer

if TYPE_CHECKING:
    from suitest_api.services.defect_auto_filer import DefectAutoFiler

log = structlog.get_logger(__name__)


@runtime_checkable
class _Publisher(Protocol):
    """Minimal Redis publish surface so tests can sub a recorder for ``publish``."""

    async def publish(self, channel: str, message: str | bytes) -> int: ...


def _is_defect_auto_filer(obj: object) -> bool:
    """Duck-typed check for the M1d-10 defect auto-filer.

    We avoid a hard import-time dependency on
    :class:`~suitest_api.services.defect_auto_filer.DefectAutoFiler` (the
    api package is logically downstream of the runner from a deployment
    standpoint, even though both currently live in the same monorepo) by
    structurally checking for the single method the hook calls. This keeps
    the runner importable in test fixtures that monkeypatch ``ctx`` with
    plain stubs.
    """
    return hasattr(obj, "file_for_failed_step") and callable(
        getattr(obj, "file_for_failed_step", None)
    )


@runtime_checkable
class _LogseqIncrementer(Protocol):
    """Redis ``INCR`` surface used to mint the per-run monotonic ``seq`` counter."""

    async def incr(self, name: str) -> int: ...


async def _build_translator(
    session: object, *, tier: Tier, workspace_id: str
) -> StepTranslator | None:
    """Bind the workspace's active LLM into a per-step action→code translator.

    Returns ``None`` at ZERO tier or when no LLM is configured — agentic steps
    then stay ``SKIP``. The provider is resolved once and closed over so every
    step in the run reuses the same client (M3-10).
    """
    if tier not in (Tier.LOCAL, Tier.CLOUD):
        return None
    from sqlalchemy.ext.asyncio import AsyncSession

    if not isinstance(session, AsyncSession):  # pragma: no cover - defensive
        return None
    llm = await LLMConfigRepo(session).get_active(workspace_id)
    if llm is None:
        return None
    base_url = llm.config_json.get("base_url")
    provider = get_provider(
        llm.provider,
        api_key=llm.api_key_encrypted,
        base_url=base_url if isinstance(base_url, str) else None,
    )
    model = llm.model

    async def _translate(action: str) -> dict[str, object] | None:
        return await translate_single_step(provider, model=model, action=action)

    return _translate


async def run_test_case(ctx: dict[str, object], run_id: str) -> dict[str, object]:
    """Execute one test run.

    Args:
        ctx: ARQ-supplied per-job context. Must contain ``session_factory``,
            ``redis``, ``invoker``, ``registry`` (wired by
            :func:`suitest_runner.worker.startup`).
        run_id: Public/internal ID of the run row to execute.

    Returns:
        Summary dict: ``{"run_id": ..., "status": "PASS"|"FAIL", "total": N,
        "passed": ..., "failed": ..., "errored": ..., "skipped": ...}`` —
        the shape the M1c WS gateway tests assert against.
    """
    factory = ctx.get("session_factory")
    redis_client = ctx.get("redis")
    invoker = ctx.get("invoker")
    registry = ctx.get("registry")
    if not callable(factory):
        return {"error": "RUNNER_CTX_INVALID", "field": "session_factory"}
    if not isinstance(invoker, McpInvoker):
        return {"error": "RUNNER_CTX_INVALID", "field": "invoker"}
    if not isinstance(registry, McpRegistry):
        return {"error": "RUNNER_CTX_INVALID", "field": "registry"}

    tracer = get_tracer()

    with tracer.start_as_current_span(
        "runner.run_test_case",
        attributes={"job.queue": "suitest:runs", "run.id": run_id},
    ):
        # --- load run + selection + tier ----------------------------------
        async with factory() as session:
            run_repo = RunRepo(session)
            run, selection = await run_repo.get_with_selection(run_id)
            if run is None:
                log.warning("runner.job.missing_run", run_id=run_id)
                return {"error": "RUN_NOT_FOUND", "run_id": run_id}

            project = await session.get(Project, run.project_id)
            workspace_id = project.workspace_id if project is not None else None
            if workspace_id is None:
                log.warning("runner.job.missing_project", run_id=run_id)
                return {"error": "RUN_PROJECT_MISSING", "run_id": run_id}

            if workspace_id not in registry._by_workspace:
                await registry.load_for_workspace(session, workspace_id)

            capability = await WorkspaceCapabilityRepo(session).get(workspace_id)
            tier = Tier(capability.tier) if capability is not None else Tier.ZERO
            overrides_raw = (
                capability.features_json.get("routing_overrides") if capability else None
            )
            overrides: dict[str, object] | None = (
                overrides_raw if isinstance(overrides_raw, dict) else None
            )
            triggered_by = run.triggered_by

            # M3-10: at LOCAL/CLOUD tier, bind the workspace's LLM into a
            # per-step translator so agentic (code-less) steps resolve their
            # ``action`` to a tool call at execution time. ZERO / no-LLM → None
            # (such steps stay SKIP, exactly as before).
            translator = await _build_translator(session, tier=tier, workspace_id=workspace_id)

            await run_repo.update_status(
                run_id,
                RunStatus.RUNNING,
                started_at=datetime.now(UTC),
                tier_at_runtime=tier,
            )
            await session.commit()

        await _publish(
            redis_client,
            run_id,
            "run.started",
            {"runId": run_id, "tier": tier.value},
            factory=factory,
        )

        # --- per-step dispatch --------------------------------------------
        summary = {"total": 0, "passed": 0, "failed": 0, "errored": 0, "skipped": 0}
        t0 = time.perf_counter()

        for case_id, step_order, test_step in selection:
            summary["total"] += 1
            await _publish(
                redis_client,
                run_id,
                "run.step.started",
                {
                    "runId": run_id,
                    "stepIndex": step_order,
                    "action": test_step.action,
                    "mcpProvider": test_step.mcp_provider,
                    "targetKind": (
                        test_step.target_kind.value
                        if hasattr(test_step.target_kind, "value")
                        else str(test_step.target_kind)
                    ),
                },
                factory=factory,
            )

            result = await execute_step(
                invoker=invoker,
                test_step=test_step,
                run_id=run_id,
                workspace_id=workspace_id,
                actor_user_id=triggered_by,
                tier=tier,
                routing_overrides=overrides,
                translator=translator,
            )

            async with factory() as session:
                run_step_repo = RunStepRepo(session)
                run_step = await run_step_repo.create_step(
                    run_id=run_id,
                    case_id=case_id,
                    step_order=step_order,
                    outcome=result.outcome,
                    started_at=result.started_at,
                    completed_at=result.completed_at,
                    duration_ms=result.duration_ms,
                    stdout=result.stdout or None,
                    stderr=result.stderr or None,
                    error_message=result.error_message,
                    # M5-1: capture the normalized MCP output as the step's state
                    # snapshot so time-travel replay can diff consecutive steps.
                    state_snapshot=(
                        dict(result.mcp_result.output)
                        if result.mcp_result is not None and result.mcp_result.output
                        else None
                    ),
                )
                if result.mcp_result is not None and result.mcp_result.artifacts:
                    # Task 13 wires this. Late import keeps the runner importable
                    # without aioboto3 installed when artifact upload is disabled.
                    from suitest_runner.artifacts import upload_artifacts

                    await upload_artifacts(
                        session=session,
                        ctx=ctx,
                        run_id=run_id,
                        run_step_id=run_step.id,
                        step_order=step_order,
                        artifacts=result.mcp_result.artifacts,
                    )
                await session.commit()

            await _publish(
                redis_client,
                run_id,
                "run.step.completed",
                {
                    "runId": run_id,
                    "stepIndex": step_order,
                    "outcome": result.outcome.value,
                    "durationMs": result.duration_ms,
                    "error": result.error_message,
                },
                factory=factory,
                run_step_id=run_step.id,
            )
            if result.outcome == StepOutcome.PASS:
                summary["passed"] += 1
            elif result.outcome == StepOutcome.FAIL:
                summary["failed"] += 1
                # M1d-10: hand the failed step off to the defect auto-filer.
                # The hook owns its own try/except so a degraded defect
                # pipeline never blocks run completion. We swallow any
                # exception that bubbles out of the hook itself for the
                # same reason — orchestrator forward-progress is paramount.
                auto_filer = ctx.get("defect_auto_filer")
                # ``cast`` is intentional — the handler accepts a nominal
                # ``DefectAutoFiler | None`` but mypy can't narrow ``object``
                # to that type. :func:`_is_defect_auto_filer` is the runtime
                # source of truth — non-conforming objects become ``None``.
                typed_filer: DefectAutoFiler | None = (
                    cast("DefectAutoFiler", auto_filer)
                    if _is_defect_auto_filer(auto_filer)
                    else None
                )
                try:
                    await on_run_step_failed(
                        auto_filer=typed_filer,
                        run_step=run_step,
                    )
                except Exception as exc:
                    log.warning(
                        "runner.step.fail.hook_error",
                        run_step_id=run_step.id,
                        reason=str(exc),
                    )
            elif result.outcome == StepOutcome.SKIP:
                summary["skipped"] += 1
            else:
                summary["errored"] += 1

        # --- finalize -----------------------------------------------------
        duration_ms = int((time.perf_counter() - t0) * 1000)
        failed_total = summary["failed"] + summary["errored"]
        final_status = RunStatus.FAIL if failed_total > 0 else RunStatus.PASS

        async with factory() as session:
            await RunRepo(session).update_status(
                run_id,
                final_status,
                completed_at=datetime.now(UTC),
                duration_ms=duration_ms,
                total_steps=summary["total"],
                passed_steps=summary["passed"],
                failed_steps=failed_total,
            )
            await session.commit()

        await _publish(
            redis_client,
            run_id,
            "run.completed",
            {
                "runId": run_id,
                "status": final_status.value,
                "totalSteps": summary["total"],
                "passedSteps": summary["passed"],
                "failedSteps": failed_total,
                "durationMs": duration_ms,
            },
            factory=factory,
        )

        # --- best-effort defect filing ------------------------------------
        # M1d-10 ships per-step defect filing via the ``on_run_step_failed``
        # hook above; the old per-run filer below is retained as a no-op
        # safety net until M2 deletes it.
        if failed_total > 0:
            await _try_file_defect(factory, run_id)

        return {
            "run_id": run_id,
            "status": final_status.value,
            "total": summary["total"],
            "passed": summary["passed"],
            "failed": summary["failed"],
            "errored": summary["errored"],
            "skipped": summary["skipped"],
        }


async def _publish(
    redis_client: object,
    run_id: str,
    event: str,
    data: dict[str, object],
    *,
    factory: object = None,
    run_step_id: str | None = None,
    level: str = "info",
) -> None:
    """Publish ``{"event": ..., "data": ...}`` to Redis AND persist to ``run_step_logs``.

    Typed against a structural :class:`_Publisher` so test stubs (a recorder
    that just appends to a list) satisfy the contract without inheriting
    :class:`redis.asyncio.Redis`. When ``factory`` is callable AND the redis
    client supports ``INCR``, an explicit per-run monotonic sequence is
    minted via ``INCR run:<id>:logseq`` and the payload is appended to
    ``run_step_logs``. Persistence is best-effort: a transient DB / Redis
    failure logs a warning but never blocks the publish hot path (the runs
    UI degrades to the live socket stream).
    """
    payload = json.dumps({"event": event, "data": data})
    if isinstance(redis_client, _Publisher):
        await redis_client.publish(f"run:{run_id}", payload)
    if not callable(factory) or not isinstance(redis_client, _LogseqIncrementer):
        return
    try:
        seq = int(await redis_client.incr(f"run:{run_id}:logseq"))
        async with factory() as session:
            await RunStepLogRepo(session).append(
                run_id=run_id,
                run_step_id=run_step_id,
                level=level,
                message=payload,
                seq=seq,
            )
            await session.commit()
    except Exception as exc:
        log.warning("runner.log.persist_skip", run_id=run_id, reason=str(exc))


async def _try_file_defect(factory: object, run_id: str) -> None:
    """Best-effort defect ingest after a failed run.

    The :class:`DefectService` lives in ``apps/api`` and the runner does not
    hard-depend on it; we late-import and swallow any error (import-time,
    constructor signature drift, missing method) so a defect-pipeline outage
    can never poison a completed run record. M2 will move the service into a
    shared package and let us drop this duck-typing.
    """
    if not callable(factory):
        return
    try:
        from suitest_api.services.defect_service import DefectService

        async with factory() as session:
            # DefectService takes (ctx, repo) today, which the runner doesn't
            # have around. We only call it when both pieces are reachable —
            # for now the missing args path falls through to the warn log.
            if not hasattr(DefectService, "file_for_failed_run"):
                return
            log.info("runner.defect.not_wired", run_id=run_id)
            _ = session
    except Exception as exc:
        log.warning("runner.defect.skip", run_id=run_id, reason=str(exc))

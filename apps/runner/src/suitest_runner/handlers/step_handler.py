"""``on_run_step_failed`` — runner step-failed event handler (M1d-10).

The orchestrator (``suitest_runner.jobs.run_test_case.run_test_case``) calls
:func:`on_run_step_failed` once per step that reports
:attr:`~suitest_shared.domain.enums.StepOutcome.FAIL`. The handler dispatches
the failure to :class:`~suitest_api.services.defect_auto_filer.DefectAutoFiler`
which categorises the failure (regex over stderr/stdout/assertion message),
inserts the defect with ``created_by='system'``, dedups via the
``uq_defects_auto_dedup`` partial unique idx, and enqueues downstream
notifier / issue-tracker ARQ jobs.

Failure semantics: any exception thrown by the auto-filer is caught here and
logged — the runner orchestrator MUST keep finishing the run even if the
defect pipeline is degraded (the run record is the canonical truth; defects
are an enrichment layer). This contract is exercised in
``apps/runner/tests/test_step_handler_hook.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from suitest_api.services.defect_auto_filer import DefectAutoFiler
    from suitest_db.models.run import RunStep

log = structlog.get_logger(__name__)


async def on_run_step_failed(
    *,
    auto_filer: DefectAutoFiler | None,
    run_step: RunStep,
) -> None:
    """Dispatch a FAIL outcome to the auto-filer; absorb every error.

    Args:
        auto_filer: Filer to invoke. Optional so the runner can wire ``None``
            in environments where the API-side service isn't reachable (e.g.
            the runner is deployed standalone for a unit-test run). When
            ``None`` the handler is a no-op + a debug log.
        run_step: The persisted ``run_steps`` row whose ``outcome`` is FAIL.
            The handler only consumes ``id``; the auto-filer re-loads the
            full row inside its own session so we don't smuggle a
            cross-coroutine ORM object across event-loop boundaries.

    Returns:
        ``None`` always. Side effects (DB write + redis publish + ARQ
        enqueue) happen inside the auto-filer. We deliberately don't return
        the inserted :class:`Defect` because the runner has no use for it —
        downstream consumers subscribe via the ``defect.created`` WS event.
    """
    if auto_filer is None:
        log.debug("runner.step.fail.no_auto_filer", run_step_id=run_step.id)
        return
    try:
        defect = await auto_filer.file_for_failed_step(run_step.id)
        if defect is None:
            log.debug(
                "runner.step.fail.no_defect_filed",
                run_step_id=run_step.id,
                reason="dedup_or_missing_row",
            )
            return
        log.info(
            "runner.step.fail.defect_filed",
            run_step_id=run_step.id,
            defect_id=defect.id,
            severity=defect.severity.value,
            kind=defect.agent_diagnosis_kind.value,
        )
    except Exception as exc:  # pragma: no cover — defensive; auto-filer also catches
        log.warning(
            "runner.step.fail.auto_filer_error",
            run_step_id=run_step.id,
            error=str(exc),
        )

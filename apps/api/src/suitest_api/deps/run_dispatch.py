"""Run trigger seam: ``server`` enqueues to ARQ/Redis; ``local`` no-ops.

In local mode the run row is already persisted as QUEUED by the caller; the
local supervisor (:mod:`suitest_runner.local_supervisor`, a separate process
launched by ``suitest up``) polls and executes it. The API never imports the
runner package — the boundary in :mod:`suitest_api.deps.arq` is preserved.

Returns the ARQ job-id string when in server mode (so callers can persist it
via ``RunService.attach_arq_job_id``), or ``None`` in local mode.
"""

from __future__ import annotations

from typing import Protocol


class _Enqueuer(Protocol):
    async def enqueue_job(
        self, name: str, /, *args: object, _queue_name: str | None = None
    ) -> object: ...


async def dispatch_run(
    *,
    mode: str,
    arq: _Enqueuer,
    run_id: str,
    queue_name: str,
) -> str | None:
    """Enqueue a run in server mode; no-op in local mode.

    Returns the ARQ job-id when enqueued, ``None`` otherwise (local mode or
    when ARQ returns ``None`` for a duplicate job).
    """
    if mode == "local":
        return None  # ponytail: supervisor drains QUEUED runs; nothing to enqueue
    job = await arq.enqueue_job("run_test_case", run_id, _queue_name=queue_name)
    if job is None:
        return None
    job_id = getattr(job, "job_id", None)
    return job_id if isinstance(job_id, str) else None

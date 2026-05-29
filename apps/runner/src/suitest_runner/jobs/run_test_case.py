"""Run-test-case ARQ job — placeholder for M1c Task 10.

The real executor (mixed-MCP step dispatcher, step output normalization, artifact
upload, defect ingest) lands in M1c Task 11. This stub keeps the queue + worker
wiring honest: ARQ has at least one registered function so ``Worker.main`` does
not refuse to start, and the placeholder return shape gives Task 11 a contract
test to break against.
"""

from __future__ import annotations

import structlog

from suitest_runner.observability import get_tracer

log = structlog.get_logger(__name__)


async def run_test_case(ctx: dict[str, object], run_id: str) -> dict[str, object]:
    """Pick up a run, log it, return the documented placeholder payload.

    Args:
        ctx: ARQ-supplied per-job context. ARQ populates ``job_id`` / ``job_try``
            / ``score`` / ``enqueue_time`` before invoking the job. We only read
            ``job_id`` here (defensively — direct invocations from tests may
            omit it).
        run_id: Public ID of the test run to execute.

    Returns:
        ``{"status": "placeholder", "run_id": <run_id>}`` — matches the shape
        the Task-10 worker test asserts against.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "runner.run_test_case",
        attributes={
            "job.id": str(ctx.get("job_id", "")),
            "job.queue": "suitest:runs",
            "run.id": run_id,
        },
    ):
        log.info("runner.job.pickup", run_id=run_id, job_id=ctx.get("job_id"))
        return {"status": "placeholder", "run_id": run_id}

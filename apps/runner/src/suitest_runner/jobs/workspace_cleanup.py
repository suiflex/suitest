"""``workspace_cleanup`` ARQ job — M1d-28 placeholder.

Enqueued by ``DELETE /workspaces/:id`` (OWNER-only, slug-typed-confirm) after
the API tombstones ``workspaces.deleted_at = now()``. Reads short-circuit
immediately so the workspace disappears from the FE; this job tears down the
heavy resources behind the scenes:

1. MCP provider sessions for the workspace (``McpPool.purge_workspace``)
2. Artifact blobs in R2 / MinIO under ``workspaces/<id>/``
3. Child rows (projects → suites → cases → steps → runs → defects → …)
4. Final ``workspace.deleted`` WS event so any listener can drop caches.

Today the executor only logs + returns a status dict — implementing the actual
teardown is tracked as a follow-up (see issue ``M1d-28-FOLLOWUP`` once filed).
Shipping the stub now lets the API enqueue safely and keeps the WS contract
stable for the FE (``workspace.delete_initiated`` + future ``workspace.deleted``).
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


# TODO(M1d-28-FOLLOWUP): implement the four teardown stages above. The runner
# already has McpPool + redis on ``ctx`` (see :mod:`suitest_runner.worker`) and
# can grow an artifact-store handle the same way. Until then, this stub keeps
# the queue contract — the API enqueues, the worker dequeues + acks — so the
# DoD slug-typed-confirm flow ships green.
async def workspace_cleanup(ctx: dict[str, object], workspace_id: str) -> dict[str, object]:
    """Best-effort placeholder. Logs the request and returns a stub summary.

    Args:
        ctx: ARQ-supplied per-job context (mirrors :func:`run_test_case`).
        workspace_id: The cuid2 string from the tombstoned workspace row.

    Returns:
        Summary dict: ``{"workspace_id", "status", "stage"}`` so a future
        executor can grow incremental progress reporting without changing the
        public job-result contract.
    """
    log.info(
        "runner.workspace_cleanup.received",
        workspace_id=workspace_id,
        note="executor TODO — see module docstring",
    )
    return {
        "workspace_id": workspace_id,
        "status": "QUEUED_NOOP",
        "stage": "placeholder",
    }

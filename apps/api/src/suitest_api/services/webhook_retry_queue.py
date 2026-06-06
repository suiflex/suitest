"""WebhookRetryQueue — durable, idempotent, backoff retry for outbound calls (M4-31).

Every outbound call to an external integration (Jira / Linear / GitHub / Slack /
GitLab) goes through this queue instead of firing inline. The queue:

* Persists the rendered payload in ``webhook_dispatch_attempts`` *before*
  dispatch, so a process crash / 5xx never loses it.
* Dedups by ``(integration_id, idempotency_key)`` — a double-fire collapses to
  one upstream effect (``INSERT ... ON CONFLICT DO NOTHING``).
* Retries with exponential backoff (:data:`BACKOFF_SECONDS`, max
  :data:`MAX_ATTEMPTS`).
* Dead-letters after the budget is exhausted: flips the integration to
  ``status=error`` so the UI surfaces it, and stops retrying.

The dispatch itself runs in the ``dispatch_webhook`` ARQ job
(:mod:`suitest_runner.jobs.dispatch_webhook`) — this module owns enqueue +
ledger bookkeeping; the runner owns the wire call. Splitting the two keeps the
backoff schedule + idempotency rules in one importable place that both the API
(enqueue side) and the runner (dispatch side) read.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from suitest_db.models.webhook_dispatch import WebhookDispatchAttempt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Exponential backoff schedule, indexed by 0-based completed-attempt count.
# After attempt ``n`` fails (1-based), the next dispatch is deferred by
# ``BACKOFF_SECONDS[n - 1]``. Seven entries == :data:`MAX_ATTEMPTS`.
# Spec (ROADMAP M4-31): 1s, 5s, 30s, 5m, 1h, 6h, 24h.
BACKOFF_SECONDS: Final[tuple[int, ...]] = (1, 5, 30, 300, 3600, 21600, 86400)
MAX_ATTEMPTS: Final[int] = 7

DISPATCH_QUEUE: Final[str] = "suitest:runs"


class _ArqEnqueueCapable(Protocol):
    """Subset of :class:`arq.connections.ArqRedis` the queue needs."""

    async def enqueue_job(self, name: str, *args: object, **kwargs: object) -> object: ...


def _hash_payload(payload: dict[str, object]) -> str:
    """Stable SHA-256 of the canonicalised payload (dedup + tamper check)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def backoff_for(attempt_n: int) -> int:
    """Seconds to defer the *next* dispatch after ``attempt_n`` (1-based) failed.

    Clamps to the last bucket so an off-by-one never raises.
    """
    idx = max(0, min(attempt_n - 1, len(BACKOFF_SECONDS) - 1))
    return BACKOFF_SECONDS[idx]


class WebhookRetryQueue:
    """Enqueue side of the durable webhook retry pipeline.

    Stateless apart from the ARQ pool handle; safe to construct per-request.
    """

    def __init__(self, arq_pool: _ArqEnqueueCapable | None) -> None:
        self._arq = arq_pool

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        integration_id: str,
        operation: str,
        payload: dict[str, object],
        idempotency_key: str,
    ) -> WebhookDispatchAttempt:
        """Persist a dispatch row (idempotent) and enqueue the worker.

        Returns the ledger row. If ``(integration_id, idempotency_key)`` already
        exists the existing row is returned and NO new ARQ job is enqueued — the
        prior dispatch is already in flight or terminal.

        The caller owns the surrounding transaction; this method flushes but
        does not commit, so the row participates in the caller's unit of work.
        The ARQ enqueue is best-effort and happens after flush.
        """
        payload_hash = _hash_payload(payload)
        stmt = (
            pg_insert(WebhookDispatchAttempt)
            .values(
                workspace_id=workspace_id,
                integration_id=integration_id,
                idempotency_key=idempotency_key,
                operation=operation,
                payload_json=payload,
                payload_hash=payload_hash,
                status="pending",
                attempt_n=0,
            )
            .on_conflict_do_nothing(constraint="webhook_dedup")
            .returning(WebhookDispatchAttempt.id)
        )
        result = await session.execute(stmt)
        inserted_id = result.scalar_one_or_none()

        if inserted_id is None:
            # Dedup hit — return the pre-existing row, do not re-enqueue.
            existing = await session.scalar(
                select(WebhookDispatchAttempt).where(
                    WebhookDispatchAttempt.integration_id == integration_id,
                    WebhookDispatchAttempt.idempotency_key == idempotency_key,
                )
            )
            assert existing is not None  # unique row must exist after conflict
            return existing

        row = await session.get(WebhookDispatchAttempt, inserted_id)
        assert row is not None
        await session.flush()

        if self._arq is not None:
            await self._arq.enqueue_job("dispatch_webhook", row.id, _queue_name=DISPATCH_QUEUE)
        return row

"""WebhookDispatchAttempt — durable retry ledger for outbound integration calls.

Backs the M4-31 :class:`~suitest_api.services.webhook_retry_queue.WebhookRetryQueue`.
Every outbound call to an external tracker / notifier (Jira / Linear / GitHub /
Slack / GitLab) is recorded here before dispatch so a transient 5xx never loses
the payload. One row = one logical dispatch (deduped by ``idempotency_key``);
``attempt_n`` counts how many times the ARQ job has tried it.

Lifecycle (``status``):

* ``pending`` — enqueued, not yet attempted (or between retries).
* ``succeeded`` — adapter accepted the payload; terminal.
* ``failed`` — transient error, ``next_retry_at`` set, will retry.
* ``dead_letter`` — exhausted ``MAX_ATTEMPTS`` (7); integration flipped to
  ``status=error`` and surfaced in the UI; terminal.

The ``payload_json`` column holds the already-rendered request body so the
retry worker is fully self-contained — it never re-derives the payload from
mutable domain rows (which may have changed between attempts). Secrets are NOT
stored here; the worker resolves them from the integration row at dispatch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id
from suitest_db.types import PortableJSON


class WebhookDispatchAttempt(Base, TimestampMixin):
    __tablename__ = "webhook_dispatch_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    integration_id: Mapped[str] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    # Caller-provided dedup key. Two enqueues with the same key collapse to one
    # row (INSERT ... ON CONFLICT DO NOTHING) so a double-fire never doubles the
    # upstream effect. Scoped per-integration via the unique constraint below.
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    # Logical operation the worker dispatches, e.g. ``file_external_issue`` /
    # ``send_notification`` / ``sync_status``. The worker maps this to an adapter
    # method; kept as free-form text so new operations don't need a migration.
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, default=dict, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempt_n: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("integration_id", "idempotency_key", name="webhook_dedup"),
        Index("ix_webhook_dispatch_attempts_status", "status"),
        Index(
            "ix_webhook_dispatch_attempts_next_retry_at",
            "next_retry_at",
            postgresql_where=func.coalesce(status == "failed", False),
        ),
    )

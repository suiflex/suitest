"""``run_step_logs`` ORM — persisted run-log line stream (docs/DATA_MODEL.md §3.6 update).

Written through alongside the Redis pubsub by
:func:`suitest_runner.jobs.run_test_case.run_test_case` so historical lines
survive Redis retention. The ``(run_id, seq)`` composite index backs the
cursor-paginated ``GET /api/v1/runs/:id/logs`` read path. ``seq`` is the
per-run counter the orchestrator increments via Redis ``INCR``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from suitest_db.base import Base
from suitest_db.ids import new_id


class RunStepLog(Base):
    __tablename__ = "run_step_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    run_step_id: Mapped[str | None] = mapped_column(
        ForeignKey("run_steps.id", ondelete="CASCADE"), nullable=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_run_step_logs_run_seq", "run_id", "seq"),)

"""Run / RunStep / Artifact models (docs/DATA_MODEL.md §3.6).

``metadata`` is reserved on ``DeclarativeBase`` (it shadows ``Base.metadata``),
so the Python attribute is ``metadata_json`` while the DB column stays
``metadata`` (see DATA_MODEL §3.1 naming note).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from suitest_shared.domain.enums import ArtifactKind, RunStatus, RunTrigger, StepOutcome, Tier

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(120))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    env: Mapped[str] = mapped_column(String(32), default="staging", nullable=False)
    trigger: Mapped[RunTrigger] = mapped_column(
        SAEnum(RunTrigger, name="run_trigger"), nullable=False
    )
    triggered_by: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status"), default=RunStatus.QUEUED, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    # NEW — captured at run start so historical runs stay reproducible
    tier_at_runtime: Mapped[Tier] = mapped_column(SAEnum(Tier, name="tier"), nullable=False)

    total_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (
        Index("ix_runs_project_status", "project_id", "status"),
        Index("ix_runs_created_at", "created_at"),
        Index("ix_runs_tier", "tier_at_runtime"),
    )


class RunStep(Base, TimestampMixin):
    __tablename__ = "run_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    # No CASCADE on case_id — preserve historical run data if a case is deleted.
    case_id: Mapped[str] = mapped_column(ForeignKey("test_cases.id"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[StepOutcome] = mapped_column(
        SAEnum(StepOutcome, name="step_outcome"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    stdout: Mapped[str | None] = mapped_column(Text)
    stderr: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_stack: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_run_steps_run_outcome", "run_id", "outcome"),)


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_step_id: Mapped[str] = mapped_column(
        ForeignKey("run_steps.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ArtifactKind] = mapped_column(
        SAEnum(ArtifactKind, name="artifact_kind"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)  # s3:// or file://
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (Index("ix_artifacts_run_step_id", "run_step_id"),)

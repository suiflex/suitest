"""Defect + ExternalIssue models (docs/DATA_MODEL.md §3.7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from suitest_shared.domain.enums import DefectStatus, DiagnosisKind, Severity

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class Defect(Base, TimestampMixin):
    __tablename__ = "defects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    test_case_id: Mapped[str | None] = mapped_column(ForeignKey("test_cases.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    requirement_id: Mapped[str | None] = mapped_column(ForeignKey("requirements.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(SAEnum(Severity, name="severity"), nullable=False)
    status: Mapped[DefectStatus] = mapped_column(
        SAEnum(DefectStatus, name="defect_status"), default=DefectStatus.OPEN, nullable=False
    )
    component: Mapped[str | None] = mapped_column(String(120))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    agent_diagnosis: Mapped[str | None] = mapped_column(Text)

    # NEW — diagnosis kind drives downstream automation (retry / block / triage-manual)
    agent_diagnosis_kind: Mapped[DiagnosisKind] = mapped_column(
        SAEnum(DiagnosisKind, name="diagnosis_kind"),
        default=DiagnosisKind.MANUAL_TRIAGE,
        nullable=False,
    )
    agent_confidence: Mapped[float | None] = mapped_column(Float)
    stack_trace: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_defects_workspace_status", "workspace_id", "status"),
        Index("ix_defects_severity", "severity"),
        Index("ix_defects_diagnosis_kind", "agent_diagnosis_kind"),
    )


class ExternalIssue(Base, TimestampMixin):
    __tablename__ = "external_issues"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    defect_id: Mapped[str] = mapped_column(
        ForeignKey("defects.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_external_issues_provider_external"),
    )

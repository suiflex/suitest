"""Test case / step / tag models (docs/DATA_MODEL.md §3.4).

``TestStep.executable`` is intentionally NOT a column — it is computed at read
time from the workspace tier via the domain model
``suitest_shared.domain.case.TestStep.executable(tier)``. See DATA_MODEL §3.4/§5.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, TargetKind

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id

if TYPE_CHECKING:
    # Resolved at runtime via SQLAlchemy's registry; a runtime import would create
    # a project ↔ case cycle.
    from suitest_db.models.project import Suite  # noqa: TCH004


class TestCase(Base, TimestampMixin):
    __tablename__ = "test_cases"
    __test__ = False  # not a pytest test class

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    suite_id: Mapped[str] = mapped_column(
        ForeignKey("suites.id", ondelete="CASCADE"), nullable=False
    )
    # Blocker #3: denormalized workspace pointer so ``public_id`` is unique PER
    # WORKSPACE (composite constraint below) rather than globally. Each workspace
    # mints its own ``TC-N`` sequence (see :mod:`suitest_db.public_id`), so a
    # global unique made the first case in any 2nd+ workspace collide on ``TC-1``.
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    preconditions: Mapped[str | None] = mapped_column(Text)
    source: Mapped[CaseSource] = mapped_column(
        SAEnum(CaseSource, name="case_source"), nullable=False
    )
    status: Mapped[CaseStatus] = mapped_column(
        SAEnum(CaseStatus, name="case_status"), default=CaseStatus.ACTIVE, nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, name="priority"), default=Priority.P2, nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    generated_by: Mapped[str | None] = mapped_column(String(64))
    generated_from: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    estimated_ms: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # M1d: manual sort key within suite — drives drag-reorder UX (M1d-21/22).
    # Default 0; service layer breaks ties by created_at ASC. The composite
    # `(suite_id, order_in_suite)` index is declared in `__table_args__` below;
    # we deliberately do NOT also emit the auto-named single-column index here
    # (plan-05b explicitly excludes ix_test_cases_order_in_suite).
    order_in_suite: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    suite: Mapped[Suite] = relationship("Suite")
    steps: Mapped[list[TestStep]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="TestStep.order"
    )
    tags: Mapped[list[CaseTag]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("workspace_id", "public_id", name="uq_test_cases_workspace_public_id"),
        Index("ix_test_cases_suite_status", "suite_id", "status"),
        Index("ix_test_cases_source", "source"),
        Index("ix_test_cases_deleted_at", "deleted_at"),
        Index("ix_test_cases_suite_order", "suite_id", "order_in_suite"),
    )


class TestStep(Base):
    __tablename__ = "test_steps"
    __test__ = False  # not a pytest test class

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # NEW — per-step MCP routing
    mcp_provider: Mapped[str] = mapped_column(String(64), default="playwright-mcp", nullable=False)
    target_kind: Mapped[TargetKind] = mapped_column(
        SAEnum(TargetKind, name="target_kind"), default=TargetKind.FE_WEB, nullable=False
    )

    case: Mapped[TestCase] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("case_id", "order", name="uq_test_steps_case_order"),
        Index("ix_test_steps_mcp_provider", "mcp_provider"),
        Index("ix_test_steps_target_kind", "target_kind"),
    )

    # NOTE: `executable` is intentionally NOT a column — it depends on workspace
    # tier at read time. See domain model `TestStep.executable(tier)`.


class CaseTag(Base):
    __tablename__ = "case_tags"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("case_id", "tag", name="uq_case_tags_case_tag"),
        Index("ix_case_tags_tag", "tag"),
    )

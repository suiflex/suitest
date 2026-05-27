"""TestCase repository with filtered keyset listing + step loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.project import Suite
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


class TestCaseCreate(BaseModel):
    __test__ = False  # not a pytest test class (name starts with "Test")

    suite_id: str
    public_id: str
    name: str
    source: CaseSource
    description: str | None = None
    preconditions: str | None = None
    status: CaseStatus = CaseStatus.ACTIVE
    priority: Priority = Priority.P2


class TestCaseUpdate(BaseModel):
    __test__ = False  # not a pytest test class (name starts with "Test")

    name: str | None = None
    description: str | None = None
    preconditions: str | None = None
    status: CaseStatus | None = None
    priority: Priority | None = None


class TestCaseRepo(AsyncRepository[TestCase, TestCaseCreate, TestCaseUpdate]):
    __test__ = False  # not a pytest test class (name starts with "Test")
    model = TestCase

    async def list_by_suite_filtered(
        self,
        suite_id: str,
        *,
        status: CaseStatus | None = None,
        source: CaseSource | None = None,
        priority: Priority | None = None,
        tag: str | None = None,
        q: str | None = None,
        cursor: tuple[datetime, str] | None = None,
        limit: int = 20,
    ) -> tuple[Sequence[TestCase], tuple[datetime, str] | None]:
        stmt = select(TestCase).where(TestCase.suite_id == suite_id, TestCase.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(TestCase.status == status)
        if source is not None:
            stmt = stmt.where(TestCase.source == source)
        if priority is not None:
            stmt = stmt.where(TestCase.priority == priority)
        if tag is not None:
            stmt = stmt.where(TestCase.id.in_(select(CaseTag.case_id).where(CaseTag.tag == tag)))
        if q is not None:
            stmt = stmt.where(TestCase.name.ilike(f"%{q}%"))
        if cursor is not None:
            cursor_ts, cursor_id = cursor
            stmt = stmt.where(
                (TestCase.created_at < cursor_ts)
                | ((TestCase.created_at == cursor_ts) & (TestCase.id < cursor_id))
            )
        stmt = stmt.order_by(TestCase.created_at.desc(), TestCase.id.desc()).limit(limit + 1)

        rows = list((await self.session.scalars(stmt)).all())
        if len(rows) > limit:
            page = rows[:limit]
            last = page[-1]
            next_cursor: tuple[datetime, str] | None = (last.created_at, last.id)
        else:
            page = rows
            next_cursor = None
        return page, next_cursor

    async def get_steps(self, case_id: str) -> Sequence[TestStep]:
        stmt = select(TestStep).where(TestStep.case_id == case_id).order_by(TestStep.order.asc())
        return (await self.session.scalars(stmt)).all()

    async def get_tags(self, case_id: str) -> list[str]:
        """Return a case's tag strings, ordered alphabetically for stable output."""
        stmt = select(CaseTag.tag).where(CaseTag.case_id == case_id).order_by(CaseTag.tag.asc())
        return list((await self.session.scalars(stmt)).all())

    async def list_by_project(self, project_id: str) -> Sequence[TestCase]:
        """All non-deleted cases in a project (via its suites) — for the matrix."""
        stmt = (
            select(TestCase)
            .join(Suite, Suite.id == TestCase.suite_id)
            .where(Suite.project_id == project_id, TestCase.deleted_at.is_(None))
            .order_by(TestCase.public_id.asc())
        )
        return (await self.session.scalars(stmt)).all()

    async def list_with_steps_by_suite(self, suite_id: str) -> Sequence[TestCase]:
        stmt = (
            select(TestCase)
            .where(TestCase.suite_id == suite_id, TestCase.deleted_at.is_(None))
            .options(selectinload(TestCase.steps))
            .order_by(TestCase.created_at.desc(), TestCase.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

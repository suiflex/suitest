"""TestCase repository with filtered keyset listing + step loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.project import Suite
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.base import AsyncRepository
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


class TestCaseCreate(BaseModel):
    __test__ = False  # not a pytest test class (name starts with "Test")

    suite_id: str
    name: str
    source: CaseSource
    # Optional: the ``before_insert`` listener (suitest_db.public_id) fills this
    # from the per-workspace ``TC`` sequence. Callers may still pin a value for
    # seeders / migrations — the listener is idempotent when public_id is set.
    public_id: str | None = None
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

    async def create(  # type: ignore[override]
        self, dto: TestCaseCreate, *, workspace_id: str
    ) -> TestCase:
        """Create a test case, deferring ``public_id`` to the ``before_insert`` listener.

        ``workspace_id`` is required (and stashed as a transient attr on the
        instance) so the listener can pick the right ``pubid_<ws>_TC`` sequence.
        Signature intentionally diverges from :class:`AsyncRepository.create`
        (LSP override) — the base lacks the workspace context this generator
        needs.
        """
        row = TestCase(**dto.model_dump(exclude_unset=True))
        set_workspace_id(row, workspace_id)
        self.session.add(row)
        await self.session.flush()
        return row

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
        include_deleted: bool = False,
    ) -> tuple[Sequence[TestCase], tuple[datetime, str] | None]:
        stmt = select(TestCase).where(TestCase.suite_id == suite_id)
        if not include_deleted:
            stmt = stmt.where(TestCase.deleted_at.is_(None))
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

    # -- M1d-2 step writes -----------------------------------------------------

    async def replace_tags(self, case_id: str, tags: Sequence[str]) -> None:
        """Replace the case's tag set wholesale.

        Deletes every existing :class:`CaseTag` row for ``case_id`` then inserts
        each unique tag in ``tags`` (preserving caller order). The unique
        constraint ``(case_id, tag)`` makes duplicate entries in ``tags`` collapse
        to a single row; we de-duplicate in Python first so a single ``IntegrityError``
        on the second insert does not abort the surrounding transaction.
        """
        await self.session.execute(delete(CaseTag).where(CaseTag.case_id == case_id))
        seen: set[str] = set()
        for tag in tags:
            if tag in seen:
                continue
            seen.add(tag)
            self.session.add(CaseTag(case_id=case_id, tag=tag))
        await self.session.flush()

    async def delete_steps(self, case_id: str) -> None:
        """Delete every :class:`TestStep` row for ``case_id``."""
        await self.session.execute(delete(TestStep).where(TestStep.case_id == case_id))
        await self.session.flush()

    async def add_steps(self, case_id: str, steps: Sequence[TestStep]) -> None:
        """Persist every step in ``steps`` (caller pre-populates ``case_id``, ``order``)."""
        for step in steps:
            step.case_id = case_id
            self.session.add(step)
        await self.session.flush()

    async def next_step_order_locked(self, case_id: str) -> int:
        """Return the next 0-based ``order`` for an append, race-safe.

        Plan-05b specifies ``SELECT MAX(order) FROM test_steps WHERE
        case_id=:cid FOR UPDATE`` — but Postgres rejects ``FOR UPDATE`` on a
        query that uses an aggregate. We achieve the same serialisation by
        locking the parent :class:`TestCase` row (always unique, always
        present) up front, then computing the max in a follow-up read.
        Concurrent appends against the same case block on that row lock; the
        max read inside the second transaction therefore sees the first
        transaction's just-inserted step. Returns ``0`` when no steps exist.
        """
        await self.session.execute(
            select(TestCase.id).where(TestCase.id == case_id).with_for_update()
        )
        stmt = select(func.max(TestStep.order)).where(TestStep.case_id == case_id)
        current_max: int | None = await self.session.scalar(stmt)
        return 0 if current_max is None else current_max + 1

    async def step_ids(self, case_id: str) -> Sequence[str]:
        """Return the ids of every step belonging to ``case_id`` (no order)."""
        stmt = select(TestStep.id).where(TestStep.case_id == case_id)
        return list((await self.session.scalars(stmt)).all())

    async def get_steps_by_ids(self, case_id: str, ids: Sequence[str]) -> Sequence[TestStep]:
        """Return the steps whose ``id`` is in ``ids`` AND who belong to ``case_id``."""
        if not ids:
            return []
        stmt = select(TestStep).where(TestStep.case_id == case_id, TestStep.id.in_(list(ids)))
        return list((await self.session.scalars(stmt)).all())

    # -- M1d-3 soft delete + restore -----------------------------------------

    async def get_by_id_including_deleted(self, case_id: str) -> TestCase | None:
        """Return a case by id without the ``deleted_at IS NULL`` default filter.

        :meth:`AsyncRepository.get_by_id` filters out tombstones; the M1d-3
        restore + idempotency paths need to surface them so the service can
        decide between ``404`` (row never existed) and ``204`` (row currently
        deleted / already active).
        """
        stmt = select(TestCase).where(TestCase.id == case_id)
        row: TestCase | None = await self.session.scalar(stmt)
        return row

    async def mark_deleted(self, case_id: str, *, deleted_at: datetime) -> bool:
        """Set ``deleted_at`` on ``case_id`` if it is currently ``NULL``.

        Returns ``True`` when a row transitioned active -> deleted, ``False``
        when the row was already tombstoned (or does not exist). The caller
        uses the boolean to drive idempotency: a non-transition means a
        re-DELETE that should map to 404 per ``docs/API.md §3.3``.
        """
        case = await self.get_by_id_including_deleted(case_id)
        if case is None or case.deleted_at is not None:
            return False
        case.deleted_at = deleted_at
        await self.session.flush()
        return True

    async def clear_deleted(self, case_id: str) -> bool | None:
        """Clear ``deleted_at`` on ``case_id``.

        Returns ``True`` when a row transitioned deleted -> active, ``False``
        when the row exists but is already active (idempotent re-restore), and
        ``None`` when no such row exists. Callers translate ``None`` to 404 and
        accept either bool as a 204 per ``docs/API.md §3.3``.
        """
        case = await self.get_by_id_including_deleted(case_id)
        if case is None:
            return None
        if case.deleted_at is None:
            return False
        case.deleted_at = None
        await self.session.flush()
        return True

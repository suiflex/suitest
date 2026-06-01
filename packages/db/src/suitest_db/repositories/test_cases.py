"""TestCase repository with filtered keyset listing + step loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.project import Project, Suite
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

    async def get_by_public_id(  # type: ignore[override]  # tenant-scoped: adds required workspace_id vs base
        self, public_id: str, workspace_id: str
    ) -> TestCase | None:
        """Resolve a non-deleted case by its per-workspace public id (``TC-1000``).

        Public ids are unique per workspace, so the lookup is scoped through the
        case's ``suite → project → workspace`` chain. Returns ``None`` when no
        live case matches (caller raises 404). Signature intentionally diverges
        from :class:`AsyncRepository.get_by_public_id` (LSP override) — the base
        lacks the workspace context this scoped lookup needs, mirroring ``create``.
        """
        stmt = (
            select(TestCase)
            .join(Suite, Suite.id == TestCase.suite_id)
            .join(Project, Project.id == Suite.project_id)
            .where(
                TestCase.public_id == public_id,
                Project.workspace_id == workspace_id,
                TestCase.deleted_at.is_(None),
            )
        )
        return (await self.session.scalars(stmt)).first()

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

    # -- M1d-7 bulk update ----------------------------------------------------

    async def list_active_by_ids(self, ids: Sequence[str]) -> Sequence[TestCase]:
        """Return ACTIVE (non-tombstoned) :class:`TestCase` rows matching ``ids``.

        Order is undefined — callers index by id. Empty input → empty result
        without round-tripping the DB.
        """
        if not ids:
            return []
        stmt = select(TestCase).where(TestCase.id.in_(list(ids)), TestCase.deleted_at.is_(None))
        return list((await self.session.scalars(stmt)).all())

    async def workspace_ids_for(self, ids: Sequence[str]) -> dict[str, str]:
        """Return ``{case_id: workspace_id}`` for every case in ``ids``.

        Resolves workspace via ``test_cases -> suites -> projects``. Missing
        ids are omitted from the mapping (caller treats them as 404). Used by
        bulk-update to fail-fast on cross-workspace ids in a single query.
        """
        if not ids:
            return {}
        stmt = (
            select(TestCase.id, Project.workspace_id)
            .join(Suite, Suite.id == TestCase.suite_id)
            .join(Project, Project.id == Suite.project_id)
            .where(TestCase.id.in_(list(ids)))
        )
        rows = (await self.session.execute(stmt)).all()
        return {case_id: ws_id for case_id, ws_id in rows}

    async def suite_workspace_id(self, suite_id: str) -> str | None:
        """Return the workspace id owning ``suite_id`` (or ``None`` when missing).

        Mirrors :meth:`workspace_ids_for` for a single suite; used by the
        ``move_to_suite`` bulk action to validate the target before mutating.
        Filters tombstoned suites — moving cases into a deleted suite is
        disallowed.
        """
        stmt = (
            select(Project.workspace_id)
            .join(Suite, Suite.project_id == Project.id)
            .where(Suite.id == suite_id, Suite.deleted_at.is_(None))
        )
        ws_id: str | None = await self.session.scalar(stmt)
        return ws_id

    async def bulk_soft_delete(self, ids: Sequence[str], *, deleted_at: datetime) -> Sequence[str]:
        """Tombstone every ACTIVE case in ``ids`` in one statement.

        Returns the ids that transitioned (a row already tombstoned is
        skipped). Uses ``UPDATE … WHERE deleted_at IS NULL`` so the operation
        is idempotent at the SQL layer.
        """
        if not ids:
            return []
        stmt = (
            update(TestCase)
            .where(TestCase.id.in_(list(ids)), TestCase.deleted_at.is_(None))
            .values(deleted_at=deleted_at)
            .returning(TestCase.id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_move_to_suite(
        self, ids: Sequence[str], *, target_suite_id: str
    ) -> Sequence[str]:
        """Re-parent every ACTIVE case in ``ids`` to ``target_suite_id``.

        Returns the ids actually moved (skipping rows already in the target
        or tombstoned). ``order_in_suite`` is reset to ``0`` per plan-05b
        Task M1d-7 ("resets order in suite") so the moved cases land at the
        top of the new suite's order — FE can re-rank afterwards via the
        normal drag-reorder flow.
        """
        if not ids:
            return []
        stmt = (
            update(TestCase)
            .where(TestCase.id.in_(list(ids)), TestCase.deleted_at.is_(None))
            .values(suite_id=target_suite_id, order_in_suite=0)
            .returning(TestCase.id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_set_priority(self, ids: Sequence[str], *, priority: Priority) -> Sequence[str]:
        """Set ``priority`` on every ACTIVE case in ``ids``.

        Returns the affected ids. Uses a single ``UPDATE`` so the audit
        listener sees the whole batch within one flush.
        """
        if not ids:
            return []
        stmt = (
            update(TestCase)
            .where(TestCase.id.in_(list(ids)), TestCase.deleted_at.is_(None))
            .values(priority=priority)
            .returning(TestCase.id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_add_tags(self, ids: Sequence[str], *, tags: Sequence[str]) -> Sequence[str]:
        """Add ``tags`` to every case in ``ids`` (dedupe via the unique constraint).

        Returns the ids that received at least one new tag. A tag already
        present on the case is skipped (no duplicate :class:`CaseTag` row).
        ``tags`` itself is deduplicated in Python first so we never issue a
        within-batch dupe.
        """
        if not ids or not tags:
            return []
        # Existing tag set per case (load once vs. N queries).
        existing_stmt = select(CaseTag.case_id, CaseTag.tag).where(CaseTag.case_id.in_(list(ids)))
        existing: dict[str, set[str]] = {}
        for case_id, tag in (await self.session.execute(existing_stmt)).all():
            existing.setdefault(case_id, set()).add(tag)

        # Dedupe input tags, preserving the caller's order for reproducibility.
        seen: set[str] = set()
        unique_tags: list[str] = []
        for tag in tags:
            if tag in seen:
                continue
            seen.add(tag)
            unique_tags.append(tag)

        affected: set[str] = set()
        for case_id in ids:
            had = existing.get(case_id, set())
            for tag in unique_tags:
                if tag in had:
                    continue
                self.session.add(CaseTag(case_id=case_id, tag=tag))
                affected.add(case_id)
        if affected:
            await self.session.flush()
        return list(affected)

    async def bulk_remove_tags(self, ids: Sequence[str], *, tags: Sequence[str]) -> Sequence[str]:
        """Remove ``tags`` from every case in ``ids``.

        Returns the ids that had at least one matching tag removed. Tags
        absent from a case are a silent no-op for that case (per plan-05b
        ``test_bulk_remove_tags_no_op_if_tag_absent``).
        """
        if not ids or not tags:
            return []
        existing_stmt = select(CaseTag.case_id).where(
            CaseTag.case_id.in_(list(ids)), CaseTag.tag.in_(list(tags))
        )
        affected = list(set((await self.session.scalars(existing_stmt)).all()))
        del_stmt = delete(CaseTag).where(
            CaseTag.case_id.in_(list(ids)), CaseTag.tag.in_(list(tags))
        )
        await self.session.execute(del_stmt)
        await self.session.flush()
        return affected

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

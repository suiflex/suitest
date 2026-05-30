"""Suite repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel
from sqlalchemy import func, select, update
from suitest_db.models.case import TestCase
from suitest_db.models.project import Suite
from suitest_db.models.requirement import RequirementLink
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class SuiteCreate(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    order: int = 0


class SuiteUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    order: int | None = None


class SuiteRepo(AsyncRepository[Suite, SuiteCreate, SuiteUpdate]):
    model = Suite

    async def list_by_project(self, project_id: str) -> Sequence[Suite]:
        """List active (non-deleted) suites in a project.

        The ``deleted_at IS NULL`` predicate maps to the partial index
        ``ix_suites_project_active`` (M1d-1 migration) — verified inside
        ``test_list_suites_excludes_deleted``.
        """
        stmt = (
            select(Suite)
            .where(Suite.project_id == project_id, Suite.deleted_at.is_(None))
            .order_by(Suite.order.asc(), Suite.created_at.desc(), Suite.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def get_active_by_id(self, suite_id: str) -> Suite | None:
        """Return a non-deleted suite or ``None``.

        Callers that need to operate on tombstoned rows (e.g. ``restore``) use
        :meth:`get_by_id` from the base repo and inspect ``deleted_at`` themselves.
        """
        stmt = select(Suite).where(Suite.id == suite_id, Suite.deleted_at.is_(None))
        result: Suite | None = await self.session.scalar(stmt)
        return result

    async def case_counts(self, suite_ids: Sequence[str]) -> dict[str, int]:
        """Map each suite id → its count of non-deleted cases (one grouped query).

        Returns 0 for suites with no cases (callers default-fill missing keys).
        """
        if not suite_ids:
            return {}
        stmt = (
            select(TestCase.suite_id, func.count(TestCase.id))
            .where(TestCase.suite_id.in_(suite_ids), TestCase.deleted_at.is_(None))
            .group_by(TestCase.suite_id)
        )
        counts: dict[str, int] = {}
        for suite_id, count in (await self.session.execute(stmt)).all():
            counts[suite_id] = count
        return counts

    async def covered_case_counts(self, suite_ids: Sequence[str]) -> dict[str, int]:
        """Map suite id → count of its cases linked to at least one requirement.

        A case is "covered" when a ``RequirementLink`` references it; we count
        distinct linked cases per suite (one grouped query).
        """
        if not suite_ids:
            return {}
        stmt = (
            select(TestCase.suite_id, func.count(func.distinct(TestCase.id)))
            .join(RequirementLink, RequirementLink.case_id == TestCase.id)
            .where(TestCase.suite_id.in_(suite_ids), TestCase.deleted_at.is_(None))
            .group_by(TestCase.suite_id)
        )
        counts: dict[str, int] = {}
        for suite_id, count in (await self.session.execute(stmt)).all():
            counts[suite_id] = count
        return counts

    # ------------------------------------------------------------------
    # M1d-4 write helpers
    # ------------------------------------------------------------------

    async def active_case_ids_in_order(self, suite_id: str) -> list[str]:
        """Return ids of non-deleted cases in ``suite_id`` ordered by current rank.

        Used by the reorder validator and the ``case_order`` audit payload.
        Order is ``(order_in_suite ASC, created_at ASC, id ASC)`` so a freshly
        seeded suite (where every order_in_suite=0) yields a deterministic
        sequence the service can diff against ``case_order`` submissions.
        """
        stmt = (
            select(TestCase.id)
            .where(TestCase.suite_id == suite_id, TestCase.deleted_at.is_(None))
            .order_by(
                TestCase.order_in_suite.asc(),
                TestCase.created_at.asc(),
                TestCase.id.asc(),
            )
        )
        return list((await self.session.scalars(stmt)).all())

    async def reorder_active_cases(self, suite_id: str, ordered_case_ids: Sequence[str]) -> None:
        """Rewrite ``order_in_suite`` for every active case in the suite atomically.

        Caller must have already verified the submitted set matches the live
        set (via :meth:`active_case_ids_in_order`); this helper trusts the
        input. Single transaction — one ``UPDATE`` per case keyed on the
        ``(suite_id, id)`` pair so a foreign id silently no-ops rather than
        bleeding into another suite.

        The plan-05b ``UPDATE … FROM unnest(...)`` pattern is equivalent to
        this loop for the M1d-4 row counts (single-digit cases per suite in
        the typical TCM workflow). We keep the loop because SQLAlchemy 2's
        async API does not expose a portable ``unnest(text[], int[])`` form
        without resorting to raw SQL — and raw SQL is forbidden by CLAUDE
        §2.2 outside performance-critical hot paths.
        """
        for new_rank, case_id in enumerate(ordered_case_ids):
            await self.session.execute(
                update(TestCase)
                .where(
                    TestCase.id == case_id,
                    TestCase.suite_id == suite_id,
                    TestCase.deleted_at.is_(None),
                )
                .values(order_in_suite=new_rank)
            )
        await self.session.flush()

    async def count_active_children(self, suite_id: str) -> int:
        """Count of non-deleted test cases in ``suite_id`` (cascade pre-check)."""
        stmt = select(func.count(TestCase.id)).where(
            TestCase.suite_id == suite_id, TestCase.deleted_at.is_(None)
        )
        result: int | None = await self.session.scalar(stmt)
        return result or 0

    async def soft_delete_with_cascade(
        self,
        suite_id: str,
        *,
        deleted_at: datetime | None = None,
    ) -> tuple[bool, list[str]]:
        """Mark suite + every active child case as soft-deleted.

        Returns ``(suite_touched, cascaded_case_ids)`` so callers can build
        the audit payload + WS event. ``suite_touched`` is False if the suite
        is already tombstoned — keeps the operation idempotent at the repo
        level (the router maps "already deleted" to a 404 separately).
        Uses bulk ``UPDATE`` statements so two writes (suite + cases) — not
        ``len(cases) + 1`` — land per call.
        """
        stamp = deleted_at or datetime.now(tz=UTC)

        # Capture the cascaded set BEFORE the bulk update so we can audit
        # / emit them in the response. Ordered by ``id`` ASC for a stable
        # cascade payload across test runs.
        cascaded = list(
            (
                await self.session.scalars(
                    select(TestCase.id)
                    .where(
                        TestCase.suite_id == suite_id,
                        TestCase.deleted_at.is_(None),
                    )
                    .order_by(TestCase.id.asc())
                )
            ).all()
        )

        suite_result = await self.session.execute(
            update(Suite)
            .where(Suite.id == suite_id, Suite.deleted_at.is_(None))
            .values(deleted_at=stamp)
        )
        # ``rowcount`` lives on ``CursorResult`` (returned by UPDATE/DELETE).
        # The static type for ``execute`` is the base ``Result`` Protocol so
        # mypy strict needs a cast to surface the attribute.
        suite_touched = cast("int", getattr(suite_result, "rowcount", 0) or 0) > 0

        if suite_touched and cascaded:
            await self.session.execute(
                update(TestCase)
                .where(
                    TestCase.suite_id == suite_id,
                    TestCase.deleted_at.is_(None),
                )
                .values(deleted_at=stamp)
            )
        await self.session.flush()
        return suite_touched, cascaded

    async def restore(self, suite_id: str) -> bool:
        """Clear ``deleted_at`` on the suite — children stay tombstoned.

        Returns ``True`` when a row transitioned from deleted -> active;
        ``False`` when the suite either does not exist or was never deleted.
        The router maps a missing transition to a 404 to keep the contract
        idempotent (re-POST after a successful restore also returns 204).
        Per docs/API.md §328 the cascade is one-way: child cases must be
        restored individually via ``POST /test-cases/:id/restore``.
        """
        result = await self.session.execute(
            update(Suite)
            .where(Suite.id == suite_id, Suite.deleted_at.is_not(None))
            .values(deleted_at=None)
        )
        await self.session.flush()
        return cast("int", getattr(result, "rowcount", 0) or 0) > 0

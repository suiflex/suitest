"""Suite repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import func, select
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
        stmt = (
            select(Suite)
            .where(Suite.project_id == project_id)
            .order_by(Suite.order.asc(), Suite.created_at.desc(), Suite.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

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

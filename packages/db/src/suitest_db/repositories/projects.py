"""Project repository (workspace-scoped via per-method ``workspace_id``)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel
from sqlalchemy import select, update
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_db.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from collections.abc import Sequence


class ProjectCreate(BaseModel):
    workspace_id: str
    slug: str
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    gating_suite_id: str | None = None
    default_mcp_routing: dict[str, Any] | None = None


class ProjectRepo(AsyncRepository[Project, ProjectCreate, ProjectUpdate]):
    model = Project

    async def list_by_workspace(self, workspace_id: str) -> Sequence[Project]:
        """List active (non-deleted) projects in a workspace.

        The ``deleted_at IS NULL`` predicate maps to the partial index
        ``ix_projects_workspace_active`` (M1d-5 migration).
        """
        stmt = (
            select(Project)
            .where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
            .order_by(Project.created_at.desc(), Project.id.desc())
        )
        return (await self.session.scalars(stmt)).all()

    async def list_by_workspace_paginated(
        self,
        workspace_id: str,
        *,
        cursor: tuple[datetime, str] | None = None,
        limit: int = 20,
    ) -> tuple[Sequence[Project], tuple[datetime, str] | None]:
        """Keyset page of active projects in a workspace (newest-first, id tiebreak)."""
        return await self.list_paginated(
            cursor=cursor,
            limit=limit,
            filters={"workspace_id": workspace_id, "deleted_at": None},
        )

    async def get_by_slug(self, workspace_id: str, slug: str) -> Project | None:
        """Return any project (active or tombstoned) with the given slug.

        Slug uniqueness is enforced at the ``UniqueConstraint`` level — soft-
        deleted rows still occupy the slug until hard-purge.
        """
        stmt = select(Project).where(Project.workspace_id == workspace_id, Project.slug == slug)
        result: Project | None = await self.session.scalar(stmt)
        return result

    async def get_active_by_id(self, project_id: str) -> Project | None:
        """Return a non-deleted project or ``None``.

        Callers that need to operate on tombstoned rows (e.g. ``restore``) use
        :meth:`get_by_id` from the base repo and inspect ``deleted_at`` themselves.
        """
        stmt = select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        result: Project | None = await self.session.scalar(stmt)
        return result

    # ------------------------------------------------------------------
    # M1d-5 write helpers
    # ------------------------------------------------------------------

    async def count_active_suites(self, project_id: str) -> int:
        """Count of non-deleted suites in ``project_id`` (cascade pre-check)."""
        from sqlalchemy import func

        stmt = select(func.count(Suite.id)).where(
            Suite.project_id == project_id, Suite.deleted_at.is_(None)
        )
        result: int | None = await self.session.scalar(stmt)
        return result or 0

    async def count_active_cases(self, project_id: str) -> int:
        """Count of non-deleted cases in ``project_id`` (via its active suites)."""
        from sqlalchemy import func

        stmt = (
            select(func.count(TestCase.id))
            .join(Suite, Suite.id == TestCase.suite_id)
            .where(Suite.project_id == project_id, TestCase.deleted_at.is_(None))
        )
        result: int | None = await self.session.scalar(stmt)
        return result or 0

    async def soft_delete_with_cascade(
        self,
        project_id: str,
        *,
        deleted_at: datetime | None = None,
    ) -> tuple[bool, list[str], list[str]]:
        """Mark project + every active child suite + child case as soft-deleted.

        Returns ``(project_touched, cascaded_suite_ids, cascaded_case_ids)`` so
        callers can build the audit payload + WS event. ``project_touched`` is
        False if the project is already tombstoned — keeps the operation
        idempotent at the repo level. Uses bulk ``UPDATE`` statements so three
        writes (project + suites + cases) — not ``len(children) + 1`` — land
        per call.
        """
        stamp = deleted_at or datetime.now(tz=UTC)

        # Capture the cascaded sets BEFORE the bulk update so we can audit /
        # emit them in the response. Ordered by ``id`` ASC for a stable
        # cascade payload across test runs.
        cascaded_suites = list(
            (
                await self.session.scalars(
                    select(Suite.id)
                    .where(Suite.project_id == project_id, Suite.deleted_at.is_(None))
                    .order_by(Suite.id.asc())
                )
            ).all()
        )
        cascaded_cases = list(
            (
                await self.session.scalars(
                    select(TestCase.id)
                    .join(Suite, Suite.id == TestCase.suite_id)
                    .where(Suite.project_id == project_id, TestCase.deleted_at.is_(None))
                    .order_by(TestCase.id.asc())
                )
            ).all()
        )

        project_result = await self.session.execute(
            update(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .values(deleted_at=stamp)
        )
        project_touched = cast("int", getattr(project_result, "rowcount", 0) or 0) > 0

        if project_touched and cascaded_suites:
            await self.session.execute(
                update(Suite)
                .where(Suite.project_id == project_id, Suite.deleted_at.is_(None))
                .values(deleted_at=stamp)
            )
        if project_touched and cascaded_cases:
            await self.session.execute(
                update(TestCase).where(TestCase.id.in_(cascaded_cases)).values(deleted_at=stamp)
            )
        await self.session.flush()
        return project_touched, cascaded_suites, cascaded_cases

    async def restore(self, project_id: str) -> bool:
        """Clear ``deleted_at`` on the project — children stay tombstoned.

        Returns ``True`` when the row transitioned from deleted -> active;
        ``False`` when the project either does not exist or was never deleted.
        The cascade is one-way: child suites + cases must be restored
        individually.
        """
        result = await self.session.execute(
            update(Project)
            .where(Project.id == project_id, Project.deleted_at.is_not(None))
            .values(deleted_at=None)
        )
        await self.session.flush()
        return cast("int", getattr(result, "rowcount", 0) or 0) > 0

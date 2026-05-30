"""ProjectService — workspace-scoped CRUD reads + M1d-5 writes.

Write path (M1d-5): ``create`` (slug autogen + collision retry),
``update`` (metadata patch with immutable-slug guard + gating-suite
validation), ``soft_delete_with_cascade`` (cascade tombstones suites +
cases in a single transaction), ``restore`` (clears the project tombstone;
children stay tombstoned).

Each write method opens a single transaction owned by the caller (router
commits), calls the repo, writes audit, and stamps the WS event helper the
router fires after the commit so subscribers never see a phantom event for
a rolled-back write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from sqlalchemy.exc import IntegrityError
from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.models.project import Project
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_shared.schemas.responses import ProjectOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier
from suitest_api.utils.slug import slugify

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from suitest_api.schemas.project import ProjectCreate, ProjectUpdate


class SlugConflictError(Exception):
    """Raised when the (workspace_id, slug) pair is already taken.

    The router translates this into a 409 ``DUPLICATE_PROJECT_SLUG`` with
    the offending ``slug`` in ``details``.
    """

    def __init__(self, slug: str) -> None:
        super().__init__(f"project slug {slug!r} already in use in this workspace")
        self.slug = slug


class ImmutableSlugError(Exception):
    """Raised when PATCH /projects/:id includes a ``slug`` field.

    Per docs/API.md §3.2, the slug is fixed at create time so external links
    (CI badges, requirement traceability matrices) stay valid. Renaming the
    project itself is allowed via the ``name`` field.
    """

    def __init__(self) -> None:
        super().__init__("project slug is immutable; create a new project to rename it")


class InvalidGatingSuiteError(Exception):
    """Raised when ``gating_suite_id`` does not belong to the target project.

    The router translates this into a 400 ``INVALID_GATING_SUITE`` with the
    offending ``suiteId`` + the expected ``projectId`` in ``details``.
    """

    def __init__(self, *, suite_id: str, project_id: str) -> None:
        super().__init__(f"suite {suite_id!r} does not belong to project {project_id!r}")
        self.suite_id = suite_id
        self.project_id = project_id


class ConfirmCascadeRequiredError(Exception):
    """Raised when a DELETE lacks ``confirmCascade=true`` and the project has children.

    The router translates this into a 409 ``CONFIRM_CASCADE_REQUIRED`` with
    ``details.suiteCount`` / ``details.caseCount`` / ``details.resourceType=
    "project"`` per the M1d error matrix.
    """

    def __init__(self, *, suite_count: int, case_count: int) -> None:
        super().__init__("delete requires confirmCascade=true — project has child resources")
        self.suite_count = suite_count
        self.case_count = case_count


class ProjectWriteResult(NamedTuple):
    """Outcome bundle: read DTO + the WS event the router should emit.

    Keeping the WS event out-of-band (vs. having the service publish directly)
    lets the router wait for the transaction to commit before broadcasting —
    subscribers never observe a phantom event for a rolled-back write.
    """

    project: ProjectOut
    ws_event: str
    ws_payload: dict[str, object]


# Maximum collision-retry attempts when autogenerating a slug. The repo's
# ``UniqueConstraint`` retries one suffix (-2) before bubbling; raising the
# cap higher just defers the eventual 409 envelope the FE has to render.
_SLUG_RETRY_SUFFIX = "-2"


class ProjectService:
    def __init__(self, ctx: TenantContext, repo: ProjectRepo) -> None:
        self._ctx = ctx
        self._repo = repo

    @property
    def _session(self) -> AsyncSession:
        return self._repo.session

    @require_tier(TierFlag.ANY)
    async def list(self) -> list[ProjectOut]:
        rows = await self._repo.list_by_workspace(self._ctx.workspace_id)
        return [ProjectOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id(self, project_id: str) -> ProjectOut | None:
        row = await self._repo.get_active_by_id(project_id)
        if row is None or row.workspace_id != self._ctx.workspace_id:
            return None
        return ProjectOut.model_validate(row)

    # ------------------------------------------------------------------
    # Write path (M1d-5)
    # ------------------------------------------------------------------

    async def _next_slug(self, requested: str | None, *, name: str) -> str:
        """Pick the slug to write.

        * Explicit ``requested`` wins (caller controls collision handling).
        * Otherwise derive from ``name`` via :func:`slugify`. If the derived
          slug is taken, try ``<slug>-2`` once before letting the caller see
          a 409. We keep the retry cap at one suffix to avoid pathological
          suffix walks under load — see plan-05b § Task M1d-5 implementation.
        """
        if requested is not None and requested.strip():
            return requested.strip()
        base = slugify(name)
        existing = await self._repo.get_by_slug(self._ctx.workspace_id, base)
        if existing is None:
            return base
        candidate = base + _SLUG_RETRY_SUFFIX
        # 64 is the column width; trim back if the suffix overflows.
        if len(candidate) > 64:
            candidate = base[: 64 - len(_SLUG_RETRY_SUFFIX)] + _SLUG_RETRY_SUFFIX
        return candidate

    @require_tier(TierFlag.ANY)
    async def create(self, body: ProjectCreate) -> ProjectWriteResult:
        """Create a project under the active workspace.

        Slug autogen: if the body omits ``slug`` we derive from ``name`` and
        retry once with a ``-2`` suffix on collision. A second collision
        bubbles as :class:`SlugConflictError` so the router can build the
        canonical 409 ``DUPLICATE_PROJECT_SLUG`` envelope.
        """
        slug = await self._next_slug(body.slug, name=body.name)
        project = Project(
            workspace_id=self._ctx.workspace_id,
            slug=slug,
            name=body.name,
            description=body.description,
        )
        self._session.add(project)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Bubble as a typed error so the router maps to 409 — but only
            # if the failure is the slug uniqueness constraint. Re-raise on
            # any other integrity failure (e.g. workspace FK violation).
            await self._session.rollback()
            if "uq_projects_workspace_slug" in str(exc.orig):
                raise SlugConflictError(slug) from exc
            raise

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="project.created",
            resource_type="project",
            resource_id=project.id,
            metadata={"slug": project.slug, "name": project.name},
        )
        return ProjectWriteResult(
            project=ProjectOut.model_validate(project),
            ws_event="project.created",
            ws_payload={
                "projectId": project.id,
                "slug": project.slug,
                "name": project.name,
            },
        )

    async def _load_active_in_scope(self, project_id: str) -> Project | None:
        """Return an active project owned by the active workspace, else ``None``."""
        project = await self._repo.get_active_by_id(project_id)
        if project is None or project.workspace_id != self._ctx.workspace_id:
            return None
        return project

    async def _validate_gating_suite(self, project_id: str, suite_id: str) -> None:
        """Raise :class:`InvalidGatingSuiteError` if ``suite_id`` is foreign.

        The gating suite must exist AND live under ``project_id``. Cross-
        project assignments would let a webhook gate against another team's
        suite — the FE picker already filters by project, but the API guard
        is the source-of-truth check.
        """
        suite_repo = SuiteRepo(self._session)
        suite = await suite_repo.get_by_id(suite_id)
        if suite is None or suite.project_id != project_id:
            raise InvalidGatingSuiteError(suite_id=suite_id, project_id=project_id)

    @require_tier(TierFlag.ANY)
    async def update(self, project_id: str, body: ProjectUpdate) -> ProjectWriteResult | None:
        """Patch metadata; ``gating_suite_id`` validated to be in-project.

        Returns ``None`` for a non-existent / cross-workspace project (router
        maps to 404). Raises :class:`ImmutableSlugError` when the payload
        carries a ``slug`` field — the slug is fixed at create time.
        """
        payload = body.model_dump(exclude_unset=True, by_alias=False)
        if "slug" in payload and payload["slug"] is not None:
            raise ImmutableSlugError

        project = await self._load_active_in_scope(project_id)
        if project is None:
            return None

        changed_fields: list[str] = []
        gating_changed = False
        if "name" in payload and payload["name"] is not None:
            project.name = payload["name"]
            changed_fields.append("name")
        if "description" in payload:
            project.description = payload["description"]
            changed_fields.append("description")
        if "default_mcp_routing" in payload and payload["default_mcp_routing"] is not None:
            routing: dict[str, Any] = payload["default_mcp_routing"]
            project.default_mcp_routing = routing
            changed_fields.append("default_mcp_routing")
        if "gating_suite_id" in payload:
            new_suite_id = payload["gating_suite_id"]
            if new_suite_id is not None:
                await self._validate_gating_suite(project.id, new_suite_id)
            project.gating_suite_id = new_suite_id
            changed_fields.append("gating_suite_id")
            gating_changed = True

        await self._session.flush()

        if changed_fields:
            await write_audit(
                self._session,
                workspace_id=self._ctx.workspace_id,
                user_id=self._ctx.user_id,
                action="project.updated",
                resource_type="project",
                resource_id=project.id,
                metadata={"fields": changed_fields},
            )
        if gating_changed:
            await write_audit(
                self._session,
                workspace_id=self._ctx.workspace_id,
                user_id=self._ctx.user_id,
                action="project.gating_suite_changed",
                resource_type="project",
                resource_id=project.id,
                metadata={"suiteId": project.gating_suite_id},
            )
        return ProjectWriteResult(
            project=ProjectOut.model_validate(project),
            ws_event="project.updated",
            ws_payload={
                "projectId": project.id,
                "fields": changed_fields,
            },
        )

    @require_tier(TierFlag.ANY)
    async def soft_delete_with_cascade(
        self, project_id: str, *, confirm_cascade: bool
    ) -> ProjectWriteResult | None:
        """Soft-delete the project (+ cascade child suites + cases when confirmed).

        Cascade pre-check runs against the live count of active children;
        if ``confirm_cascade`` is False AND the suite_count is > 0,
        :class:`ConfirmCascadeRequiredError` raises with ``suite_count`` +
        ``case_count`` so the router can build the canonical envelope.
        Empty projects (zero active suites) soft-delete immediately.
        """
        project = await self._load_active_in_scope(project_id)
        if project is None:
            return None

        suite_count = await self._repo.count_active_suites(project.id)
        case_count = await self._repo.count_active_cases(project.id)
        if suite_count > 0 and not confirm_cascade:
            raise ConfirmCascadeRequiredError(suite_count=suite_count, case_count=case_count)

        (
            project_touched,
            cascaded_suites,
            cascaded_cases,
        ) = await self._repo.soft_delete_with_cascade(project.id)
        if not project_touched:
            # Race: another writer tombstoned between the active-project load
            # and the bulk UPDATE. Treat as not-found so the router emits 404
            # (idempotent).
            return None

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="project.soft_deleted_with_cascade",
            resource_type="project",
            resource_id=project.id,
            metadata={
                "cascadedSuiteIds": cascaded_suites,
                "cascadedCaseIds": cascaded_cases,
                "suiteCount": len(cascaded_suites),
                "caseCount": len(cascaded_cases),
            },
        )
        await self._session.refresh(project)
        return ProjectWriteResult(
            project=ProjectOut.model_validate(project),
            ws_event="project.deleted",
            ws_payload={
                "projectId": project.id,
                "cascadedSuiteIds": cascaded_suites,
                "cascadedCaseIds": cascaded_cases,
            },
        )

    @require_tier(TierFlag.ANY)
    async def restore(self, project_id: str) -> ProjectWriteResult | None:
        """Clear ``deleted_at`` on the project (children stay tombstoned).

        Returns ``None`` for a non-existent project or a project in another
        workspace (router maps to 404). Children stay tombstoned per
        ``docs/API.md §3.2`` — restore each individually via
        ``POST /suites/:id/restore`` / ``POST /test-cases/:id/restore``.
        """
        project = await self._repo.get_by_id(project_id)
        if project is None or project.workspace_id != self._ctx.workspace_id:
            return None

        was_deleted = project.deleted_at is not None
        if was_deleted:
            await self._repo.restore(project.id)
            await write_audit(
                self._session,
                workspace_id=self._ctx.workspace_id,
                user_id=self._ctx.user_id,
                action="project.restored",
                resource_type="project",
                resource_id=project.id,
                metadata={"slug": project.slug},
            )
        await self._session.refresh(project)
        return ProjectWriteResult(
            project=ProjectOut.model_validate(project),
            ws_event="project.restored",
            ws_payload={
                "projectId": project.id,
                "slug": project.slug,
            },
        )

    # M1d-5 cascaded delete check helper for the router cascade gate (router
    # may want suite/case counts in the 409 envelope without re-querying).
    async def cascade_counts(self, project_id: str) -> tuple[int, int] | None:
        """Return ``(suite_count, case_count)`` for the active project, or ``None``.

        Used by the router to build the ``CONFIRM_CASCADE_REQUIRED`` envelope
        without re-loading the project. Returns ``None`` when the project is
        cross-workspace or tombstoned.
        """
        project = await self._load_active_in_scope(project_id)
        if project is None:
            return None
        return (
            await self._repo.count_active_suites(project.id),
            await self._repo.count_active_cases(project.id),
        )

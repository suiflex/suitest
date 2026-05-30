"""RequirementWriteService — M1d-6 requirement + link CRUD.

Implements the mutation surface declared in plan-05b § M1d-6:

* ``POST /requirements`` — create a requirement with a ``REQ-N`` public id via
  the ``before_insert`` listener (driven by ``set_workspace_id``).
* ``PATCH /requirements/:id`` — metadata patch (title / description / source /
  external_url).
* ``DELETE /requirements/:id`` — soft-delete (``deleted_at`` tombstone) with
  idempotent re-delete returning 404 (the row is already invisible).
* ``POST /requirements/:id/restore`` — clear the tombstone; idempotent on an
  already-active row (returns 204 without bumping ``updated_at``).
* ``POST /requirements/:id/links`` — link a requirement to a test case. Both
  must live in the same workspace; otherwise the service raises
  :class:`CrossWorkspaceLinkError` which the router maps to a 400
  ``CROSS_WORKSPACE_LINK`` envelope.
* ``DELETE /requirements/:id/links/:case_id`` — remove a link; 404 when the
  join row no longer exists.

All write paths emit an explicit audit row via :func:`write_audit` plus a typed
WS event helper. The router owns the transaction commit so subscribers cannot
observe a phantom event for a rolled-back write.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.requirements import (
    RequirementRepo,
)
from suitest_db.repositories.requirements import (
    RequirementUpdate as RepoRequirementUpdate,
)
from suitest_db.repositories.test_cases import TestCaseRepo

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.requirement import Requirement, RequirementLink
    from suitest_db.repositories.projects import ProjectRepo

    from suitest_api.schemas.requirement import (
        RequirementCreate as SchemaRequirementCreate,
    )
    from suitest_api.schemas.requirement import (
        RequirementUpdate as SchemaRequirementUpdate,
    )


class CrossWorkspaceLinkError(Exception):
    """Raised when a ``POST /requirements/:id/links`` spans two workspaces.

    Router translates to ``400 CROSS_WORKSPACE_LINK`` with both workspace ids
    in ``details`` (docs/API.md §1 error table). 400 (not 403) because the
    target case existence is observable via the public id namespace.
    """

    def __init__(self, *, requirement_id: str, case_id: str, req_ws: str, case_ws: str) -> None:
        super().__init__("requirement and case belong to different workspaces")
        self.requirement_id = requirement_id
        self.case_id = case_id
        self.requirement_workspace_id = req_ws
        self.case_workspace_id = case_ws


class RequirementWriteResult(NamedTuple):
    """Outcome bundle: the persisted row + the WS event the router emits.

    Keeping the WS event out-of-band (vs. having the service publish directly)
    lets the router wait for the commit before broadcasting — subscribers never
    observe a phantom event for a rolled-back transaction.
    """

    requirement: Requirement
    ws_event: str
    ws_payload: dict[str, object]


class RequirementLinkResult(NamedTuple):
    """Outcome bundle for a link create."""

    link: RequirementLink
    ws_event: str
    ws_payload: dict[str, object]


class RequirementWriteService:
    """All M1d-6 write logic. Read paths stay on the existing read router."""

    def __init__(
        self,
        ctx: TenantContext,
        repo: RequirementRepo,
        project_repo: ProjectRepo,
        case_repo: TestCaseRepo,
    ) -> None:
        self._ctx = ctx
        self._repo = repo
        self._project_repo = project_repo
        self._case_repo = case_repo

    @property
    def _session(self) -> AsyncSession:
        return self._repo.session

    # ------------------------------------------------------------------
    # Scope guards
    # ------------------------------------------------------------------

    async def _project_in_scope(self, project_id: str) -> bool:
        project = await self._project_repo.get_by_id(project_id)
        return project is not None and project.workspace_id == self._ctx.workspace_id

    async def _load_in_scope(self, req_id: str) -> Requirement | None:
        """Load a requirement only when its project lives in the current workspace.

        ``None`` covers both the cross-workspace 404 case and the soft-deleted
        row case — the router cannot tell them apart on purpose (no enumeration
        oracle for deleted ids).
        """
        row = await self._repo.get_by_id(req_id)
        if row is None or not await self._project_in_scope(row.project_id):
            return None
        if row.deleted_at is not None:
            return None
        return row

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def create(self, body: SchemaRequirementCreate) -> RequirementWriteResult | None:
        """Create a requirement + assign a ``REQ-N`` public id via the listener."""
        if not await self._project_in_scope(body.project_id):
            return None

        from suitest_db.models.requirement import Requirement as ReqModel

        row = ReqModel(
            project_id=body.project_id,
            title=body.title,
            description=body.description,
            source=body.source,
            external_url=body.external_url,
        )
        set_workspace_id(row, self._ctx.workspace_id)
        self._session.add(row)
        await self._session.flush()

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="requirement.created",
            resource_type="requirement",
            resource_id=row.id,
            metadata={"publicId": row.public_id, "projectId": row.project_id},
        )
        return RequirementWriteResult(
            requirement=row,
            ws_event="requirement.created",
            ws_payload={
                "requirementId": row.id,
                "publicId": row.public_id,
                "projectId": row.project_id,
                "by": self._ctx.user_id,
            },
        )

    @require_tier(TierFlag.ANY)
    async def update(
        self, req_id: str, body: SchemaRequirementUpdate
    ) -> RequirementWriteResult | None:
        """Patch metadata; only ``model_dump(exclude_unset=True)`` keys apply."""
        if await self._load_in_scope(req_id) is None:
            return None

        repo_dto = RepoRequirementUpdate(**body.model_dump(exclude_unset=True))
        updated = await self._repo.update_metadata(req_id, repo_dto)
        if updated is None:
            return None
        changed_fields = sorted(body.model_dump(exclude_unset=True).keys())

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="requirement.updated",
            resource_type="requirement",
            resource_id=updated.id,
            metadata={"publicId": updated.public_id, "fields": changed_fields},
        )
        return RequirementWriteResult(
            requirement=updated,
            ws_event="requirement.updated",
            ws_payload={
                "requirementId": updated.id,
                "publicId": updated.public_id,
                "fields": changed_fields,
            },
        )

    @require_tier(TierFlag.ANY)
    async def soft_delete(self, req_id: str) -> RequirementWriteResult | None:
        """Set ``deleted_at``; idempotent re-delete returns ``None`` (router → 404)."""
        row = await self._load_in_scope(req_id)
        if row is None:
            return None
        ok = await self._repo.mark_deleted(req_id)
        if not ok:
            return None

        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="requirement.soft_deleted",
            resource_type="requirement",
            resource_id=row.id,
            metadata={"publicId": row.public_id},
        )
        return RequirementWriteResult(
            requirement=row,
            ws_event="requirement.deleted",
            ws_payload={"requirementId": row.id, "publicId": row.public_id},
        )

    @require_tier(TierFlag.ANY)
    async def restore(self, req_id: str) -> RequirementWriteResult | None:
        """Clear ``deleted_at``; idempotent on an already-active row.

        Returns the requirement on success; ``None`` when the row never existed
        or lives in another workspace (router → 404 either way).
        """
        # Bypass ``_load_in_scope`` which hides soft-deleted rows; we need to
        # find the tombstoned row to restore it. Re-check workspace scope.
        row = await self._repo.get_by_id(req_id)
        if row is None or not await self._project_in_scope(row.project_id):
            return None
        was_deleted = row.deleted_at is not None
        await self._repo.clear_deleted(req_id)

        if was_deleted:
            await write_audit(
                self._session,
                workspace_id=self._ctx.workspace_id,
                user_id=self._ctx.user_id,
                action="requirement.restored",
                resource_type="requirement",
                resource_id=row.id,
                metadata={"publicId": row.public_id},
            )
        return RequirementWriteResult(
            requirement=row,
            ws_event="requirement.restored",
            ws_payload={"requirementId": row.id, "publicId": row.public_id},
        )

    # ------------------------------------------------------------------
    # Link path
    # ------------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def create_link(self, req_id: str, case_id: str) -> RequirementLinkResult | None:
        """Link a requirement to a case after the same-workspace guard.

        Returns ``None`` when the requirement is not visible to this workspace
        (cross-workspace or soft-deleted) — router maps to 404. Raises
        :class:`CrossWorkspaceLinkError` when the requirement lives in this
        workspace but the case does not — router maps to 400.
        Returns the existing link (no-op) when a link already exists.
        """
        req = await self._load_in_scope(req_id)
        if req is None:
            return None

        # Resolve workspace ids on each side. The requirement always lives in
        # the current workspace (guard above); the case might not.
        case = await self._case_repo.get_by_id(case_id)
        if case is None:
            return None
        from suitest_db.repositories.suites import SuiteRepo

        suite_repo = SuiteRepo(self._session)
        suite = await suite_repo.get_by_id(case.suite_id)
        case_project = (
            await self._project_repo.get_by_id(suite.project_id) if suite is not None else None
        )
        case_workspace_id = case_project.workspace_id if case_project is not None else None
        if case_workspace_id is None:
            return None  # malformed graph — surface as 404 not 500

        if case_workspace_id != self._ctx.workspace_id:
            raise CrossWorkspaceLinkError(
                requirement_id=req.id,
                case_id=case.id,
                req_ws=self._ctx.workspace_id,
                case_ws=case_workspace_id,
            )

        existing = await self._repo.find_link(req.id, case.id)
        if existing is not None:
            # Idempotent: re-POST returns the existing link without writing an
            # audit or WS event (no real state change).
            return RequirementLinkResult(
                link=existing,
                ws_event="requirement.link.created",
                ws_payload={
                    "requirementId": req.id,
                    "publicId": req.public_id,
                    "caseId": case.id,
                    "casePublicId": case.public_id,
                    "idempotent": True,
                },
            )

        link = await self._repo.create_link(req.id, case.id)
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="requirement.link_created",
            resource_type="requirement_link",
            resource_id=link.id,
            metadata={
                "requirementId": req.id,
                "publicId": req.public_id,
                "caseId": case.id,
                "casePublicId": case.public_id,
            },
        )
        return RequirementLinkResult(
            link=link,
            ws_event="requirement.link.created",
            ws_payload={
                "requirementId": req.id,
                "publicId": req.public_id,
                "caseId": case.id,
                "casePublicId": case.public_id,
            },
        )

    @require_tier(TierFlag.ANY)
    async def delete_link(self, req_id: str, case_id: str) -> bool | None:
        """Remove a link. ``None`` when the requirement is out-of-scope (router → 404).

        Returns ``True`` when a link was deleted, ``False`` when no link existed
        (router → 404). The audit + WS event only fire on the True path.
        """
        req = await self._load_in_scope(req_id)
        if req is None:
            return None

        link = await self._repo.find_link(req.id, case_id)
        if link is None:
            return False

        link_id = link.id
        await self._repo.delete_link(req.id, case_id)
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="requirement.link_deleted",
            resource_type="requirement_link",
            resource_id=link_id,
            metadata={
                "requirementId": req.id,
                "publicId": req.public_id,
                "caseId": case_id,
            },
        )
        return True


__all__ = [
    "CrossWorkspaceLinkError",
    "RequirementLinkResult",
    "RequirementWriteResult",
    "RequirementWriteService",
]

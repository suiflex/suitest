"""WorkspaceService — read + M1d-28 settings/members/danger-zone writes.

Role rules (mirrors ``docs/API.md §3.1``):

* ``PATCH /workspaces/:id`` (General):
  - ``name`` / ``description`` / ``strict_zero_validation`` / ``mcp_routing_overrides``
    require ``ADMIN`` or ``OWNER``.
  - ``slug`` is **immutable** — POSTing it raises ``IMMUTABLE_SLUG`` (400) at
    the router (the DTO already forbids the field; the router converts the
    pydantic 422 into our canonical envelope).
* ``POST /workspaces/:id/members``: OWNER/ADMIN may invite QA/VIEWER/ADMIN.
  Granting OWNER requires the caller to be OWNER.
* ``PATCH /workspaces/:id/members/:user_id``: same gate as invite. Cannot
  demote the sole remaining OWNER → ``SOLE_OWNER_PROTECTED`` (400).
* ``DELETE /workspaces/:id/members/:user_id``: OWNER/ADMIN. Self-removal is
  allowed except if the caller is the sole OWNER.
* ``DELETE /workspaces/:id``: OWNER only. Body ``confirm_slug`` must equal
  ``workspace.slug``; mismatch raises ``CONFIRM_SLUG_MISMATCH`` (400). Sets
  ``deleted_at = now()`` (reads short-circuit) and the caller enqueues the
  async ``workspace_cleanup`` ARQ job.

Every mutation writes an explicit audit row via :func:`write_audit` and
returns a ``(result, ws_event, ws_payload)`` triple so the router can publish
the WS event *after* commit (same pattern as :mod:`test_case_service`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.models.tenancy import Membership
from suitest_db.models.workspace import Workspace
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_db.repositories.workspace_members import (
    WorkspaceMembershipRepo,
    create_placeholder_user,
)
from suitest_db.repositories.workspaces import WorkspaceRepo
from suitest_shared.domain.enums import AutonomyLevel, Role, Tier
from suitest_shared.schemas.responses import WorkspaceOut

from suitest_api.deps.scope import TenantContext
from suitest_api.deps.tier import require_tier
from suitest_api.utils.slug import slugify

# ``WorkspaceOut`` (shared package) covers the M1a list/detail summary surface.
# The Settings General-tab response carries ``strict_zero_validation`` +
# ``mcp_routing_overrides`` in addition — the router serialises those via
# :class:`WorkspaceDetail` (defined in :mod:`suitest_api.schemas.workspace`).
# The service returns the ORM row so the router can pick whichever DTO matches
# the endpoint. We re-export :class:`WorkspaceOut` so callers can keep validating
# read-side responses without re-deriving the import.
__all__ = [
    "ConfirmSlugMismatchError",
    "ImmutableSlugError",
    "MemberAlreadyExistsError",
    "MemberWriteResult",
    "OwnerGrantRequiresOwnerError",
    "SoleOwnerProtectedError",
    "WorkspaceCreateResult",
    "WorkspaceDeleteResult",
    "WorkspaceOut",
    "WorkspaceService",
    "WorkspaceServiceError",
    "WorkspaceSlugConflictError",
    "WorkspaceWriteResult",
    "create_workspace_for_user",
]


# ---------------------------------------------------------------------------
# Error sentinels — translated to HTTP envelope at the router edge.
# ---------------------------------------------------------------------------


class WorkspaceServiceError(Exception):
    """Base class for service-layer business-rule violations."""

    code: str = "WORKSPACE_ERROR"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ImmutableSlugError(WorkspaceServiceError):
    code = "IMMUTABLE_SLUG"


class OwnerGrantRequiresOwnerError(WorkspaceServiceError):
    code = "OWNER_GRANT_REQUIRES_OWNER"


class SoleOwnerProtectedError(WorkspaceServiceError):
    code = "SOLE_OWNER_PROTECTED"


class ConfirmSlugMismatchError(WorkspaceServiceError):
    code = "CONFIRM_SLUG_MISMATCH"


class MemberAlreadyExistsError(WorkspaceServiceError):
    code = "MEMBER_ALREADY_EXISTS"


class WorkspaceSlugConflictError(WorkspaceServiceError):
    code = "DUPLICATE_WORKSPACE_SLUG"

    def __init__(self, slug: str) -> None:
        super().__init__(
            f"workspace slug {slug!r} is already in use",
            details={"slug": slug},
        )
        self.slug = slug


# ---------------------------------------------------------------------------
# Result envelopes — router publishes WS event after commit.
# ---------------------------------------------------------------------------


@dataclass
class WorkspaceWriteResult:
    workspace: Workspace
    ws_event: str
    ws_payload: dict[str, object]


@dataclass
class MemberWriteResult:
    member_id: uuid.UUID
    email: str
    role: Role
    ws_event: str
    ws_payload: dict[str, object]


@dataclass
class WorkspaceDeleteResult:
    workspace_id: str
    ws_event: str
    ws_payload: dict[str, object]


@dataclass
class WorkspaceCreateResult:
    workspace: Workspace
    ws_event: str
    ws_payload: dict[str, object]


_ADMIN_OR_OWNER: frozenset[Role] = frozenset({Role.ADMIN, Role.OWNER})

# One ``-2`` suffix retry on slug collision before bubbling the 409 — same cap
# as the project create path (``project_service._SLUG_RETRY_SUFFIX``).
_WS_SLUG_RETRY_SUFFIX = "-2"
_WS_SLUG_MAX = 64


async def _next_workspace_slug(repo: WorkspaceRepo, requested: str | None, *, name: str) -> str:
    """Pick the slug to write: explicit ``requested`` wins, else derive from ``name``.

    Workspace slugs are globally unique. When derived from ``name`` we pre-check
    once and append ``-2`` on collision; an explicit ``requested`` slug is taken
    as-is so the caller owns conflict handling (a clash surfaces a 409 at flush).
    """
    if requested is not None and requested.strip():
        return requested.strip()
    base = slugify(name)
    if await repo.get_by_slug(base) is None:
        return base
    candidate = base + _WS_SLUG_RETRY_SUFFIX
    if len(candidate) > _WS_SLUG_MAX:
        candidate = base[: _WS_SLUG_MAX - len(_WS_SLUG_RETRY_SUFFIX)] + _WS_SLUG_RETRY_SUFFIX
    return candidate


@require_tier(TierFlag.ANY)
async def create_workspace_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str,
    slug: str | None,
    region: str | None = None,
) -> WorkspaceCreateResult:
    """Create a workspace owned by ``user_id`` and seed a ZERO-tier capability.

    Bootstrap path (``POST /workspaces``): a freshly-registered or invited user
    has no workspace, so this is how they get their first one entirely from the
    UI. The caller becomes the OWNER (so the row lists immediately) and a
    ``ZERO`` / ``MANUAL`` :class:`WorkspaceCapability` is seeded — mirrors
    :func:`suitest_api.services.bootstrap.bootstrap_first_install_superadmin` so
    a brand-new workspace resolves capabilities without an LLM config. Raises
    :class:`WorkspaceSlugConflictError` (→ 409) when the slug collides.
    """
    repo = WorkspaceRepo(session)
    resolved_slug = await _next_workspace_slug(repo, slug, name=name)
    workspace = Workspace(slug=resolved_slug, name=name)
    if region:
        workspace.region = region
    session.add(workspace)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "workspaces" in str(exc.orig) and "slug" in str(exc.orig):
            raise WorkspaceSlugConflictError(resolved_slug) from exc
        raise

    session.add(Membership(workspace_id=workspace.id, user_id=user_id, role=Role.OWNER))
    session.add(
        WorkspaceCapability(
            workspace_id=workspace.id,
            tier=Tier.ZERO,
            autonomy_level=AutonomyLevel.MANUAL,
            features_json={},
        )
    )
    await session.flush()
    await write_audit(
        session,
        workspace_id=workspace.id,
        user_id=str(user_id),
        action="workspace.created",
        resource_type="workspace",
        resource_id=workspace.id,
        metadata={"slug": workspace.slug, "name": workspace.name},
    )
    return WorkspaceCreateResult(
        workspace=workspace,
        ws_event="workspace.created",
        ws_payload={
            "workspaceId": workspace.id,
            "slug": workspace.slug,
            "name": workspace.name,
        },
    )


class WorkspaceService:
    def __init__(
        self,
        ctx: TenantContext,
        repo: WorkspaceRepo,
        member_repo: WorkspaceMembershipRepo,
    ) -> None:
        self._ctx = ctx
        self._repo = repo
        self._member_repo = member_repo
        self._session = repo.session

    # -- reads ---------------------------------------------------------------

    @require_tier(TierFlag.ANY)
    async def list_for_user(self) -> list[WorkspaceOut]:
        rows = await self._repo.list_for_user(uuid.UUID(self._ctx.user_id))
        return [WorkspaceOut.model_validate(r) for r in rows]

    @require_tier(TierFlag.ANY)
    async def get_by_id_for_user(self, workspace_id: str) -> WorkspaceOut | None:
        rows = await self._repo.list_for_user(uuid.UUID(self._ctx.user_id))
        for r in rows:
            if r.id == workspace_id:
                return WorkspaceOut.model_validate(r)
        return None

    # -- internal helpers ----------------------------------------------------

    async def _load_active(self, workspace_id: str) -> Workspace | None:
        row = await self._repo.get_by_id(workspace_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    def _require_admin(self) -> None:
        if self._ctx.role not in _ADMIN_OR_OWNER:
            raise WorkspaceServiceError(
                "ADMIN or OWNER required",
                details={"role": self._ctx.role.value},
            )

    def _require_owner(self) -> None:
        if self._ctx.role is not Role.OWNER:
            raise WorkspaceServiceError("OWNER required", details={"role": self._ctx.role.value})

    # -- PATCH /workspaces/:id ----------------------------------------------

    @require_tier(TierFlag.ANY)
    async def update_settings(
        self,
        workspace_id: str,
        *,
        name: str | None,
        description: str | None,
        strict_zero_validation: bool | None,
        mcp_routing_overrides: dict[str, str] | None,
    ) -> WorkspaceWriteResult | None:
        """Apply the General-tab patch. Returns ``None`` for unknown / soft-deleted ws.

        Every field is ADMIN+. ``description`` is stored on the
        ``mcp_routing_overrides`` JSON as a small adjacency since the
        ``workspaces`` table has no dedicated column today — keeps the
        migration footprint nil while the doc reads ``workspace.description``
        from the same JSON map. (FE M1d-28 ignores any string keys it does not
        recognise.)
        """
        self._require_admin()
        ws = await self._load_active(workspace_id)
        if ws is None:
            return None

        changed: list[str] = []
        if name is not None and ws.name != name:
            ws.name = name
            changed.append("name")
        if (
            strict_zero_validation is not None
            and ws.strict_zero_validation != strict_zero_validation
        ):
            ws.strict_zero_validation = strict_zero_validation
            changed.append("strict_zero_validation")
        if mcp_routing_overrides is not None and dict(ws.mcp_routing_overrides) != dict(
            mcp_routing_overrides
        ):
            ws.mcp_routing_overrides = dict(mcp_routing_overrides)
            changed.append("mcp_routing_overrides")
        if description is not None:
            overrides = dict(ws.mcp_routing_overrides)
            current_meta_raw: Any = overrides.get("_meta")
            current_meta: dict[str, Any] = (
                dict(current_meta_raw) if isinstance(current_meta_raw, dict) else {}
            )
            if current_meta.get("description") != description:
                current_meta["description"] = description
                overrides["_meta"] = current_meta
                ws.mcp_routing_overrides = overrides
                changed.append("description")

        await self._session.flush()
        await write_audit(
            self._session,
            workspace_id=workspace_id,
            user_id=self._ctx.user_id,
            action="workspace.updated",
            resource_type="workspace",
            resource_id=workspace_id,
            metadata={"fields": changed},
        )
        return WorkspaceWriteResult(
            workspace=ws,
            ws_event="workspace.updated",
            ws_payload={
                "workspaceId": workspace_id,
                "fields": changed,
                "by": self._ctx.user_id,
            },
        )

    # -- POST /workspaces/:id/members ---------------------------------------

    @require_tier(TierFlag.ANY)
    async def invite_member(
        self, workspace_id: str, *, email: str, role: Role
    ) -> MemberWriteResult | None:
        """Add a membership; create a placeholder user if no account exists yet."""
        self._require_admin()
        ws = await self._load_active(workspace_id)
        if ws is None:
            return None
        if role is Role.OWNER and self._ctx.role is not Role.OWNER:
            raise OwnerGrantRequiresOwnerError(
                "Only an OWNER can grant the OWNER role",
                details={"role": role.value},
            )

        user = await self._member_repo.find_user_by_email(email)
        if user is None:
            user = await create_placeholder_user(self._session, email=email)

        existing = await self._member_repo.get(workspace_id, user.id)
        if existing is not None:
            raise MemberAlreadyExistsError(
                "user is already a member of this workspace",
                details={"userId": str(user.id)},
            )

        membership = await self._member_repo.add(
            workspace_id=workspace_id, user_id=user.id, role=role
        )
        await write_audit(
            self._session,
            workspace_id=workspace_id,
            user_id=self._ctx.user_id,
            action="workspace.member.added",
            resource_type="membership",
            resource_id=membership.id,
            metadata={"email": email, "role": role.value, "userId": str(user.id)},
        )
        return MemberWriteResult(
            member_id=user.id,
            email=user.email,
            role=role,
            ws_event="workspace.member.added",
            ws_payload={
                "workspaceId": workspace_id,
                "userId": str(user.id),
                "email": user.email,
                "role": role.value,
                "by": self._ctx.user_id,
            },
        )

    # -- PATCH /workspaces/:id/members/:user_id -----------------------------

    @require_tier(TierFlag.ANY)
    async def change_member_role(
        self, workspace_id: str, user_id: uuid.UUID, *, role: Role
    ) -> MemberWriteResult | None:
        self._require_admin()
        ws = await self._load_active(workspace_id)
        if ws is None:
            return None
        if role is Role.OWNER and self._ctx.role is not Role.OWNER:
            raise OwnerGrantRequiresOwnerError(
                "Only an OWNER can grant the OWNER role",
                details={"role": role.value},
            )

        membership = await self._member_repo.get(workspace_id, user_id)
        if membership is None:
            return None
        previous = membership.role
        if previous is Role.OWNER and role is not Role.OWNER:
            owners = await self._member_repo.count_owners(workspace_id)
            if owners <= 1:
                raise SoleOwnerProtectedError(
                    "cannot demote the sole remaining OWNER",
                    details={"userId": str(user_id)},
                )

        await self._member_repo.change_role(membership, role)
        await write_audit(
            self._session,
            workspace_id=workspace_id,
            user_id=self._ctx.user_id,
            action="workspace.member.role_changed",
            resource_type="membership",
            resource_id=membership.id,
            metadata={"userId": str(user_id), "from": previous.value, "to": role.value},
        )
        return MemberWriteResult(
            member_id=user_id,
            email=membership.user.email,
            role=role,
            ws_event="workspace.member.role_changed",
            ws_payload={
                "workspaceId": workspace_id,
                "userId": str(user_id),
                "from": previous.value,
                "to": role.value,
                "by": self._ctx.user_id,
            },
        )

    # -- DELETE /workspaces/:id/members/:user_id ----------------------------

    @require_tier(TierFlag.ANY)
    async def remove_member(
        self, workspace_id: str, user_id: uuid.UUID
    ) -> MemberWriteResult | None:
        self._require_admin()
        ws = await self._load_active(workspace_id)
        if ws is None:
            return None

        membership: Membership | None = await self._member_repo.get(workspace_id, user_id)
        if membership is None:
            return None
        if membership.role is Role.OWNER:
            owners = await self._member_repo.count_owners(workspace_id)
            if owners <= 1:
                raise SoleOwnerProtectedError(
                    "cannot remove the sole remaining OWNER",
                    details={"userId": str(user_id)},
                )
        email = membership.user.email
        previous = membership.role
        await self._member_repo.delete(membership)
        await write_audit(
            self._session,
            workspace_id=workspace_id,
            user_id=self._ctx.user_id,
            action="workspace.member.removed",
            resource_type="membership",
            resource_id=str(user_id),
            metadata={"userId": str(user_id), "role": previous.value, "email": email},
        )
        return MemberWriteResult(
            member_id=user_id,
            email=email,
            role=previous,
            ws_event="workspace.member.removed",
            ws_payload={
                "workspaceId": workspace_id,
                "userId": str(user_id),
                "role": previous.value,
                "by": self._ctx.user_id,
            },
        )

    # -- DELETE /workspaces/:id ---------------------------------------------

    @require_tier(TierFlag.ANY)
    async def initiate_delete(
        self, workspace_id: str, *, confirm_slug: str
    ) -> WorkspaceDeleteResult | None:
        """Tombstone the workspace; caller enqueues the cleanup ARQ job."""
        self._require_owner()
        ws = await self._load_active(workspace_id)
        if ws is None:
            return None
        if confirm_slug != ws.slug:
            raise ConfirmSlugMismatchError(
                "confirm_slug does not match the workspace slug",
                details={"workspaceId": workspace_id},
            )
        await self._repo.mark_deleted(workspace_id)
        await write_audit(
            self._session,
            workspace_id=workspace_id,
            user_id=self._ctx.user_id,
            action="workspace.delete_initiated",
            resource_type="workspace",
            resource_id=workspace_id,
            metadata={"slug": ws.slug},
        )
        return WorkspaceDeleteResult(
            workspace_id=workspace_id,
            ws_event="workspace.delete_initiated",
            ws_payload={
                "workspaceId": workspace_id,
                "slug": ws.slug,
                "by": self._ctx.user_id,
            },
        )

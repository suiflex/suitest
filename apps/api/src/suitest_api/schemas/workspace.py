"""Auth + workspace response DTOs (docs/API.md §3.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from suitest_shared.domain.enums import Role


class UserPublic(BaseModel):
    """The authenticated user, safe for the wire (no password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None = None


class WorkspacePublic(BaseModel):
    """Workspace summary used in lists + as the nested object in a membership."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    region: str
    created_at: datetime
    updated_at: datetime


class MembershipPublic(BaseModel):
    """A user's membership in a workspace, with the workspace embedded."""

    workspace_id: str
    role: Role
    workspace: WorkspacePublic


class MeResponse(BaseModel):
    """``GET /auth/me`` — the current user plus every workspace they belong to."""

    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None = None
    memberships: list[MembershipPublic]


class WorkspaceDetail(WorkspacePublic):
    """``GET /workspaces/:id`` — Settings General tab consumes the extra fields."""

    model_config = ConfigDict(from_attributes=True)

    description: str | None = None
    strict_zero_validation: bool = True
    mcp_routing_overrides: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMemberPublic(BaseModel):
    """One row of ``GET /workspaces/:id/members``."""

    user_id: uuid.UUID
    email: str
    name: str
    role: Role
    joined_at: datetime


# ---------------------------------------------------------------------------
# M1d-28 write DTOs
# ---------------------------------------------------------------------------


class WorkspaceUpdate(BaseModel):
    """``PATCH /workspaces/:id`` body — General tab.

    ``slug`` is intentionally NOT present: slugs are immutable in the Project +
    Workspace pattern (changing them would orphan public URLs, audit refs, and
    cached MCP routing). A client that POSTs ``slug`` gets a 400
    ``IMMUTABLE_SLUG`` from the router — we surface a clear error rather than
    silently dropping the field, so a buggy client never thinks the slug
    update succeeded.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    strict_zero_validation: bool | None = None
    mcp_routing_overrides: dict[str, str] | None = None


class WorkspaceMemberInvite(BaseModel):
    """``POST /workspaces/:id/members`` body — invite by email + role."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: Role


class WorkspaceMemberRoleUpdate(BaseModel):
    """``PATCH /workspaces/:id/members/:user_id`` body."""

    model_config = ConfigDict(extra="forbid")

    role: Role


class WorkspaceDeleteConfirm(BaseModel):
    """``DELETE /workspaces/:id`` body — slug-typed-confirm guard."""

    model_config = ConfigDict(extra="forbid")

    confirm_slug: str = Field(min_length=1)


class WorkspaceDeleteAccepted(BaseModel):
    """``DELETE /workspaces/:id`` 202 response — cleanup is asynchronous."""

    cleanup_job_id: str
    status: str = "QUEUED"

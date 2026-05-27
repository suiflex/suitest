"""Auth + workspace response DTOs (docs/API.md §3.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict
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
    """``GET /workspaces/:id`` — currently identical to the summary (M1a)."""


class WorkspaceMemberPublic(BaseModel):
    """One row of ``GET /workspaces/:id/members``."""

    user_id: uuid.UUID
    email: str
    name: str
    role: Role
    joined_at: datetime

"""Audit log response DTOs (M1d-27 — docs/API.md §146-158).

``AuditLogRead`` is the per-row shape returned by ``GET /audit-logs``. The
metadata JSONB is exposed verbatim as ``details`` to match the documented
response envelope. ``user_email`` is best-effort: resolved via a left-join to
``users``; ``None`` when the audit row was written by a system actor or the
user has been deleted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogRead(BaseModel):
    """One audit row in the workspace audit trail (``GET /audit-logs`` item)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    workspace_id: str = Field(alias="workspaceId")
    user_id: str | None = Field(default=None, alias="userId")
    user_email: str | None = Field(default=None, alias="userEmail")
    action: str
    resource_type: str = Field(alias="resourceType")
    resource_id: str | None = Field(default=None, alias="resourceId")
    details: dict[str, Any] | None = None
    created_at: datetime = Field(alias="createdAt")


class AuditLogsResponse(BaseModel):
    """Cursor-paginated envelope for ``GET /audit-logs``.

    ``next_cursor`` is an opaque base64 token encoding ``(created_at, id)``; when
    ``None`` the caller has reached the head of the workspace audit log. The
    wire key stays snake_case to match the example envelope in ``docs/API.md``
    (§179) — the per-row keys are camelCase by alias, only the envelope keys
    follow the spec verbatim.
    """

    model_config = ConfigDict(populate_by_name=True)

    items: list[AuditLogRead] = Field(default_factory=list)
    next_cursor: str | None = None

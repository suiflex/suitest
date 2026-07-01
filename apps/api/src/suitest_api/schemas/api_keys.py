"""Pydantic DTOs for programmatic API keys (docs/API.md §3.x)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    """Create a key for the current workspace."""

    name: str = Field(min_length=1, max_length=120)
    # Optional lifetime in days; omit for a non-expiring key.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyItem(BaseModel):
    """A key in the management list.

    ``key`` carries the full plaintext token, decrypted from the AES-GCM column,
    so admins can re-copy it. It is ``None`` for keys created before the
    encrypted column existed. The list endpoint is admin-gated for this reason.
    """

    id: str
    name: str
    key_prefix: str
    key: str | None = None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyList(BaseModel):
    items: list[ApiKeyItem]


class ApiKeyCreated(ApiKeyItem):
    """Returned ONCE on creation — the only time the plaintext key is exposed."""

    key: str


class ApiKeyWhoami(BaseModel):
    """Verify-probe result: which workspace a key authenticates to."""

    workspace_id: str
    key_id: str
    key_name: str

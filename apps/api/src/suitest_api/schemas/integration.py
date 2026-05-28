"""Integration response DTOs (docs/API.md §3.9) — secrets always REDACTED.

The full encrypted secret is NEVER serialised. ``SecretsHint`` carries only a
``redacted=True`` marker and a ``hint`` (the last 4 chars of the decrypted secret),
matching ``{"redacted": true, "hint": "...last4"}`` from API.md §3.9. ``secrets`` is
``null`` when no secret is configured.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from suitest_shared.domain.enums import IntegrationKind


class SecretsHint(BaseModel):
    """Redacted secret marker + last-4 hint (no full secret ever)."""

    redacted: bool = True
    hint: str | None = None


class IntegrationListItem(BaseModel):
    """List row for ``GET /integrations`` (config visible, no secret material)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    kind: IntegrationKind
    name: str
    status: str
    has_secrets: bool
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IntegrationDetail(IntegrationListItem):
    """Detail — adds visible ``config`` and the redacted ``secrets`` block."""

    config: dict[str, Any]
    secrets: SecretsHint | None = None

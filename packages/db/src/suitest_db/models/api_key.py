"""Programmatic API keys for MCP / SDK / CI access (docs/DATA_MODEL.md §3.x).

A key authenticates a machine (an AI IDE's MCP client, the CLI, a CI job) to a
single workspace's API surface, standing in for a human's session JWT.

Security model: the key is a high-entropy random token (``sk_suitest_<43 chars>``)
shown to the user EXACTLY ONCE at creation. Only its SHA-256 hash is stored, so a
DB leak cannot recover live keys. ``key_prefix`` keeps a short, non-secret head
(``sk_suitest_ab12``) for the management UI to identify a key. This is a one-way
hash (not AES-GCM) because we never need to read the key back — only verify it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from suitest_core.crypto import EncryptedBytes

from suitest_db.base import Base, TimestampMixin
from suitest_db.ids import new_id


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Non-secret display head, e.g. "sk_suitest_ab12".
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    # SHA-256 hex digest of the full token — the auth path.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Full token, AES-GCM encrypted, so admins can re-copy it from the UI. Read
    # only by the (admin-gated) list surface; NULL for keys made before 0043.
    key_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_api_keys_workspace", "workspace_id"),
        Index("ux_api_keys_key_hash", "key_hash", unique=True),
    )

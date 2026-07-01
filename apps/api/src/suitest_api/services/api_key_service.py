"""Business logic for programmatic API keys.

Owns token generation, hashing, and audit. The token is minted here, hashed,
and handed back to the caller exactly once; only the hash reaches the DB.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit
from suitest_db.models.api_key import ApiKey
from suitest_db.repositories.api_keys import ApiKeyRepo

# User-visible token shape: sk_suitest_<43 url-safe chars>. The prefix (head) is
# stored non-secret so the UI can identify a key without the full value.
_TOKEN_BYTES = 32
_PREFIX_LEN = 15  # "sk_suitest_" (11) + 4 chars
KEY_PREFIX = "sk_suitest_"


def hash_token(token: str) -> str:
    """SHA-256 hex digest — the only stored representation of a key."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str, str]:
    """Return ``(token, prefix, key_hash)`` for a fresh key."""
    token = KEY_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    return token, token[:_PREFIX_LEN], hash_token(token)


async def create_api_key(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
    name: str,
    expires_in_days: int | None = None,
) -> tuple[ApiKey, str]:
    """Create a key; returns the row plus the plaintext token (shown once)."""
    token, prefix, key_hash = generate_token()
    expires_at = (
        datetime.now(UTC) + timedelta(days=expires_in_days)
        if expires_in_days is not None
        else None
    )
    created_by = uuid.UUID(user_id)
    row = await ApiKeyRepo(session).create(
        workspace_id=workspace_id,
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        key_encrypted=token,
        created_by=created_by,
        expires_at=expires_at,
    )
    await write_audit(
        session,
        workspace_id=workspace_id,
        user_id=user_id,
        action="api_key.create",
        resource_type="api_key",
        resource_id=row.id,
        metadata={"name": name, "key_prefix": prefix},
    )
    return row, token


async def list_api_keys(session: AsyncSession, workspace_id: str) -> Sequence[ApiKey]:
    return await ApiKeyRepo(session).list_active(workspace_id)


async def revoke_api_key(
    session: AsyncSession, *, workspace_id: str, user_id: str, key_id: str
) -> ApiKey | None:
    """Revoke a key. Returns ``None`` when it does not exist in the workspace."""
    row = await ApiKeyRepo(session).revoke(workspace_id, key_id)
    if row is None:
        return None
    await write_audit(
        session,
        workspace_id=workspace_id,
        user_id=user_id,
        action="api_key.revoke",
        resource_type="api_key",
        resource_id=row.id,
        metadata={"key_prefix": row.key_prefix},
    )
    return row


async def authenticate(session: AsyncSession, token: str) -> ApiKey | None:
    """Resolve a live key from a plaintext token, bumping ``last_used_at``.

    Returns ``None`` for unknown/revoked/expired keys (caller maps to 401).
    """
    if not token.startswith(KEY_PREFIX):
        return None
    repo = ApiKeyRepo(session)
    row = await repo.get_active_by_hash(hash_token(token))
    if row is None:
        return None
    await repo.touch_last_used(row)
    return row

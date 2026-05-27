"""Shared cursor helpers for the read-only routers.

Routers decode the opaque ``?cursor`` token into the ``(created_at, id)`` keyset
the repos expect (raising 400 on a malformed token), then re-encode the repo's
``next_cursor`` keyset back into an opaque token for the response. Keeping this in
one place means every paginated endpoint agrees on the 400-on-bad-cursor rule.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from suitest_db.repositories.cursor import InvalidCursorError, decode_cursor, encode_cursor

Keyset = tuple[datetime, str]


def decode_cursor_or_400(cursor: str | None) -> Keyset | None:
    """Decode an opaque cursor into a keyset, or 400 if it is malformed."""
    if cursor is None:
        return None
    try:
        return decode_cursor(cursor)
    except InvalidCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cursor"
        ) from exc


def encode_next(next_keyset: Keyset | None) -> str | None:
    """Encode a repo ``next_cursor`` keyset back into an opaque token (or None)."""
    return encode_cursor(*next_keyset) if next_keyset is not None else None

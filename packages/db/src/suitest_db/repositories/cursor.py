"""Opaque keyset-pagination cursor codec.

The wire format is a URL-safe base64 string wrapping a tiny JSON object
``{"ts": <iso8601>, "id": <cuid>}``. Callers never parse the cursor — they hand
it back verbatim and the repository decodes it into the ``(created_at, id)``
keyset tuple used for the ``WHERE (created_at, id) < (?, ?)`` predicate.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime


class InvalidCursorError(ValueError):
    """Raised when a cursor string cannot be decoded into a keyset tuple."""


def encode_cursor(ts: datetime, id: str) -> str:
    """Encode a ``(created_at, id)`` keyset into an opaque base64 token."""
    payload = json.dumps({"ts": ts.isoformat(), "id": id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(token: str) -> tuple[datetime, str]:
    """Decode an opaque base64 token back into a ``(created_at, id)`` keyset.

    Raises ``InvalidCursorError`` for any malformed input (bad base64, bad JSON,
    missing keys, or an unparseable timestamp).
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursorError(f"malformed cursor: {token!r}") from exc

    if not isinstance(data, dict) or "ts" not in data or "id" not in data:
        raise InvalidCursorError(f"malformed cursor payload: {token!r}")

    ts_raw = data["ts"]
    id_raw = data["id"]
    if not isinstance(ts_raw, str) or not isinstance(id_raw, str):
        raise InvalidCursorError(f"malformed cursor fields: {token!r}")

    try:
        ts = datetime.fromisoformat(ts_raw)
    except ValueError as exc:
        raise InvalidCursorError(f"malformed cursor timestamp: {token!r}") from exc

    return ts, id_raw

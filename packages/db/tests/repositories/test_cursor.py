"""Cursor codec tests (no DB required)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from suitest_db.repositories.cursor import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)


def test_cursor_roundtrip() -> None:
    ts = datetime(2026, 5, 28, 12, 30, 45, 123456, tzinfo=UTC)
    cuid = "abc123def456"
    token = encode_cursor(ts, cuid)
    decoded_ts, decoded_id = decode_cursor(token)
    assert decoded_ts == ts
    assert decoded_id == cuid


@pytest.mark.parametrize(
    "bad",
    [
        "not-base64-$$$",
        "",
        "e30=",  # base64 of "{}" — valid JSON, missing keys
        "bm90LWpzb24=",  # base64 of "not-json"
    ],
)
def test_cursor_malformed_raises(bad: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(bad)

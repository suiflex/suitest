"""Tests for ``rotate_audit_logs`` serialisation helpers (M4-32).

The S3 + DB round-trip is exercised by integration tests; here we cover the
pure archival serialisation (JSONL + gzip), the archive key layout, and the
ctx-guard short-circuits that keep the job safe under a malformed worker ctx.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime

import pytest
from suitest_db.models.audit import AuditLog
from suitest_runner.jobs.rotate_audit_logs import (
    _archive_key,
    _serialise,
    restore_audit_logs,
    rotate_audit_logs,
)


def _make_row(row_id: str) -> AuditLog:
    return AuditLog(
        id=row_id,
        workspace_id="ws_1",
        user_id=None,
        action="defect.create",
        resource_type="defect",
        resource_id="defc_1",
        metadata_json={"k": "v"},
        ip_address="10.0.0.1",
        user_agent="pytest",
        created_at=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
    )


def test_archive_key_layout() -> None:
    assert _archive_key("ws_1", "2025-01") == "audit/ws_1/2025-01.jsonl.gz"


def test_serialise_roundtrips_jsonl() -> None:
    rows = [_make_row("a1"), _make_row("a2")]
    blob = _serialise(rows)
    decoded = gzip.decompress(blob).decode("utf-8").splitlines()
    assert len(decoded) == 2
    first = json.loads(decoded[0])
    assert first["id"] == "a1"
    assert first["action"] == "defect.create"
    assert first["metadata"] == {"k": "v"}
    assert first["created_at"].startswith("2025-01-15")


@pytest.mark.asyncio
async def test_rotate_guard_on_invalid_ctx() -> None:
    out = await rotate_audit_logs({})
    assert out == {"archived_months": 0, "error": "RUNNER_CTX_INVALID"}


@pytest.mark.asyncio
async def test_restore_guard_on_invalid_ctx() -> None:
    out = await restore_audit_logs({}, "ws_1", "2025-01")
    assert out == {"restored": 0, "error": "RUNNER_CTX_INVALID"}

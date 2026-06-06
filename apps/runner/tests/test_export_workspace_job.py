"""Tests for ``export_workspace`` archive helpers (M4-29).

Covers secret redaction, the tarball layout, and the ctx guard. The S3 + DB
round-trip is exercised by integration tests.
"""

from __future__ import annotations

import io
import json
import tarfile

import pytest
from suitest_db.models.integration import Integration
from suitest_runner.jobs.export_workspace import (
    _build_tarball,
    _dump_rows,
    _export_key,
    export_workspace,
)
from suitest_shared.domain.enums import IntegrationKind


def test_export_key_layout() -> None:
    assert _export_key("ws_1", "exp_1") == "exports/ws_1/exp_1.tar.gz"


def test_dump_rows_redacts_encrypted_columns() -> None:
    integration = Integration(
        id="int_1",
        workspace_id="ws_1",
        kind=IntegrationKind.JIRA,
        name="Jira",
        config={"base_url": "https://x.atlassian.net"},
        secrets_encrypted='{"token": "super-secret"}',
        status="active",
    )
    dumped = _dump_rows([integration])
    assert dumped[0]["secrets_encrypted"] == "***REDACTED***"
    assert dumped[0]["name"] == "Jira"
    assert "super-secret" not in json.dumps(dumped)


def test_build_tarball_layout() -> None:
    bundle = {"schema_version": "1.0", "projects": [], "workspace": {"id": "ws_1"}}
    blob = _build_tarball("ws_1", "exp_1", bundle)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        names = tar.getnames()
        assert "manifest.json" in names
        assert "entities.json" in names
        entities = json.loads(tar.extractfile("entities.json").read())  # type: ignore[union-attr]
        assert entities["workspace"]["id"] == "ws_1"


@pytest.mark.asyncio
async def test_export_guard_on_invalid_ctx() -> None:
    out = await export_workspace({}, "ws_1", "exp_1")
    assert out == {"status": "error", "error": "RUNNER_CTX_INVALID"}

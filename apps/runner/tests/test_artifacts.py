"""Tests for the artifact upload pipeline (M1c Task 13).

We stub the aioboto3 S3 client directly instead of using moto: moto's mock
S3 patches the synchronous ``botocore.endpoint`` path, which doesn't
intercept ``aiobotocore``'s async endpoint resolver (the two stacks diverged
after botocore 1.40 added per-request SHA-256 checksums + ``aws-chunked``
transfer encoding to S3 put_object — moto can't decode the chunked body and
aiobotocore's response shape doesn't match what moto returns).

Patching ``aioboto3.Session.client`` with an async context manager that
returns a recording stub gives us:

* deterministic assertions over the ``put_object`` call args (Bucket, Key,
  Body, ContentType) — exactly what we'd assert against a real S3 anyway,
* no chunked-encoding / signature-version drift,
* no network — the test runs in <50ms,
* the same assertions cover MinIO + AWS S3 (the surface is identical).

``ArtifactRepo`` is replaced via monkeypatch with a recorder so we can assert
against the kwargs the upload pipeline forwards into the repo.

Three slices:
* round-trip a binary screenshot — put_object lands the bytes + DB row,
* upload a text artifact (HAR) — text body is UTF-8 encoded into put_object,
* empty artifact list — no S3 client opened, no DB row created (fast path).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from suitest_mcp.models import McpArtifact
from suitest_runner.settings import RunnerSettings

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _RecordingS3Client:
    """Async S3 client stand-in capturing every ``put_object`` invocation."""

    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        return {"ETag": f'"etag-{len(self.puts)}"'}


@pytest.fixture()
def recording_s3(monkeypatch: pytest.MonkeyPatch) -> _RecordingS3Client:
    """Patch ``aioboto3.Session.client`` to yield a recording S3 stub.

    Returns the shared client so the test can assert against the puts list
    after :func:`upload_artifacts` returns.
    """
    stub = _RecordingS3Client()

    @asynccontextmanager
    async def _client_factory(
        _self: object, _service: str, **_kwargs: Any
    ) -> AsyncIterator[_RecordingS3Client]:
        yield stub

    import aioboto3

    monkeypatch.setattr(aioboto3.Session, "client", _client_factory)
    return stub


@pytest.fixture()
def recording_repo(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Replace ``ArtifactRepo`` with a class that appends every create_artifact call.

    Returns the shared ``calls`` list so tests can assert against the kwargs
    the upload pipeline forwarded into the repo (kind, url, size_bytes, mime,
    metadata).
    """
    calls: list[dict[str, object]] = []

    class _RecorderArtifactRepo:
        def __init__(self, _session: object) -> None:
            pass

        async def create_artifact(self, **kwargs: object) -> MagicMock:
            calls.append(kwargs)
            row = MagicMock()
            row.id = f"art-{len(calls)}"
            return row

    # The upload module late-imports the repo; we monkeypatch the source so
    # the late import resolves to our recorder regardless of import order.
    import suitest_db.repositories.runs as runs_repo_mod

    monkeypatch.setattr(runs_repo_mod, "ArtifactRepo", _RecorderArtifactRepo)
    return calls


@pytest.fixture()
def runner_settings(monkeypatch: pytest.MonkeyPatch) -> RunnerSettings:
    """RunnerSettings pinned at a deterministic test bucket + dummy creds."""
    monkeypatch.setenv("SUITEST_RUNNER_S3_BUCKET", "suitest-test-artifacts")
    monkeypatch.setenv("SUITEST_RUNNER_S3_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("SUITEST_RUNNER_S3_ACCESS_KEY", "testing")
    monkeypatch.setenv("SUITEST_RUNNER_S3_SECRET_KEY", "testing")
    monkeypatch.setenv("SUITEST_RUNNER_S3_REGION", "us-east-1")
    return RunnerSettings()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_upload_creates_s3_object_and_db_row(
    runner_settings: RunnerSettings,
    recording_s3: _RecordingS3Client,
    recording_repo: list[dict[str, object]],
) -> None:
    """Binary screenshot round-trips: put_object args + repo row both match the input."""
    from suitest_runner.artifacts import upload_artifacts

    art = McpArtifact(
        kind="SCREENSHOT",
        filename="step.png",
        content_type="image/png",
        bytes=b"PNG\x89FAKEDATA",
    )
    session = MagicMock()
    ctx: dict[str, object] = {"settings": runner_settings}

    await upload_artifacts(
        session=session,
        ctx=ctx,
        run_id="r1",
        run_step_id="rs1",
        step_order=0,
        artifacts=[art],
    )

    assert len(recording_s3.puts) == 1
    put = recording_s3.puts[0]
    assert put["Bucket"] == "suitest-test-artifacts"
    assert put["Key"] == "runs/r1/step-0/screenshot/step.png"
    assert put["Body"] == b"PNG\x89FAKEDATA"
    assert put["ContentType"] == "image/png"

    assert len(recording_repo) == 1
    row = recording_repo[0]
    assert row["run_step_id"] == "rs1"
    assert row["kind"] == "SCREENSHOT"
    assert row["url"] == "s3://suitest-test-artifacts/runs/r1/step-0/screenshot/step.png"
    assert row["size_bytes"] == len(b"PNG\x89FAKEDATA")
    assert row["mime_type"] == "image/png"


async def test_upload_text_artifact(
    runner_settings: RunnerSettings,
    recording_s3: _RecordingS3Client,
    recording_repo: list[dict[str, object]],
) -> None:
    """A HAR / console log carries ``text`` instead of bytes — UTF-8 encoded on upload."""
    from suitest_runner.artifacts import upload_artifacts

    payload = '{"log":{"entries":[]}}'
    art = McpArtifact(
        kind="HAR",
        filename="trace.har",
        content_type="application/json",
        text=payload,
    )
    session = MagicMock()
    ctx: dict[str, object] = {"settings": runner_settings}

    await upload_artifacts(
        session=session,
        ctx=ctx,
        run_id="r2",
        run_step_id="rs2",
        step_order=3,
        artifacts=[art],
    )

    assert len(recording_s3.puts) == 1
    put = recording_s3.puts[0]
    assert put["Key"] == "runs/r2/step-3/har/trace.har"
    assert put["Body"] == payload.encode("utf-8")
    assert put["ContentType"] == "application/json"

    assert len(recording_repo) == 1
    assert recording_repo[0]["mime_type"] == "application/json"
    assert recording_repo[0]["size_bytes"] == len(payload.encode("utf-8"))


async def test_no_artifacts_short_circuits(
    runner_settings: RunnerSettings,
    recording_s3: _RecordingS3Client,
    recording_repo: list[dict[str, object]],
) -> None:
    """Empty list → fast path: no S3 calls, no DB rows written."""
    from suitest_runner.artifacts import upload_artifacts

    session = MagicMock()
    ctx: dict[str, object] = {"settings": runner_settings}

    await upload_artifacts(
        session=session,
        ctx=ctx,
        run_id="r3",
        run_step_id="rs3",
        step_order=0,
        artifacts=[],
    )

    assert recording_s3.puts == []
    assert recording_repo == []

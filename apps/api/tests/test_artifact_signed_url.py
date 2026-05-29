"""Tests for ``GET /api/v1/runs/:id/artifacts/:artifact_id`` (M1c Task 18).

Patches ``aioboto3.Session.client`` to return a recording stub (same pattern
as ``apps/runner/tests/test_artifacts.py``) — moto + aiobotocore have been
incompatible since aiobotocore 2.x adopted the chunked SHA-256 signing path,
so a recording stub is both faster AND closer to what the production code
actually sends.

Two assertions:
* response shape: ``{url, expiresInSeconds, kind, mimeType}`` (per plan),
* one ``artifact.signed_url`` audit row is appended for download attribution.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Artifact, Run, RunStep
from suitest_shared.domain.enums import (
    ArtifactKind,
    CaseSource,
    RunTrigger,
    StepOutcome,
    Tier,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


_FAKE_PRESIGNED_URL = (
    "https://minio.example/suitest-artifacts/runs/r1/shot.png?X-Amz-Signature=stub"
)


class _RecordingS3Client:
    """Recording ``aioboto3`` client stub. Only ``generate_presigned_url`` is needed."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append({"args": args, "kwargs": kwargs})
        return _FAKE_PRESIGNED_URL


@pytest.fixture()
def recording_s3(monkeypatch: pytest.MonkeyPatch) -> _RecordingS3Client:
    """Patch ``aioboto3.Session.client`` to yield the recording S3 stub.

    Mirrors the runner-side artifact-upload test fixture so both sides keep
    one canonical pattern for "pretend S3 is here".
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


@pytest.mark.asyncio
async def test_signed_url_returns_presigned_and_audits(
    api_db: ApiDb, recording_s3: _RecordingS3Client
) -> None:
    user = await api_db.seed_user(email="art-sign@example.com")
    ws = await api_db.member_workspace(user, slug="art-sign-ws")
    proj = Project(workspace_id=ws.id, slug="p", name="P")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-AS1", name="c", source=CaseSource.MANUAL)
    run = Run(
        public_id="RUN-AS1",
        project_id=proj.id,
        name="r",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
    )
    await api_db.add_all([case, run])
    step = RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=StepOutcome.PASS)
    await api_db.add_all([step])
    art = Artifact(
        run_step_id=step.id,
        kind=ArtifactKind.SCREENSHOT,
        url="s3://suitest-artifacts/runs/r1/shot.png",
        size_bytes=10,
        mime_type="image/png",
    )
    await api_db.add_all([art])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/runs/{run.id}/artifacts/{art.id}",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"] == _FAKE_PRESIGNED_URL
    assert body["expiresInSeconds"] == 3600
    assert body["kind"] == "SCREENSHOT"
    assert body["mimeType"] == "image/png"

    # Audit row landed; ``write_audit`` records run_id in metadata.
    async with api_db.maker() as session:
        audit_rows = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "artifact.signed_url"))
        ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].resource_id == art.id
    assert audit_rows[0].workspace_id == ws.id

    # S3 stub got one call with the parsed bucket/key.
    assert len(recording_s3.calls) == 1
    params = recording_s3.calls[0]["kwargs"].get("Params") or {}
    assert params.get("Bucket") == "suitest-artifacts"
    assert params.get("Key") == "runs/r1/shot.png"

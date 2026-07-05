"""Tests for local-mode artifact serving (P0 item #3).

``local://`` artifacts resolve to the raw streaming endpoint
(``GET /api/v1/runs/:id/artifacts/:artifact_id/raw``) instead of an S3
presigned URL, and the raw endpoint streams the file from
``SUITEST_ARTIFACTS_DIR`` with a path-traversal guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
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
    from pathlib import Path

    from api_harness import ApiDb


async def _seed_run_with_artifact(
    api_db: ApiDb, *, email: str, slug: str, artifact_url: str
) -> tuple[object, object, Run, Artifact]:
    """Seed user → workspace → project → suite → case → run → step → artifact."""
    user = await api_db.seed_user(email=email)
    ws = await api_db.member_workspace(user, slug=slug)
    proj = Project(workspace_id=ws.id, slug="p", name="P")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-AL1", name="c", source=CaseSource.MANUAL)
    run = Run(
        public_id="RUN-AL1",
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
        url=artifact_url,
        size_bytes=10,
        mime_type="image/png",
    )
    await api_db.add_all([art])
    return user, ws, run, art


@pytest.mark.asyncio
async def test_local_artifact_resolves_to_raw_endpoint_and_streams(
    api_db: ApiDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUITEST_ARTIFACTS_DIR", str(tmp_path))

    rel = "runs/r1/step-1/screenshot/shot.png"
    user, ws, run, art = await _seed_run_with_artifact(
        api_db, email="art-local@example.com", slug="art-local-ws", artifact_url=f"local://{rel}"
    )

    file_path = tmp_path / rel
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"\x89PNG-local")

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/runs/{run.id}/artifacts/{art.id}",
            headers={"X-Workspace-Id": ws.id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["url"] == f"/api/v1/runs/{run.id}/artifacts/{art.id}/raw"

        raw = await c.get(body["url"], headers={"X-Workspace-Id": ws.id})
        assert raw.status_code == 200
        assert raw.content == b"\x89PNG-local"
        assert raw.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_raw_endpoint_rejects_path_traversal(
    api_db: ApiDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUITEST_ARTIFACTS_DIR", str(tmp_path))

    user, ws, run, art = await _seed_run_with_artifact(
        api_db,
        email="art-evil@example.com",
        slug="art-evil-ws",
        artifact_url="local://../../etc/passwd",
    )

    async with api_db.client(user) as c:
        raw = await c.get(
            f"/api/v1/runs/{run.id}/artifacts/{art.id}/raw",
            headers={"X-Workspace-Id": ws.id},
        )
        assert raw.status_code == 404

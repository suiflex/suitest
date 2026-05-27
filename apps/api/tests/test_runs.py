"""Task 7e — run / step / log / artifact read endpoint tests (docs/API.md §3.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.case import TestCase
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Artifact, Run, RunStep
from suitest_shared.domain.enums import (
    ArtifactKind,
    CaseSource,
    RunStatus,
    RunTrigger,
    StepOutcome,
    Tier,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


async def _project(api_db: ApiDb, ws_id: str, *, slug: str = "run-proj") -> Project:
    proj = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([proj])
    return proj


def _run(project_id: str, public_id: str, **kw: object) -> Run:
    return Run(
        public_id=public_id,
        project_id=project_id,
        name="run",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
        **kw,
    )


@pytest.mark.asyncio
async def test_list_runs_filter_by_status(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-status@example.com")
    ws = await api_db.member_workspace(user, slug="run-status-ws")
    proj = await _project(api_db, ws.id)
    await api_db.add_all(
        [
            _run(proj.id, "RUN-S1", status=RunStatus.PASS),
            _run(proj.id, "RUN-S2", status=RunStatus.FAIL),
            _run(proj.id, "RUN-S3", status=RunStatus.PASS),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/runs?projectId={proj.id}&status=PASS", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


@pytest.mark.asyncio
async def test_list_runs_filter_by_branch_env(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-be@example.com")
    ws = await api_db.member_workspace(user, slug="run-be-ws")
    proj = await _project(api_db, ws.id)
    await api_db.add_all(
        [
            _run(proj.id, "RUN-B1", branch="main", env="staging"),
            _run(proj.id, "RUN-B2", branch="dev", env="staging"),
            _run(proj.id, "RUN-B3", branch="main", env="prod"),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/runs?projectId={proj.id}&branch=main&env=staging",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {r["public_id"] for r in items} == {"RUN-B1"}


@pytest.mark.asyncio
async def test_get_run_detail_summary_correct(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-summary@example.com")
    ws = await api_db.member_workspace(user, slug="run-summary-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-RUN1", name="c", source=CaseSource.MANUAL)
    run = _run(proj.id, "RUN-SUM", duration_ms=1234)
    await api_db.add_all([case, run])
    outcomes = [
        StepOutcome.PASS,
        StepOutcome.PASS,
        StepOutcome.PASS,
        StepOutcome.FAIL,
        StepOutcome.ERROR,
    ]
    await api_db.add_all(
        [
            RunStep(run_id=run.id, case_id=case.id, step_order=i, outcome=o)
            for i, o in enumerate(outcomes)
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/runs/{run.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    summary = resp.json()["summary"]
    assert summary["total_steps"] == 5
    assert summary["passed_steps"] == 3
    assert summary["failed_steps"] == 2  # FAIL + ERROR
    assert summary["duration_ms"] == 1234


@pytest.mark.asyncio
async def test_get_run_steps_ordered(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-steps@example.com")
    ws = await api_db.member_workspace(user, slug="run-steps-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-RUN2", name="c", source=CaseSource.MANUAL)
    run = _run(proj.id, "RUN-ORD")
    await api_db.add_all([case, run])
    await api_db.add_all(
        [
            RunStep(run_id=run.id, case_id=case.id, step_order=3, outcome=StepOutcome.PASS),
            RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=StepOutcome.PASS),
            RunStep(run_id=run.id, case_id=case.id, step_order=2, outcome=StepOutcome.PASS),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/runs/{run.id}/steps", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    steps = resp.json()
    assert [s["step_order"] for s in steps] == [1, 2, 3]
    assert all(s["case_public_id"] == "TC-RUN2" for s in steps)


@pytest.mark.asyncio
async def test_get_run_logs_paginated(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-logs@example.com")
    ws = await api_db.member_workspace(user, slug="run-logs-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-RUN3", name="c", source=CaseSource.MANUAL)
    run = _run(proj.id, "RUN-LOG")
    await api_db.add_all([case, run])
    await api_db.add_all(
        [
            RunStep(
                run_id=run.id,
                case_id=case.id,
                step_order=1,
                outcome=StepOutcome.PASS,
                stdout="out-line-1\nout-line-2",
                stderr="err-line-1",
            )
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/runs/{run.id}/logs", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["lines"] == ["out-line-1", "out-line-2", "err-line-1"]
    assert data["nextCursor"] is None


@pytest.mark.asyncio
async def test_get_run_artifacts_lists_all(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-art@example.com")
    ws = await api_db.member_workspace(user, slug="run-art-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-RUN4", name="c", source=CaseSource.MANUAL)
    run = _run(proj.id, "RUN-ART")
    await api_db.add_all([case, run])
    step = RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=StepOutcome.PASS)
    await api_db.add_all([step])
    await api_db.add_all(
        [
            Artifact(
                run_step_id=step.id,
                kind=ArtifactKind.SCREENSHOT,
                url="s3://bucket/a.png",
                size_bytes=10,
                mime_type="image/png",
            ),
            Artifact(
                run_step_id=step.id,
                kind=ArtifactKind.HAR,
                url="s3://bucket/b.har",
                size_bytes=20,
                mime_type="application/json",
            ),
        ]
    )
    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/runs/{run.id}/artifacts", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_artifact_signed_url_s3(api_db: ApiDb, monkeypatch: pytest.MonkeyPatch) -> None:
    user = await api_db.seed_user(email="run-sign-s3@example.com")
    ws = await api_db.member_workspace(user, slug="run-sign-s3-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-RUN5", name="c", source=CaseSource.MANUAL)
    run = _run(proj.id, "RUN-SGN1")
    await api_db.add_all([case, run])
    step = RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=StepOutcome.PASS)
    await api_db.add_all([step])
    art = Artifact(
        run_step_id=step.id,
        kind=ArtifactKind.SCREENSHOT,
        url="s3://bucket/shot.png",
        size_bytes=10,
        mime_type="image/png",
    )
    await api_db.add_all([art])

    calls: list[tuple[str, int]] = []

    def _fake_presign(object_url: str, *, expires_in: int) -> str:
        calls.append((object_url, expires_in))
        return f"https://signed.example/{object_url}"

    monkeypatch.setattr("suitest_api.services.artifact_signing._presign", _fake_presign)

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/runs/{run.id}/artifacts/{art.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scheme"] == "s3"
    assert data["url"].startswith("https://signed.example/")
    assert calls == [("s3://bucket/shot.png", 900)]


@pytest.mark.asyncio
async def test_get_artifact_signed_url_file_scheme_returns_placeholder(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-sign-file@example.com")
    ws = await api_db.member_workspace(user, slug="run-sign-file-ws")
    proj = await _project(api_db, ws.id)
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(suite_id=suite.id, public_id="TC-RUN6", name="c", source=CaseSource.MANUAL)
    run = _run(proj.id, "RUN-SGN2")
    await api_db.add_all([case, run])
    step = RunStep(run_id=run.id, case_id=case.id, step_order=1, outcome=StepOutcome.PASS)
    await api_db.add_all([step])
    art = Artifact(
        run_step_id=step.id,
        kind=ArtifactKind.VIDEO,
        url="file:///data/video.webm",
        size_bytes=10,
        mime_type="video/webm",
    )
    await api_db.add_all([art])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/runs/{run.id}/artifacts/{art.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scheme"] == "file"
    assert data["url"] == f"/artifacts/raw/{art.id}"
    assert data["kind"] == "VIDEO"


@pytest.mark.asyncio
async def test_get_run_404_cross_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-x@example.com")
    ws = await api_db.member_workspace(user, slug="run-x-ws")
    other = await api_db.seed_workspace(slug="run-x-other", name="Other")
    proj = await _project(api_db, other.id, slug="run-x-other-proj")
    run = _run(proj.id, "RUN-XX")
    await api_db.add_all([run])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/runs/{run.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 404

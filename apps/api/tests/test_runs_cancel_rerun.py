"""Tests for ``POST /api/v1/runs/:id/cancel`` and ``/rerun`` (M1c Task 16).

* Cancel on a QUEUED run flips to CANCELLED and returns the new row,
* Cancel on a terminal (PASS) run returns 409 ``run not cancellable``,
* Rerun clones the original's selection into a fresh QUEUED row with a new
  id, and the ARQ stub records one enqueue call against ``run_test_case``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from suitest_api.deps.arq import get_arq
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run
from suitest_shared.domain.enums import (
    CaseSource,
    RunStatus,
    RunTrigger,
    TargetKind,
    Tier,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


# Local copies of the create-run test's ARQ stub. Inlined (rather than imported
# from ``test_runs_create``) because the api ``tests/`` package has no
# ``__init__.py`` — pytest runs each test module under ``--import-mode=importlib``
# which discourages relative imports between test files.


@dataclass
class _RecordingJob:
    job_id: str


@dataclass
class _RecordingArq:
    enqueued: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(default_factory=list)

    async def enqueue_job(self, function: str, *args: object, **kwargs: object) -> _RecordingJob:
        self.enqueued.append((function, args, kwargs))
        return _RecordingJob(job_id=f"job-{len(self.enqueued)}")


def _override_arq(app: Any, arq: _RecordingArq) -> None:
    async def _get_recording_arq() -> _RecordingArq:
        return arq

    app.dependency_overrides[get_arq] = _get_recording_arq


def _run_row(project_id: str, public_id: str, status: RunStatus, **kw: Any) -> Run:
    return Run(
        public_id=public_id,
        project_id=project_id,
        name="r",
        trigger=RunTrigger.MANUAL,
        tier_at_runtime=Tier.ZERO,
        status=status,
        **kw,
    )


async def _seed_runnable_project(api_db: ApiDb, ws_id: str, slug: str) -> tuple[Project, TestCase]:
    """Seed a project + suite + case + bundled-mcp step so rerun can clone selection."""
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(
        suite_id=suite.id,
        public_id=f"TC-{slug.upper()}",
        name="c",
        source=CaseSource.MANUAL,
    )
    await api_db.add_all([case])
    step = TestStep(
        case_id=case.id,
        order=1,
        action="ping",
        expected="200",
        mcp_provider="api-http-mcp",
        target_kind=TargetKind.BE_REST,
    )
    await api_db.add_all([step])
    return project, case


@pytest.mark.asyncio
async def test_cancel_queued_run_transitions_to_cancelled(api_db: ApiDb) -> None:
    """A QUEUED run flips to CANCELLED on POST /cancel; status echoed in the response."""
    user = await api_db.seed_user(email="run-cancel-q@example.com")
    ws = await api_db.member_workspace(user, slug="run-cancel-q-ws")
    project, _ = await _seed_runnable_project(api_db, ws.id, slug="cancel-q-p")
    run = _run_row(project.id, "RUN-CANCEL-Q", RunStatus.QUEUED)
    await api_db.add_all([run])

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/runs/{run.id}/cancel",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_completed_run_returns_409(api_db: ApiDb) -> None:
    """A run already in a terminal state (PASS) must not be cancellable."""
    user = await api_db.seed_user(email="run-cancel-pass@example.com")
    ws = await api_db.member_workspace(user, slug="run-cancel-pass-ws")
    project, _ = await _seed_runnable_project(api_db, ws.id, slug="cancel-pass-p")
    run = _run_row(project.id, "RUN-CANCEL-PASS", RunStatus.PASS)
    await api_db.add_all([run])

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/runs/{run.id}/cancel",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 409
    assert "not cancellable" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_rerun_clones_selection_and_enqueues(api_db: ApiDb) -> None:
    """Rerun produces a NEW run id in QUEUED + invokes ARQ once with the new id."""
    user = await api_db.seed_user(email="run-rerun@example.com")
    ws = await api_db.member_workspace(user, slug="run-rerun-ws")
    project, case = await _seed_runnable_project(api_db, ws.id, slug="rerun-p")
    run = _run_row(
        project.id,
        "RUN-RERUN-SRC",
        RunStatus.FAIL,
        metadata_json={
            "selection": [{"case_id": case.id, "selected_step_ids": None}],
            "mcp_routing_override": None,
        },
    )
    await api_db.add_all([run])

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/runs/{run.id}/rerun",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "QUEUED"
    assert body["id"] != run.id
    assert len(arq.enqueued) == 1
    function, args, _ = arq.enqueued[0]
    assert function == "run_test_case"
    assert args == (body["id"],)

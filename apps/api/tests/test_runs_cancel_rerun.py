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
from suitest_db.models.run import Run, RunStep
from suitest_shared.domain.enums import (
    CaseSource,
    RunStatus,
    RunTrigger,
    StepOutcome,
    TargetKind,
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
        status=status,
        **kw,
    )


async def _seed_runnable_project(api_db: ApiDb, ws_id: str, slug: str) -> tuple[Project, TestCase]:
    """Seed a project + suite + case + bundled-mcp step so rerun can clone selection."""
    await api_db.seed_ready_llm(ws_id)
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


@pytest.mark.asyncio
async def test_rerun_failed_only_clones_only_failing_cases(api_db: ApiDb) -> None:
    """When failedOnly=true, the new run's selection contains only cases with FAIL/ERROR steps."""
    user = await api_db.seed_user(email="run-rerun-failed@example.com")
    ws = await api_db.member_workspace(user, slug="run-rerun-failed-ws")
    await api_db.seed_ready_llm(ws.id)
    project = Project(workspace_id=ws.id, slug="p-failed", name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    case1 = TestCase(
        suite_id=suite.id, public_id="TC-P1", name="Passing Case", source=CaseSource.MANUAL
    )
    case2 = TestCase(
        suite_id=suite.id, public_id="TC-F1", name="Failing Case", source=CaseSource.MANUAL
    )
    await api_db.add_all([case1, case2])

    run = _run_row(
        project.id,
        "RUN-RERUN-FAILED-SRC",
        RunStatus.FAIL,
        metadata_json={
            "selection": [
                {"case_id": case1.id, "selected_step_ids": None},
                {"case_id": case2.id, "selected_step_ids": None},
            ],
            "mcp_routing_override": None,
        },
    )
    await api_db.add_all([run])

    # Record passing step for case1 and failing step for case2
    step1 = RunStep(run_id=run.id, case_id=case1.id, step_order=0, outcome=StepOutcome.PASS)
    step2 = RunStep(run_id=run.id, case_id=case2.id, step_order=1, outcome=StepOutcome.FAIL)
    await api_db.add_all([step1, step2])

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/runs/{run.id}/rerun?failedOnly=true",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    new_run_id = body["id"]

    # Verify that the cloned run's metadata selection contains ONLY case2
    async with api_db.maker() as session:
        cloned = await session.get(Run, new_run_id)
        assert cloned is not None
        assert cloned.metadata_json is not None
        selection = cloned.metadata_json.get("selection", [])
        assert len(selection) == 1
        assert selection[0]["case_id"] == case2.id
        assert cloned.metadata_json.get("rerun_mode") == "failed_only"


@pytest.mark.asyncio
async def test_rerun_failed_only_no_failures_returns_400(api_db: ApiDb) -> None:
    """When a run has 0 failed cases, calling rerun with failedOnly=true returns 400 Bad Request."""
    user = await api_db.seed_user(email="run-rerun-nofail@example.com")
    ws = await api_db.member_workspace(user, slug="run-rerun-nofail-ws")
    project, case = await _seed_runnable_project(api_db, ws.id, slug="rerun-nofail-p")
    run = _run_row(
        project.id,
        "RUN-RERUN-NOFAIL-SRC",
        RunStatus.PASS,
        metadata_json={
            "selection": [{"case_id": case.id, "selected_step_ids": None}],
            "mcp_routing_override": None,
        },
    )
    await api_db.add_all([run])
    step = RunStep(run_id=run.id, case_id=case.id, step_order=0, outcome=StepOutcome.PASS)
    await api_db.add_all([step])

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/runs/{run.id}/rerun?failedOnly=true",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 400
    assert "No failed test cases" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_rerun_selective_case_ids_body(api_db: ApiDb) -> None:
    """When caseIds are passed in the JSON body, only those cases are cloned."""
    user = await api_db.seed_user(email="run-rerun-select@example.com")
    ws = await api_db.member_workspace(user, slug="run-rerun-select-ws")
    await api_db.seed_ready_llm(ws.id)
    project = Project(workspace_id=ws.id, slug="p-select", name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    case1 = TestCase(suite_id=suite.id, public_id="TC-S1", name="Case 1", source=CaseSource.MANUAL)
    case2 = TestCase(suite_id=suite.id, public_id="TC-S2", name="Case 2", source=CaseSource.MANUAL)
    await api_db.add_all([case1, case2])

    run = _run_row(
        project.id,
        "RUN-RERUN-SELECT-SRC",
        RunStatus.PASS,
        metadata_json={
            "selection": [
                {"case_id": case1.id, "selected_step_ids": None},
                {"case_id": case2.id, "selected_step_ids": None},
            ],
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
                json={"caseIds": [case2.id]},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    async with api_db.maker() as session:
        cloned = await session.get(Run, body["id"])
        assert cloned is not None
        assert cloned.metadata_json is not None
        selection = cloned.metadata_json.get("selection", [])
        assert len(selection) == 1
        assert cloned.metadata_json.get("rerun_mode") == "selective"
        assert cloned.name == "Ad-hoc: Case 2"


@pytest.mark.asyncio
async def test_rerun_selective_multiple_case_ids_name(api_db: ApiDb) -> None:
    """When >1 caseIds are passed in the JSON body, name is 'Ad-hoc: <N> selected cases'."""
    user = await api_db.seed_user(email="run-rerun-multi@example.com")
    ws = await api_db.member_workspace(user, slug="run-rerun-multi-ws")
    await api_db.seed_ready_llm(ws.id)
    project = Project(workspace_id=ws.id, slug="p-multi", name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    case1 = TestCase(suite_id=suite.id, public_id="TC-M1", name="Case 1", source=CaseSource.MANUAL)
    case2 = TestCase(suite_id=suite.id, public_id="TC-M2", name="Case 2", source=CaseSource.MANUAL)
    await api_db.add_all([case1, case2])

    run = _run_row(
        project.id,
        "Original Run Name",
        RunStatus.PASS,
        metadata_json={
            "selection": [
                {"case_id": case1.id, "selected_step_ids": None},
                {"case_id": case2.id, "selected_step_ids": None},
            ],
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
                json={"caseIds": [case1.id, case2.id]},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    async with api_db.maker() as session:
        cloned = await session.get(Run, body["id"])
        assert cloned is not None
        assert cloned.name == "Ad-hoc: 2 selected cases"


@pytest.mark.asyncio
async def test_rerun_selective_rejects_foreign_case_id(api_db: ApiDb) -> None:
    """When a caseId belongs to a different project, selective rerun returns 400."""
    user = await api_db.seed_user(email="run-rerun-foreign@example.com")
    ws = await api_db.member_workspace(user, slug="run-rerun-foreign-ws")
    await api_db.seed_ready_llm(ws.id)

    project1 = Project(workspace_id=ws.id, slug="p-1", name="P1")
    project2 = Project(workspace_id=ws.id, slug="p-2", name="P2")
    await api_db.add_all([project1, project2])

    suite1 = Suite(project_id=project1.id, name="S1", order=0)
    suite2 = Suite(project_id=project2.id, name="S2", order=0)
    await api_db.add_all([suite1, suite2])

    case1 = TestCase(suite_id=suite1.id, public_id="TC-F1", name="Case 1", source=CaseSource.MANUAL)
    case_foreign = TestCase(
        suite_id=suite2.id, public_id="TC-F2", name="Foreign Case", source=CaseSource.MANUAL
    )
    await api_db.add_all([case1, case_foreign])

    run = _run_row(
        project1.id,
        "Run in P1",
        RunStatus.PASS,
        metadata_json={
            "selection": [{"case_id": case1.id, "selected_step_ids": None}],
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
                json={"caseIds": [case_foreign.id]},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 400, resp.text
    assert f"case {case_foreign.id} not in project" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_historical_immutability_snapshot(api_db: ApiDb) -> None:
    """Run details use snapshot planned_cases so future step modifications do not alter history."""
    user = await api_db.seed_user(email="run-snapshot@example.com")
    ws = await api_db.member_workspace(user, slug="run-snapshot-ws")
    await api_db.seed_ready_llm(ws.id)
    project = Project(workspace_id=ws.id, slug="p-snap", name="Snapshot Project")
    await api_db.add_all([project])

    suite = Suite(project_id=project.id, name="Suite Snap", order=0)
    await api_db.add_all([suite])

    case = TestCase(
        suite_id=suite.id, public_id="TC-SNAP", name="Snapshot Case", source=CaseSource.MANUAL
    )
    await api_db.add_all([case])

    # Case originally has 2 steps
    step1 = TestStep(case_id=case.id, order=0, action="Step 1", expected="Passed")
    step2 = TestStep(case_id=case.id, order=1, action="Step 2", expected="Passed")
    await api_db.add_all([step1, step2])

    # Create run via API
    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            create_resp = await c.post(
                "/api/v1/runs",
                json={
                    "projectId": project.id,
                    "name": "snapshot test run",
                    "selection": [{"caseId": case.id}],
                },
                headers={"X-Workspace-Id": ws.id},
            )
            assert create_resp.status_code == 202, create_resp.text
            run_id = create_resp.json()["id"]

            # Add step 3 to the test case (simulating future user edit)
            step3 = TestStep(
                case_id=case.id, order=2, action="Step 3 added in future", expected="Passed"
            )
            await api_db.add_all([step3])

            # Fetch run details - must still report total_steps = 2 from snapshot!
            get_resp = await c.get(
                f"/api/v1/runs/{run_id}",
                headers={"X-Workspace-Id": ws.id},
            )
            assert get_resp.status_code == 200, get_resp.text
            cases = get_resp.json()["cases"]
            assert len(cases) == 1
            assert cases[0]["total_steps"] == 2

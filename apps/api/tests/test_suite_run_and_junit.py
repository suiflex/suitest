"""Integration tests for the suite-run + JUnit report endpoints (#2).

* ``POST /api/v1/suites/{suite_id}/run`` — derive the selection from the suite's
  active cases, create one bundle run, enqueue the ARQ job (recording stub).
* ``GET /api/v1/runs/{run_id}/report.junit`` — render a run's persisted steps as
  JUnit XML for CI consumption.

Mirrors the seeding / ARQ-stub / ASGI-lifespan pattern in ``test_runs_create.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from xml.etree.ElementTree import fromstring

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from suitest_api.deps.arq import get_arq
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run, RunStep
from suitest_db.public_id import set_workspace_id
from suitest_shared.domain.enums import (
    CaseSource,
    RunStatus,
    RunTrigger,
    StepOutcome,
    TargetKind,
    Tier,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


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


async def _seed_suite_with_cases(
    api_db: ApiDb, ws_id: str, *, slug: str, n_cases: int
) -> tuple[Project, Suite, list[TestCase]]:
    """Seed a project + suite + ``n_cases`` active cases, each with one bundled step."""
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="Smoke Suite", order=0)
    await api_db.add_all([suite])
    cases: list[TestCase] = []
    for i in range(n_cases):
        case = TestCase(
            suite_id=suite.id,
            public_id=f"TC-{slug}-{i + 1}",
            name=f"case {i + 1}",
            source=CaseSource.MANUAL,
            order_in_suite=i,
        )
        await api_db.add_all([case])
        await api_db.add_all(
            [
                TestStep(
                    case_id=case.id,
                    order=1,
                    action="GET /ping",
                    expected="200",
                    mcp_provider="api-http-mcp",
                    target_kind=TargetKind.BE_REST,
                )
            ]
        )
        cases.append(case)
    return project, suite, cases


@pytest.mark.asyncio
async def test_suite_run_creates_bundle_and_enqueues(api_db: ApiDb) -> None:
    """202, name defaults to the suite name, ARQ enqueued once with run_test_case."""
    user = await api_db.seed_user(email="suite-run-ok@example.com")
    ws = await api_db.member_workspace(user, slug="suite-run-ok-ws")
    _project, suite, _cases = await _seed_suite_with_cases(
        api_db, ws.id, slug="suite-run-ok-p", n_cases=2
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/suites/{suite.id}/run",
                json={"env": "staging"},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "QUEUED"
    assert body["name"] == "Smoke Suite"  # defaulted from the suite name
    assert body["publicId"].startswith("R-")
    assert len(arq.enqueued) == 1
    function, args, _kwargs = arq.enqueued[0]
    assert function == "run_test_case"
    assert args == (body["id"],)


@pytest.mark.asyncio
async def test_suite_run_empty_suite_returns_400(api_db: ApiDb) -> None:
    """A suite with no active cases → 400, no ARQ enqueue."""
    user = await api_db.seed_user(email="suite-run-empty@example.com")
    ws = await api_db.member_workspace(user, slug="suite-run-empty-ws")
    project = Project(workspace_id=ws.id, slug="suite-run-empty-p", name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="Empty", order=0)
    await api_db.add_all([suite])

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/suites/{suite.id}/run",
                json={},
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 400
    assert "no active cases" in resp.json()["detail"]
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_suite_run_cross_workspace_returns_400(api_db: ApiDb) -> None:
    """A suite id from another workspace looks like 'not found' (400)."""
    owner = await api_db.seed_user(email="suite-run-owner@example.com")
    ws_a = await api_db.member_workspace(owner, slug="suite-run-a-ws")
    _project, suite, _cases = await _seed_suite_with_cases(
        api_db, ws_a.id, slug="suite-run-a-p", n_cases=1
    )
    other = await api_db.seed_user(email="suite-run-other@example.com")
    ws_b = await api_db.member_workspace(other, slug="suite-run-b-ws")

    arq = _RecordingArq()
    app = api_db.app_for(other)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/suites/{suite.id}/run",
                json={},
                headers={"X-Workspace-Id": ws_b.id},
            )
    assert resp.status_code == 400
    assert "suite not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_run_junit_report_rolls_up_steps(api_db: ApiDb) -> None:
    """JUnit XML reflects a run's steps: 1 case, 1 failure, application/xml."""
    user = await api_db.seed_user(email="junit-ok@example.com")
    ws = await api_db.member_workspace(user, slug="junit-ok-ws")
    _project, _suite, cases = await _seed_suite_with_cases(
        api_db, ws.id, slug="junit-ok-p", n_cases=1
    )
    case = cases[0]

    run = Run(
        project_id=_project.id,
        name="ci-run",
        env="staging",
        trigger=RunTrigger.MANUAL,
        status=RunStatus.FAIL,
        tier_at_runtime=Tier.ZERO,
    )
    set_workspace_id(run, ws.id)
    await api_db.add_all([run])
    await api_db.add_all(
        [
            RunStep(
                run_id=run.id,
                case_id=case.id,
                step_order=1,
                outcome=StepOutcome.PASS,
                duration_ms=100,
            ),
            RunStep(
                run_id=run.id,
                case_id=case.id,
                step_order=2,
                outcome=StepOutcome.FAIL,
                duration_ms=50,
                error_message="expected 200 got 500",
            ),
        ]
    )

    app = api_db.app_for(user)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                f"/api/v1/runs/{run.id}/report.junit",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/xml")
    root = fromstring(resp.text)
    assert root.tag == "testsuites"
    assert root.attrib["tests"] == "1"
    assert root.attrib["failures"] == "1"
    assert root.attrib["errors"] == "0"
    assert root.attrib["time"] == "0.150"
    failure = root.find("./testsuite/testcase/failure")
    assert failure is not None
    assert failure.attrib["message"] == "expected 200 got 500"


@pytest.mark.asyncio
async def test_run_junit_report_cross_workspace_404(api_db: ApiDb) -> None:
    """A run id from another workspace → 404."""
    owner = await api_db.seed_user(email="junit-owner@example.com")
    ws_a = await api_db.member_workspace(owner, slug="junit-a-ws")
    project, _suite, _cases = await _seed_suite_with_cases(
        api_db, ws_a.id, slug="junit-a-p", n_cases=1
    )
    run = Run(
        project_id=project.id,
        name="ci-run",
        env="staging",
        trigger=RunTrigger.MANUAL,
        status=RunStatus.PASS,
        tier_at_runtime=Tier.ZERO,
    )
    set_workspace_id(run, ws_a.id)
    await api_db.add_all([run])

    other = await api_db.seed_user(email="junit-other@example.com")
    ws_b = await api_db.member_workspace(other, slug="junit-b-ws")
    app = api_db.app_for(other)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                f"/api/v1/runs/{run.id}/report.junit",
                headers={"X-Workspace-Id": ws_b.id},
            )
    assert resp.status_code == 404

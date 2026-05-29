"""Tests for ``POST /api/v1/runs`` (M1c Task 15).

The four scenarios cover the happy-path contract + the three validation
branches that produce 400:

* 202 + serialized run row with tier ZERO (default capability path),
* unknown project id → 400 ``"project not found"``,
* a TestStep referencing a non-bundled MCP provider that the workspace has
  not registered → 400 ``"unregistered MCP"``,
* ARQ enqueue is invoked with ``("run_test_case", run.id)`` against the
  ``suitest:runs`` queue — a recording :class:`ArqRedis` stub is injected via
  ``app.dependency_overrides[get_arq]`` so the create handler never opens a
  real broker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from suitest_api.deps.arq import get_arq
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource, TargetKind

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Recording ARQ stub
# ---------------------------------------------------------------------------


@dataclass
class _RecordingJob:
    """Minimal :class:`arq.jobs.Job` stand-in carrying just the id ``attach_arq_job_id`` needs."""

    job_id: str


@dataclass
class _RecordingArq:
    """Captures every ``enqueue_job`` call. Returns a synthetic job id per call."""

    enqueued: list[tuple[str, tuple[object, ...], dict[str, object]]] = field(default_factory=list)

    async def enqueue_job(self, function: str, *args: object, **kwargs: object) -> _RecordingJob:
        self.enqueued.append((function, args, kwargs))
        return _RecordingJob(job_id=f"job-{len(self.enqueued)}")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _seed_project_case(
    api_db: ApiDb,
    ws_id: str,
    *,
    mcp_provider: str = "api-http-mcp",
    slug: str = "p1",
    case_public_id: str = "TC-RC1",
) -> tuple[Project, TestCase]:
    """Seed a project + suite + case + one step bound to ``mcp_provider``."""
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(
        suite_id=suite.id,
        public_id=case_public_id,
        name="c",
        source=CaseSource.MANUAL,
    )
    await api_db.add_all([case])
    step = TestStep(
        case_id=case.id,
        order=1,
        action="GET /ping",
        expected="200",
        mcp_provider=mcp_provider,
        target_kind=TargetKind.BE_REST,
    )
    await api_db.add_all([step])
    return project, case


def _override_arq(app: Any, arq: _RecordingArq) -> None:
    """Replace the ``get_arq`` dependency on a built app with a recording stub."""

    async def _get_recording_arq() -> _RecordingArq:
        return arq

    app.dependency_overrides[get_arq] = _get_recording_arq


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_run_returns_202_with_zero_tier(api_db: ApiDb) -> None:
    """Happy path: 202, RunPublic with QUEUED + ZERO tier, ARQ enqueue invoked."""
    user = await api_db.seed_user(email="run-create-ok@example.com")
    ws = await api_db.member_workspace(user, slug="run-create-ok-ws")
    project, case = await _seed_project_case(api_db, ws.id, slug="run-create-ok-p")

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/runs",
                json={
                    "projectId": project.id,
                    "name": "nightly",
                    "selection": [{"caseId": case.id}],
                    "env": "staging",
                },
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["projectId"] == project.id
    assert body["status"] == "QUEUED"
    assert body["tierAtRuntime"] == "ZERO"
    assert body["name"] == "nightly"
    assert body["publicId"].startswith("R-")


@pytest.mark.asyncio
async def test_create_run_unknown_project_returns_400(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="run-create-nopro@example.com")
    ws = await api_db.member_workspace(user, slug="run-create-nopro-ws")

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/runs",
                json={
                    "projectId": "proj_does_not_exist",
                    "name": "x",
                    "selection": [{"caseId": "case_x"}],
                },
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 400
    assert "project not found" in resp.json()["detail"]
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_create_run_unknown_mcp_returns_400(api_db: ApiDb) -> None:
    """A step pointing at a non-bundled, non-registered provider → 400."""
    user = await api_db.seed_user(email="run-create-nomcp@example.com")
    ws = await api_db.member_workspace(user, slug="run-create-nomcp-ws")
    project, case = await _seed_project_case(
        api_db,
        ws.id,
        mcp_provider="acme-custom-mcp",  # not bundled, not registered for this ws
        slug="run-create-nomcp-p",
        case_public_id="TC-RC2",
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/runs",
                json={
                    "projectId": project.id,
                    "name": "x",
                    "selection": [{"caseId": case.id}],
                },
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 400
    assert "unregistered MCP" in resp.json()["detail"]
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_create_run_enqueues_arq_job(api_db: ApiDb) -> None:
    """ARQ enqueue must be invoked with ``run_test_case`` + the new run id."""
    user = await api_db.seed_user(email="run-create-arq@example.com")
    ws = await api_db.member_workspace(user, slug="run-create-arq-ws")
    project, case = await _seed_project_case(
        api_db, ws.id, slug="run-create-arq-p", case_public_id="TC-RC3"
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/runs",
                json={
                    "projectId": project.id,
                    "name": "from-test",
                    "selection": [{"caseId": case.id}],
                },
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202
    run_id = resp.json()["id"]
    assert len(arq.enqueued) == 1
    function, args, kwargs = arq.enqueued[0]
    assert function == "run_test_case"
    assert args == (run_id,)
    assert kwargs.get("_queue_name") == "suitest:runs"

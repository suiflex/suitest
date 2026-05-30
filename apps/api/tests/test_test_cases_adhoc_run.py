"""M1d-8 — ``POST /api/v1/test-cases/:id/run`` ad-hoc run shortcut tests.

Covers the contract from ``docs/API.md §3.3`` line 204 + plan-05b task M1d-8:

* Happy path: 202 + ``{runId, publicId, statusUrl, wsRoom}`` payload + the run
  row actually lands with ``trigger=MANUAL``, the right project_id, and a
  ``selection`` referencing the case.
* Pre-flight ZERO + strict + missing ``code`` → 400
  ``STEPS_REQUIRE_CODE_IN_ZERO_LLM`` with ``details.stepIndex`` and NO ``runs``
  row written.
* Pre-flight unregistered MCP → 404 ``MCP_PROVIDER_NOT_REGISTERED`` and NO
  ``runs`` row written.
* Cross-workspace case id → 404 (no enumeration oracle).
* Soft-deleted case → 404 (same shape).
* VIEWER → 403 (role gate matches the other write endpoints).

The ARQ broker is replaced with a recording stub (lifted from
``test_runs_create``) so the test never opens a real Redis connection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from suitest_api.deps.arq import get_arq
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run
from suitest_shared.domain.enums import (
    AutonomyLevel,
    CaseSource,
    Role,
    RunTrigger,
    TargetKind,
    Tier,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Recording ARQ stub (mirrors ``test_runs_create``)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_runnable_case(
    api_db: ApiDb,
    ws_id: str,
    *,
    slug: str = "adhoc-p",
    case_public_id: str = "TC-AH1",
    code: str | None = "await page.goto('/login');",
    mcp_provider: str = "playwright-mcp",
) -> tuple[Project, Suite, TestCase, TestStep]:
    """Seed a project + suite + case + ONE step pointing at a bundled MCP.

    By default the step carries ``code`` (so ZERO + strict_zero_validation
    passes); individual tests override ``code=None`` / a custom ``mcp_provider``
    to exercise the pre-flight validator branches.
    """
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    case = TestCase(
        suite_id=suite.id,
        public_id=case_public_id,
        name="Login flow",
        source=CaseSource.MANUAL,
    )
    await api_db.add_all([case])
    step = TestStep(
        case_id=case.id,
        order=0,
        action="Open /login",
        expected="Login form visible",
        code=code,
        mcp_provider=mcp_provider,
        target_kind=TargetKind.FE_WEB,
    )
    await api_db.add_all([step])
    return project, suite, case, step


async def _runs_count(api_db: ApiDb) -> int:
    async with api_db.maker() as session:
        return int(await session.scalar(select(func.count()).select_from(Run)) or 0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adhoc_run_returns_202_with_runId_publicId_statusUrl_wsRoom(
    api_db: ApiDb,
) -> None:
    """Happy path: 202 + the four FE-contract fields + run actually queued."""
    user = await api_db.seed_user(email="adhoc-ok@example.com")
    ws = await api_db.member_workspace(user, slug="adhoc-ok-ws")
    project, _suite, case, _step = await _seed_runnable_case(api_db, ws.id, slug="adhoc-ok-p")

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/test-cases/{case.id}/run",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert set(body) == {"runId", "publicId", "statusUrl", "wsRoom"}
    assert body["publicId"].startswith("R-")
    assert body["statusUrl"] == f"/runs/{body['publicId']}"
    assert body["wsRoom"] == f"run:{body['runId']}"

    # Verify the run row landed with the right shape.
    async with api_db.maker() as session:
        run = (await session.scalars(select(Run))).one()
    assert run.id == body["runId"]
    assert run.project_id == project.id
    assert run.trigger == RunTrigger.MANUAL
    assert run.name == "Ad-hoc: Login flow"
    selection = run.metadata_json["selection"] if run.metadata_json else None
    assert selection == [{"case_id": case.id}]

    # ARQ enqueue invoked with the new run id.
    assert len(arq.enqueued) == 1
    function, args, kwargs = arq.enqueued[0]
    assert function == "run_test_case"
    assert args == (run.id,)
    assert kwargs.get("_queue_name") == "suitest:runs"


@pytest.mark.asyncio
async def test_adhoc_run_zero_tier_missing_code_returns_400_no_run_created(
    api_db: ApiDb,
) -> None:
    """ZERO + strict + step.code missing → 400 with stepIndex AND zero Run rows."""
    user = await api_db.seed_user(email="adhoc-zero@example.com")
    ws = await api_db.member_workspace(user, slug="adhoc-zero-ws")
    _, _, case, _ = await _seed_runnable_case(
        api_db, ws.id, slug="adhoc-zero-p", case_public_id="TC-AH2", code=None
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/test-cases/{case.id}/run",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 400, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "STEPS_REQUIRE_CODE_IN_ZERO_LLM"
    assert envelope["details"]["stepIndex"] == 0

    # Pre-flight failure → no Run row, no ARQ enqueue.
    assert await _runs_count(api_db) == 0
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_adhoc_run_unregistered_mcp_returns_404_no_run_created(
    api_db: ApiDb,
) -> None:
    """Unregistered MCP on a step → 404 ``MCP_PROVIDER_NOT_REGISTERED`` + no Run."""
    user = await api_db.seed_user(email="adhoc-nomcp@example.com")
    ws = await api_db.member_workspace(user, slug="adhoc-nomcp-ws")
    _, _, case, _ = await _seed_runnable_case(
        api_db,
        ws.id,
        slug="adhoc-nomcp-p",
        case_public_id="TC-AH3",
        mcp_provider="acme-custom-mcp",
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/test-cases/{case.id}/run",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 404, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "MCP_PROVIDER_NOT_REGISTERED"
    assert envelope["details"]["name"] == "acme-custom-mcp"

    assert await _runs_count(api_db) == 0
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_adhoc_run_cross_workspace_returns_404(api_db: ApiDb) -> None:
    """Case lives in a different workspace → 404 (no enumeration oracle)."""
    user = await api_db.seed_user(email="adhoc-xws@example.com")
    ws = await api_db.member_workspace(user, slug="adhoc-xws-ws")
    other = await api_db.seed_workspace(slug="adhoc-xws-other", name="Other")
    _, _, case, _ = await _seed_runnable_case(
        api_db, other.id, slug="adhoc-xws-other-p", case_public_id="TC-AH4"
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/test-cases/{case.id}/run",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 404
    assert await _runs_count(api_db) == 0


@pytest.mark.asyncio
async def test_adhoc_run_soft_deleted_case_returns_404(api_db: ApiDb) -> None:
    """A tombstoned case is invisible to the ad-hoc run shortcut."""
    user = await api_db.seed_user(email="adhoc-deleted@example.com")
    ws = await api_db.member_workspace(user, slug="adhoc-deleted-ws")
    _, _, case, _ = await _seed_runnable_case(
        api_db, ws.id, slug="adhoc-deleted-p", case_public_id="TC-AH5"
    )

    # Tombstone the case directly via the session — no soft-delete endpoint
    # exists in the M1d-8 cut, so set the column.
    from datetime import UTC, datetime

    from sqlalchemy import update

    async with api_db.maker() as session:
        await session.execute(
            update(TestCase).where(TestCase.id == case.id).values(deleted_at=datetime.now(UTC))
        )
        await session.commit()

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/test-cases/{case.id}/run",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 404
    assert await _runs_count(api_db) == 0


@pytest.mark.asyncio
async def test_adhoc_run_viewer_returns_403(api_db: ApiDb) -> None:
    """VIEWER role is read-only and must NOT trigger ad-hoc runs."""
    user = await api_db.seed_user(email="adhoc-viewer@example.com")
    ws = await api_db.seed_workspace(slug="adhoc-viewer-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    _, _, case, _ = await _seed_runnable_case(
        api_db, ws.id, slug="adhoc-viewer-p", case_public_id="TC-AH6"
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/test-cases/{case.id}/run",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 403
    assert await _runs_count(api_db) == 0


@pytest.mark.asyncio
async def test_adhoc_run_cloud_tier_allows_action_only_step(api_db: ApiDb) -> None:
    """CLOUD tier overlay → pre-flight permits an action-only step (no ``code``).

    Guards against a regression where the ad-hoc pre-flight forgets to inherit
    the workspace tier (defaulting to ZERO+strict would 400 here).
    """
    from suitest_db.models.workspace_capability import WorkspaceCapability

    user = await api_db.seed_user(email="adhoc-cloud@example.com")
    ws = await api_db.member_workspace(user, slug="adhoc-cloud-ws")
    await api_db.add_all(
        [
            WorkspaceCapability(
                workspace_id=ws.id,
                tier=Tier.CLOUD,
                autonomy_level=AutonomyLevel.MANUAL,
                features_json={},
            )
        ]
    )
    _, _, case, _ = await _seed_runnable_case(
        api_db, ws.id, slug="adhoc-cloud-p", case_public_id="TC-AH7", code=None
    )

    arq = _RecordingArq()
    app = api_db.app_for(user)
    _override_arq(app, arq)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/test-cases/{case.id}/run",
                headers={"X-Workspace-Id": ws.id},
            )
    assert resp.status_code == 202, resp.text
    assert await _runs_count(api_db) == 1

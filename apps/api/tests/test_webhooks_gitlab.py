"""Tests for ``POST /api/v1/webhooks/gitlab`` (M1d-17).

Covers the eight scenarios spelled out in plan-05b §M1d-17 plus an extra audit
log assertion. Wiring follows the same pattern as ``test_runs_create``: a
recording ``_RecordingArq`` stub is injected via
``app.dependency_overrides[get_arq]``, and the dedup Redis dep is overridden
with a ``fakeredis`` instance so the receiver never opens a real broker.
"""

# mypy: warn_unused_ignores=False
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import fakeredis
import fakeredis.aioredis
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from suitest_api.deps.arq import get_arq
from suitest_api.deps.dedup_redis import get_dedup_redis
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.integration import Integration
from suitest_db.models.project import Project, Suite
from suitest_db.models.run import Run
from suitest_shared.domain.enums import (
    CaseSource,
    IntegrationKind,
    RunTrigger,
    TargetKind,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


_VALID_TOKEN = "glabtoken-secret-fixture"
_WRONG_TOKEN = "glabtoken-wrong-fixture"


# ---------------------------------------------------------------------------
# Recording ARQ stub (clone of test_runs_create._RecordingArq)
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


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


@dataclass
class _Seeded:
    workspace_id: str
    project: Project
    suite: Suite
    case: TestCase
    integration: Integration


async def _seed(
    api_db: ApiDb,
    *,
    slug: str,
    case_public_id: str,
    token: str = _VALID_TOKEN,
    with_smoke_tag: bool = True,
    pin_gating_suite: bool = False,
    integration_kind: IntegrationKind = IntegrationKind.GITLAB,
) -> _Seeded:
    """Create a workspace + project + suite + case + GitLab integration."""
    user = await api_db.seed_user(email=f"{slug}@example.com")
    ws = await api_db.member_workspace(user, slug=slug)
    project = Project(workspace_id=ws.id, slug=f"{slug}-p", name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    if pin_gating_suite:
        async with api_db.maker() as session:
            row = await session.get(Project, project.id)
            assert row is not None
            row.gating_suite_id = suite.id
            await session.commit()
            await session.refresh(row)
            project = row
    case = TestCase(suite_id=suite.id, public_id=case_public_id, name="c", source=CaseSource.MANUAL)
    await api_db.add_all([case])
    step = TestStep(
        case_id=case.id,
        order=1,
        action="GET /ping",
        expected="200",
        mcp_provider="api-http-mcp",
        target_kind=TargetKind.BE_REST,
    )
    await api_db.add_all([step])
    if with_smoke_tag:
        await api_db.add_all([CaseTag(case_id=case.id, tag="smoke")])

    integration = Integration(
        workspace_id=ws.id,
        kind=integration_kind,
        name="GitLab",
        config={"local_project_id": project.id},
        secrets_encrypted=token,
    )
    await api_db.add_all([integration])
    return _Seeded(
        workspace_id=ws.id,
        project=project,
        suite=suite,
        case=case,
        integration=integration,
    )


def _push_payload(branch: str = "main", commit_sha: str = "a" * 40) -> dict[str, Any]:
    return {
        "object_kind": "push",
        "ref": f"refs/heads/{branch}",
        "before": "0" * 40,
        "after": commit_sha,
        "project_id": 12345,
        "project": {
            "id": 12345,
            "path_with_namespace": "group/sample",
            "web_url": "https://gitlab.example/group/sample",
        },
        "commits": [
            {
                "id": commit_sha,
                "message": "feat: change",
                "timestamp": "2026-05-30T10:00:00Z",
                "url": "https://gitlab.example/group/sample/-/commit/" + commit_sha,
            }
        ],
    }


def _mr_payload(
    action: str, iid: int = 42, commit_sha: str = "b" * 40, branch: str = "feature/x"
) -> dict[str, Any]:
    return {
        "object_kind": "merge_request",
        "project": {"id": 12345, "path_with_namespace": "group/sample"},
        "object_attributes": {
            "iid": iid,
            "action": action,
            "source_branch": branch,
            "target_branch": "main",
            "last_commit": {"id": commit_sha, "message": "wip"},
        },
    }


def _build_app(api_db: ApiDb, *, user: Any, arq: _RecordingArq, redis: Any) -> Any:
    app = api_db.app_for(user)

    async def _override_arq() -> _RecordingArq:
        return arq

    async def _override_redis() -> Any:
        return redis

    app.dependency_overrides[get_arq] = _override_arq
    app.dependency_overrides[get_dedup_redis] = _override_redis
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gitlab_push_hook_valid_token_enqueues_run(api_db: ApiDb) -> None:
    """Push Hook with the right token returns 202 + run details and enqueues ARQ."""
    await _seed(api_db, slug="gl-push-ok", case_public_id="TC-GL1")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)

    app = _build_app(api_db, user=None, arq=arq, redis=redis)
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(),
                headers={"X-Gitlab-Token": _VALID_TOKEN, "X-Gitlab-Event": "Push Hook"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["publicId"].startswith("R-")
    assert body["statusUrl"].startswith("/api/v1/runs/")
    assert arq.enqueued and arq.enqueued[0][0] == "run_test_case"


@pytest.mark.asyncio
async def test_gitlab_token_mismatch_returns_401_constant_time(api_db: ApiDb) -> None:
    """Wrong X-Gitlab-Token → 401 even though the workspace exists."""
    await _seed(api_db, slug="gl-401-mismatch", case_public_id="TC-GL2")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(),
                headers={"X-Gitlab-Token": _WRONG_TOKEN, "X-Gitlab-Event": "Push Hook"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 401
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_gitlab_unsigned_returns_401(api_db: ApiDb) -> None:
    """Missing X-Gitlab-Token header → 401."""
    await _seed(api_db, slug="gl-unsigned", case_public_id="TC-GL3")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(),
                headers={"X-Gitlab-Event": "Push Hook"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["open", "reopen", "update"])
async def test_gitlab_merge_request_opened_reopened_updated_enqueues_run(
    api_db: ApiDb, action: str
) -> None:
    """MR Hook with open/reopen/update enqueues a run, MR iid lands on audit metadata."""
    await _seed(api_db, slug=f"gl-mr-{action}", case_public_id=f"TC-MR-{action[:1].upper()}")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_mr_payload(action),
                headers={
                    "X-Gitlab-Token": _VALID_TOKEN,
                    "X-Gitlab-Event": "Merge Request Hook",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["runId"]
    # Verify the audit metadata captured merge_request_iid
    async with api_db.maker() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "webhook.gitlab.received")
            )
        ).all()
    assert rows, "audit row must be written"
    md = rows[0].metadata_json or {}
    assert md.get("merge_request_iid") == 42
    assert md.get("event") == "Merge Request Hook"


@pytest.mark.asyncio
async def test_gitlab_unknown_event_kind_returns_200_no_run(api_db: ApiDb) -> None:
    """An unsupported event header returns 200 ignored with no run enqueued."""
    await _seed(api_db, slug="gl-unknown-evt", case_public_id="TC-GL5")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json={"object_kind": "wiki_page"},
                headers={
                    "X-Gitlab-Token": _VALID_TOKEN,
                    "X-Gitlab-Event": "Wiki Page Hook",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "unsupported_event"}
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_gitlab_no_gating_returns_200_ignored_true_reason_no_gating_suite(
    api_db: ApiDb,
) -> None:
    """Project with no gating_suite_id and no smoke-tagged cases → 200 ignored."""
    await _seed(
        api_db,
        slug="gl-no-gating",
        case_public_id="TC-GL6",
        with_smoke_tag=False,
        pin_gating_suite=False,
    )

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(),
                headers={"X-Gitlab-Token": _VALID_TOKEN, "X-Gitlab-Event": "Push Hook"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "no_gating_suite"}
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_gitlab_redis_setnx_dedup_60s_second_call_no_op(api_db: ApiDb) -> None:
    """Two pushes with the same commit within the TTL → only the first enqueues a run."""
    await _seed(api_db, slug="gl-dedup", case_public_id="TC-GL7")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            first = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(commit_sha="c" * 40),
                headers={"X-Gitlab-Token": _VALID_TOKEN, "X-Gitlab-Event": "Push Hook"},
            )
            second = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(commit_sha="c" * 40),
                headers={"X-Gitlab-Token": _VALID_TOKEN, "X-Gitlab-Event": "Push Hook"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert first.status_code == 202, first.text
    assert second.status_code == 200
    assert second.json()["reason"] == "duplicate"
    assert len(arq.enqueued) == 1


@pytest.mark.asyncio
async def test_gitlab_per_workspace_token_lookup(api_db: ApiDb) -> None:
    """A token registered on workspace A cannot enqueue a run on workspace B's project."""
    a = await _seed(api_db, slug="gl-ws-a", case_public_id="TC-WSA", token=_VALID_TOKEN)
    # Workspace B has its own integration with a *different* token; A's token
    # must not satisfy B's lookup. We don't need to actually hit B — just
    # confirm A's token only resolves to A's workspace.
    await _seed(
        api_db,
        slug="gl-ws-b",
        case_public_id="TC-WSB",
        token="other-tenant-token",
    )

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(commit_sha="d" * 40),
                headers={"X-Gitlab-Token": _VALID_TOKEN, "X-Gitlab-Event": "Push Hook"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202, resp.text
    # The enqueued run must belong to workspace A's project, not B's.
    run_id = resp.json()["runId"]
    async with api_db.maker() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.project_id == a.project.id


@pytest.mark.asyncio
async def test_gitlab_audit_row_written(api_db: ApiDb) -> None:
    """A successful webhook receipt writes a ``webhook.gitlab.received`` audit row."""
    seeded = await _seed(api_db, slug="gl-audit", case_public_id="TC-GLAUD")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(branch="main", commit_sha="e" * 40),
                headers={"X-Gitlab-Token": _VALID_TOKEN, "X-Gitlab-Event": "Push Hook"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202
    async with api_db.maker() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "webhook.gitlab.received",
                    AuditLog.workspace_id == seeded.workspace_id,
                )
            )
        ).all()
    assert len(rows) == 1
    md = rows[0].metadata_json or {}
    assert md.get("integration_id") == seeded.integration.id
    assert md.get("branch") == "main"
    assert md.get("commit_sha") == "e" * 40
    assert md.get("event") == "Push Hook"


@pytest.mark.asyncio
async def test_gitlab_run_trigger_recorded_as_webhook(api_db: ApiDb) -> None:
    """Enqueued run carries ``trigger=WEBHOOK`` and ``triggered_by='webhook:gitlab'``."""
    await _seed(api_db, slug="gl-trigger", case_public_id="TC-GLTRG")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/gitlab",
                json=_push_payload(commit_sha="f" * 40),
                headers={"X-Gitlab-Token": _VALID_TOKEN, "X-Gitlab-Event": "Push Hook"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202
    run_id = resp.json()["runId"]
    async with api_db.maker() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        assert run.trigger == RunTrigger.WEBHOOK
        assert run.triggered_by == "webhook:gitlab"

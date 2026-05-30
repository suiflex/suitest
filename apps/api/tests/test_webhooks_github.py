"""Tests for ``POST /api/v1/webhooks/github`` (M1d-16).

Covers the matrix spelled out in plan-05b §M1d-16: ping, push happy-path,
HMAC mismatches (wrong + missing), the three triggering PR actions, PR
``closed`` ignored, unknown repo 404, duplicate within 60 s ignored, distinct
runs across push vs. PR head, and the audit row write.

Wiring mirrors ``test_webhooks_gitlab``: a recording ``_RecordingArq`` stub
replaces the ARQ dep, and ``fakeredis.aioredis`` replaces the dedup Redis
dep so the receiver never opens a real broker.
"""

# mypy: warn_unused_ignores=False
from __future__ import annotations

import hashlib
import hmac
import json
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


_VALID_SECRET = "ghsec-fixture-shhh"
_WRONG_SECRET = "ghsec-wrong-fixture"
_REPO_FULL_NAME = "octo/sample"


# ---------------------------------------------------------------------------
# Recording ARQ stub
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
    secret: str = _VALID_SECRET,
    repo: str = _REPO_FULL_NAME,
    with_smoke_tag: bool = True,
    pin_gating_suite: bool = False,
    integration_kind: IntegrationKind = IntegrationKind.GITHUB,
) -> _Seeded:
    """Create a workspace + project + suite + case + GitHub integration."""
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
        name="GitHub",
        config={"local_project_id": project.id, "github_repo": repo},
        secrets_encrypted=secret,
    )
    await api_db.add_all([integration])
    return _Seeded(
        workspace_id=ws.id,
        project=project,
        suite=suite,
        case=case,
        integration=integration,
    )


def _sign(body: bytes, *, secret: str = _VALID_SECRET) -> str:
    """Compute the ``X-Hub-Signature-256`` header value for ``body``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _push_payload(
    *, branch: str = "main", commit_sha: str = "a" * 40, repo: str = _REPO_FULL_NAME
) -> dict[str, Any]:
    return {
        "ref": f"refs/heads/{branch}",
        "before": "0" * 40,
        "after": commit_sha,
        "deleted": False,
        "repository": {
            "id": 9876,
            "full_name": repo,
            "name": repo.split("/")[-1],
        },
    }


def _pr_payload(
    *,
    action: str,
    number: int = 7,
    commit_sha: str = "b" * 40,
    branch: str = "feature/x",
    repo: str = _REPO_FULL_NAME,
) -> dict[str, Any]:
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "number": number,
            "head": {"sha": commit_sha, "ref": branch},
        },
        "repository": {"id": 9876, "full_name": repo, "name": repo.split("/")[-1]},
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


def _post_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize ``payload`` to the exact bytes the receiver will sign."""
    # ``separators=(",", ":")`` so the HMAC we compute matches whatever bytes
    # ``httpx`` will send; we pass the same bytes via ``content=`` below.
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_ping_returns_pong(api_db: ApiDb) -> None:
    """``ping`` event with valid HMAC returns 200 ``{pong: true}`` (no run)."""
    await _seed(api_db, slug="gh-ping", case_public_id="TC-GH-PING")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes({"zen": "Keep it logically awesome.", "hook_id": 1})
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(body),
                    "X-GitHub-Event": "ping",
                    "X-GitHub-Delivery": "delivery-1",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"pong": True}
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_github_push_with_valid_hmac_enqueues_gating_run(api_db: ApiDb) -> None:
    """``push`` event with valid HMAC → 202 + ARQ enqueued + correct branch/SHA."""
    seeded = await _seed(api_db, slug="gh-push-ok", case_public_id="TC-GH1")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes(_push_payload(branch="main", commit_sha="a" * 40))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(body),
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": "delivery-push-1",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202, resp.text
    body_json = resp.json()
    assert body_json["runId"]
    assert body_json["publicId"].startswith("R-")
    assert body_json["statusUrl"].startswith("/api/v1/runs/")
    assert arq.enqueued and arq.enqueued[0][0] == "run_test_case"

    # Verify the run carries the right branch/commit/trigger fields.
    async with api_db.maker() as session:
        run = await session.get(Run, body_json["runId"])
        assert run is not None
        assert run.trigger == RunTrigger.WEBHOOK
        assert run.triggered_by == "webhook:github"
        assert run.branch == "main"
        assert run.commit_sha == "a" * 40
        assert run.project_id == seeded.project.id


@pytest.mark.asyncio
async def test_github_push_with_invalid_hmac_returns_401(api_db: ApiDb) -> None:
    """Wrong HMAC → 401 even though the workspace + repo are valid."""
    await _seed(api_db, slug="gh-401-hmac", case_public_id="TC-GH2")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes(_push_payload())
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    # Sign with the *wrong* secret.
                    "X-Hub-Signature-256": _sign(body, secret=_WRONG_SECRET),
                    "X-GitHub-Event": "push",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 401
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_github_missing_signature_returns_401(api_db: ApiDb) -> None:
    """Missing ``X-Hub-Signature-256`` header → 401."""
    await _seed(api_db, slug="gh-unsigned", case_public_id="TC-GH3")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes(_push_payload())
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "push",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 401
    assert arq.enqueued == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened"])
async def test_github_pull_request_triggering_actions_enqueue_run(
    api_db: ApiDb, action: str
) -> None:
    """``pull_request`` with opened/synchronize/reopened → 202 + run on head SHA."""
    seeded = await _seed(
        api_db, slug=f"gh-pr-{action}", case_public_id=f"TC-PR-{action[:1].upper()}"
    )

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    pr_sha = "c" * 40
    body = _post_bytes(_pr_payload(action=action, commit_sha=pr_sha, branch="feature/y"))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(body),
                    "X-GitHub-Event": "pull_request",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202, resp.text
    body_json = resp.json()
    assert body_json["runId"]

    async with api_db.maker() as session:
        run = await session.get(Run, body_json["runId"])
        assert run is not None
        assert run.commit_sha == pr_sha
        assert run.branch == "feature/y"
        assert run.project_id == seeded.project.id
        # Audit row carries pull_request_number.
        rows = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "webhook.github.received")
            )
        ).all()
    assert rows, "audit row must be written"
    md = rows[0].metadata_json or {}
    assert md.get("pull_request_number") == 7
    assert md.get("event") == "pull_request"


@pytest.mark.asyncio
async def test_github_pull_request_closed_returns_200_ignored(api_db: ApiDb) -> None:
    """``pull_request`` action ``closed`` → 200 ``unsupported_action`` (no run)."""
    await _seed(api_db, slug="gh-pr-closed", case_public_id="TC-PR-CLS")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes(_pr_payload(action="closed"))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(body),
                    "X-GitHub-Event": "pull_request",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "unsupported_action"}
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_github_unsupported_event_returns_200_ignored(api_db: ApiDb) -> None:
    """An event we don't handle (e.g. ``issues``) → 200 ``unsupported_event``."""
    await _seed(api_db, slug="gh-unknown-evt", case_public_id="TC-GH-UNK")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes({"action": "opened", "issue": {"number": 1}})
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(body),
                    "X-GitHub-Event": "issues",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "unsupported_event"}
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_github_unknown_repo_returns_404(api_db: ApiDb) -> None:
    """``github_repo`` mismatch → 404 even with valid HMAC."""
    await _seed(api_db, slug="gh-unknown-repo", case_public_id="TC-GH-RPO")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes(_push_payload(repo="evil/elsewhere"))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(body),
                    "X-GitHub-Event": "push",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 404
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_github_no_gating_suite_returns_200_ignored(api_db: ApiDb) -> None:
    """No gating_suite_id + no smoke-tagged cases → 200 ``no_gating_suite``."""
    await _seed(
        api_db,
        slug="gh-no-gating",
        case_public_id="TC-GH-NG",
        with_smoke_tag=False,
        pin_gating_suite=False,
    )

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes(_push_payload())
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(body),
                    "X-GitHub-Event": "push",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "no_gating_suite"}
    assert arq.enqueued == []


@pytest.mark.asyncio
async def test_github_duplicate_within_60s_returns_200_ignored(api_db: ApiDb) -> None:
    """Same commit pushed twice inside the TTL → only first enqueues."""
    await _seed(api_db, slug="gh-dedup", case_public_id="TC-GH-DD")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes(_push_payload(commit_sha="d" * 40))
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": _sign(body),
        "X-GitHub-Event": "push",
    }
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            first = await c.post("/api/v1/webhooks/github", content=body, headers=headers)
            second = await c.post("/api/v1/webhooks/github", content=body, headers=headers)
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert first.status_code == 202, first.text
    assert second.status_code == 200
    assert second.json()["reason"] == "duplicate"
    assert len(arq.enqueued) == 1


@pytest.mark.asyncio
async def test_github_push_and_pr_distinct_commits_produce_distinct_runs(
    api_db: ApiDb,
) -> None:
    """A push at SHA X and a PR with head SHA Y enqueue *different* runs."""
    await _seed(api_db, slug="gh-pr-push-mix", case_public_id="TC-GH-MIX")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    push_sha = "1" * 40
    pr_sha = "2" * 40
    push_body = _post_bytes(_push_payload(commit_sha=push_sha))
    pr_body = _post_bytes(_pr_payload(action="opened", commit_sha=pr_sha))

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            push_resp = await c.post(
                "/api/v1/webhooks/github",
                content=push_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(push_body),
                    "X-GitHub-Event": "push",
                },
            )
            pr_resp = await c.post(
                "/api/v1/webhooks/github",
                content=pr_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(pr_body),
                    "X-GitHub-Event": "pull_request",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert push_resp.status_code == 202, push_resp.text
    assert pr_resp.status_code == 202, pr_resp.text
    assert push_resp.json()["runId"] != pr_resp.json()["runId"]

    async with api_db.maker() as session:
        push_run = await session.get(Run, push_resp.json()["runId"])
        pr_run = await session.get(Run, pr_resp.json()["runId"])
        assert push_run is not None and pr_run is not None
        assert push_run.commit_sha == push_sha
        assert pr_run.commit_sha == pr_sha


@pytest.mark.asyncio
async def test_github_audit_row_written(api_db: ApiDb) -> None:
    """A successful webhook writes a ``webhook.github.received`` audit row."""
    seeded = await _seed(api_db, slug="gh-audit", case_public_id="TC-GH-AUD")

    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)

    body = _post_bytes(_push_payload(branch="main", commit_sha="e" * 40))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": _sign(body),
                    "X-GitHub-Event": "push",
                    "X-GitHub-Delivery": "delivery-aud-1",
                },
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202
    async with api_db.maker() as session:
        rows = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "webhook.github.received",
                    AuditLog.workspace_id == seeded.workspace_id,
                )
            )
        ).all()
    assert len(rows) == 1
    md = rows[0].metadata_json or {}
    assert md.get("integration_id") == seeded.integration.id
    assert md.get("branch") == "main"
    assert md.get("commit_sha") == "e" * 40
    assert md.get("event") == "push"
    assert md.get("delivery") == "delivery-aud-1"
    assert md.get("repository") == _REPO_FULL_NAME


@pytest.mark.asyncio
async def test_github_hmac_constant_time_helper_used(api_db: ApiDb) -> None:
    """Verify the receiver uses :func:`hmac.compare_digest` (not ``==``).

    We inspect the source string of the verifier to guarantee a future refactor
    can't silently drop the constant-time guard. This is a belt-and-braces
    check on top of the wrong-HMAC 401 test, mirroring the GitLab parity test.
    """
    import inspect

    from suitest_api.services import webhook_receiver_service

    src = inspect.getsource(webhook_receiver_service.verify_github_hmac)
    assert "compare_digest" in src
    # And make sure the unsigned path still surfaces 401 from the integration view:
    await _seed(api_db, slug="gh-ct-check", case_public_id="TC-GH-CT")
    arq = _RecordingArq()
    server = fakeredis.FakeServer()
    redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, user=None, arq=arq, redis=redis)
    body = _post_bytes(_push_payload())
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={"Content-Type": "application/json", "X-GitHub-Event": "push"},
            )
    await redis.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 401

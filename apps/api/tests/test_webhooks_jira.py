"""Tests for ``POST /api/v1/webhooks/jira`` (M1d-18).

Covers the matrix spelled out in plan-05b §M1d-18 plus the additional cases
the implementor task brief calls out (idempotency, terminal-status
``resolved_at`` flipping, cross-workspace isolation, audit + WS emission).
Wiring follows the pattern from ``test_test_cases_writes`` for the WS bus
(``fakeredis`` on ``app.state.ws_redis`` + an explicit pubsub subscriber) and
overrides ``get_dedup_redis`` with a separate ``fakeredis`` so the SETNX
dedup never opens a real broker.
"""

# mypy: warn_unused_ignores=False
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import fakeredis
import fakeredis.aioredis
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from suitest_api.deps.dedup_redis import get_dedup_redis
from suitest_db.models.audit import AuditLog
from suitest_db.models.defect import Defect, ExternalIssue
from suitest_db.models.integration import Integration
from suitest_db.public_id import set_workspace_id
from suitest_shared.domain.enums import (
    DefectStatus,
    DiagnosisKind,
    IntegrationKind,
    Severity,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


_VALID_SECRET = "jira-hook-secret-fixture"
_WRONG_SECRET = "jira-hook-wrong-fixture"

_JIRA_SECRETS_BLOB = json.dumps(
    {
        "url": "https://acme.atlassian.net",
        "email": "ops@acme.test",
        "token": "tok-fixture",
        "auth_type": "cloud_api_token",
        "deployment": "cloud",
    }
)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


@dataclass
class _Seeded:
    workspace_id: str
    integration: Integration
    defect: Defect
    external: ExternalIssue


async def _seed(
    api_db: ApiDb,
    *,
    slug: str,
    issue_key: str = "PROJ-42",
    initial_status: DefectStatus = DefectStatus.OPEN,
    secret: str = _VALID_SECRET,
    integration_kind: IntegrationKind = IntegrationKind.JIRA,
    resolved_at: datetime | None = None,
    with_external_link: bool = True,
) -> _Seeded:
    """Workspace + Jira Integration (URL secret + adapter creds) + Defect (+ optional ExternalIssue link)."""
    user = await api_db.seed_user(email=f"{slug}@example.com")
    ws = await api_db.member_workspace(user, slug=slug)
    integration = Integration(
        workspace_id=ws.id,
        kind=integration_kind,
        name="acme jira",
        config={
            "project_key": "PROJ",
            "webhook_secret": secret,
        },
        secrets_encrypted=_JIRA_SECRETS_BLOB,
        status="active",
    )
    await api_db.add_all([integration])
    defect = Defect(
        workspace_id=ws.id,
        title="login flakes",
        severity=Severity.HIGH,
        status=initial_status,
        created_by="auto-filer@suitest",
        agent_diagnosis_kind=DiagnosisKind.MANUAL_TRIAGE,
        resolved_at=resolved_at,
    )
    # ``Defect`` uses the per-workspace public_id sequence — attach the
    # transient workspace context the ``before_insert`` listener consumes so
    # the ``SUIT-<n>`` value gets assigned at flush time.
    set_workspace_id(defect, ws.id)
    await api_db.add_all([defect])
    external = ExternalIssue(
        defect_id=defect.id,
        provider="jira",
        external_id=issue_key,
        external_url=f"https://acme.atlassian.net/browse/{issue_key}",
    )
    if with_external_link:
        await api_db.add_all([external])
    return _Seeded(
        workspace_id=ws.id,
        integration=integration,
        defect=defect,
        external=external,
    )


def _issue_updated_payload(
    *,
    issue_key: str = "PROJ-42",
    status_name: str = "In Progress",
    changelog_id: str = "10001",
    from_status: str = "To Do",
) -> dict[str, Any]:
    """Minimal but realistic Jira ``issue_updated`` body."""
    return {
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "id": "10009",
            "key": issue_key,
            "fields": {
                "status": {"name": status_name},
            },
        },
        "changelog": {
            "id": changelog_id,
            "items": [
                {
                    "field": "status",
                    "fromString": from_status,
                    "toString": status_name,
                }
            ],
        },
    }


def _build_app(api_db: ApiDb, *, redis: Any, ws_redis: Any = None) -> Any:
    """Build an app with the dedup-redis override + (optional) ws redis injection."""
    app = api_db.app_for(None)

    async def _override_redis() -> Any:
        return redis

    app.dependency_overrides[get_dedup_redis] = _override_redis
    if ws_redis is not None:
        app.state.ws_redis = ws_redis
    return app


async def _fetch_audit(api_db: ApiDb, defect_id: str, action: str) -> AuditLog | None:
    async with api_db.maker() as session:
        stmt = (
            select(AuditLog)
            .where(AuditLog.resource_id == defect_id, AuditLog.action == action)
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def _fetch_defect(api_db: ApiDb, defect_id: str) -> Defect | None:
    async with api_db.maker() as session:
        return await session.get(Defect, defect_id)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_issue_updated_event_finds_local_defect_by_external_id_and_updates_status(
    api_db: ApiDb,
) -> None:
    """Valid secret + mapped status name → 202 + defect.status flipped."""
    seeded = await _seed(api_db, slug="jw-happy", initial_status=DefectStatus.OPEN)

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="In Progress"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body == {
        "defectId": seeded.defect.id,
        "fromStatus": "OPEN",
        "toStatus": "IN_PROGRESS",
    }
    refreshed = await _fetch_defect(api_db, seeded.defect.id)
    assert refreshed is not None
    assert refreshed.status == DefectStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_missing_secret_returns_401(api_db: ApiDb) -> None:
    """No ``?secret=`` query → 401, never touches the dedup or DB."""
    await _seed(api_db, slug="jw-401-missing")

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/webhooks/jira",
                json=_issue_updated_payload(),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_jira_wrong_secret_returns_401_constant_time(api_db: ApiDb) -> None:
    """Wrong ``?secret=`` → 401 even though the workspace exists."""
    await _seed(api_db, slug="jw-401-wrong")

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_WRONG_SECRET}",
                json=_issue_updated_payload(),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Event filter + payload shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_non_issue_updated_event_returns_200_ignored(api_db: ApiDb) -> None:
    """Other ``webhookEvent`` values (e.g. ``jira:issue_created``) → 200 ignored, no DB write."""
    seeded = await _seed(api_db, slug="jw-other-event", initial_status=DefectStatus.OPEN)

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json={
                    "webhookEvent": "jira:issue_created",
                    "issue": {"key": "PROJ-42"},
                },
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "unsupported_event"}
    refreshed = await _fetch_defect(api_db, seeded.defect.id)
    assert refreshed is not None
    assert refreshed.status == DefectStatus.OPEN  # untouched


@pytest.mark.asyncio
async def test_jira_unknown_issue_key_returns_200_ignored(api_db: ApiDb) -> None:
    """An issue_updated for an issue not linked locally → 200 ``unknown_issue``."""
    await _seed(api_db, slug="jw-unknown", issue_key="PROJ-42")

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(issue_key="PROJ-9999"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "unknown_issue"}


@pytest.mark.asyncio
async def test_jira_unmappable_status_returns_200_ignored_and_audits(api_db: ApiDb) -> None:
    """A status name the StatusMap doesn't recognise → 200 + audit skipped row."""
    seeded = await _seed(api_db, slug="jw-unmappable", initial_status=DefectStatus.OPEN)

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="Pending Review"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "unmappable_status"}
    refreshed = await _fetch_defect(api_db, seeded.defect.id)
    assert refreshed is not None
    assert refreshed.status == DefectStatus.OPEN
    audit = await _fetch_audit(api_db, seeded.defect.id, "defect.status_sync_skipped_unmappable")
    assert audit is not None
    metadata = audit.metadata_json or {}
    assert metadata.get("external_status_name") == "Pending Review"
    assert metadata.get("integration_id") == seeded.integration.id


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_no_local_change_when_status_already_matches_returns_200(
    api_db: ApiDb,
) -> None:
    """Defect already at the mapped status → 200 ``no_status_change`` (no audit, no WS)."""
    seeded = await _seed(api_db, slug="jw-idemp", initial_status=DefectStatus.IN_PROGRESS)

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="In Progress"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "no_status_change"}
    audit = await _fetch_audit(api_db, seeded.defect.id, "defect.status_synced_from_jira")
    assert audit is None


@pytest.mark.asyncio
async def test_jira_dedup_via_changelog_id_replay_no_op(api_db: ApiDb) -> None:
    """Same changelog id within the TTL window → second request 200 ``duplicate``."""
    seeded = await _seed(api_db, slug="jw-dedup", initial_status=DefectStatus.OPEN)

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            first = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="In Progress", changelog_id="dedup-key-1"),
            )
            # Reset the defect so the second call would otherwise act on it —
            # this is the strict dedup check: replay returns ``duplicate`` even
            # when there IS a change to apply.
            async with api_db.maker() as session:
                row = await session.get(Defect, seeded.defect.id)
                assert row is not None
                row.status = DefectStatus.OPEN
                await session.commit()
            second = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="In Progress", changelog_id="dedup-key-1"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json() == {"ignored": True, "reason": "duplicate"}


# ---------------------------------------------------------------------------
# resolved_at flip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_mapped_to_resolved_sets_resolved_at(api_db: ApiDb) -> None:
    """Transitioning into a terminal state stamps ``resolved_at``."""
    seeded = await _seed(api_db, slug="jw-resolve", initial_status=DefectStatus.IN_PROGRESS)
    assert seeded.defect.resolved_at is None

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="Resolved"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202
    refreshed = await _fetch_defect(api_db, seeded.defect.id)
    assert refreshed is not None
    assert refreshed.status == DefectStatus.RESOLVED
    assert refreshed.resolved_at is not None


@pytest.mark.asyncio
async def test_jira_reopen_from_closed_clears_resolved_at(api_db: ApiDb) -> None:
    """Re-opening a closed defect via Jira webhook clears ``resolved_at``."""
    seeded = await _seed(
        api_db,
        slug="jw-reopen",
        initial_status=DefectStatus.CLOSED,
        resolved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert seeded.defect.resolved_at is not None

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="To Do"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202
    refreshed = await _fetch_defect(api_db, seeded.defect.id)
    assert refreshed is not None
    assert refreshed.status == DefectStatus.OPEN
    assert refreshed.resolved_at is None


# ---------------------------------------------------------------------------
# Audit + WS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_writes_audit_with_action_defect_status_synced_from_jira(
    api_db: ApiDb,
) -> None:
    """Successful sync writes an audit row with the canonical action + metadata."""
    seeded = await _seed(api_db, slug="jw-audit", initial_status=DefectStatus.OPEN)

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="In Progress", changelog_id="aud-1"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202
    audit = await _fetch_audit(api_db, seeded.defect.id, "defect.status_synced_from_jira")
    assert audit is not None
    metadata = audit.metadata_json or {}
    assert metadata.get("from_status") == "OPEN"
    assert metadata.get("to_status") == "IN_PROGRESS"
    assert metadata.get("external_status_name") == "In Progress"
    assert metadata.get("external_id") == "PROJ-42"
    assert metadata.get("integration_id") == seeded.integration.id
    assert metadata.get("correlation_id") == "aud-1"


@pytest.mark.asyncio
async def test_jira_emits_defect_updated_ws_event_to_workspace_room(api_db: ApiDb) -> None:
    """Successful sync publishes ``defect.updated`` on ``workspace:<id>``."""
    seeded = await _seed(api_db, slug="jw-ws", initial_status=DefectStatus.OPEN)

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    ws_redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    received: list[bytes] = []

    pubsub = ws_redis.pubsub()
    await pubsub.subscribe(f"workspace:{seeded.workspace_id}")

    async def _drain() -> None:
        await pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
        for _ in range(5):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is not None:
                received.append(msg["data"])
                return

    app = _build_app(api_db, redis=dedup, ws_redis=ws_redis)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(status_name="In Progress"),
            )
            await _drain()
    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await ws_redis.aclose()  # type: ignore[no-untyped-call]
    await dedup.aclose()  # type: ignore[no-untyped-call]
    assert resp.status_code == 202
    assert received, "WS publish must land on the workspace:<id> channel"
    decoded = received[0].decode()
    assert "defect.updated" in decoded
    assert seeded.defect.id in decoded


# ---------------------------------------------------------------------------
# Cross-workspace isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_cross_workspace_defect_not_visible_to_other_workspace_returns_200_ignored(
    api_db: ApiDb,
) -> None:
    """A Jira hook secret bound to workspace A cannot mutate workspace B's defect."""
    # Workspace A: registers the Jira integration + secret.
    seeded_a = await _seed(api_db, slug="jw-isol-a", issue_key="ALPHA-1")
    # Workspace B: owns a defect linked to the SAME Jira issue key but
    # belonging to a different workspace's external_issues row would violate
    # the unique constraint, so we use a distinct key.
    user_b = await api_db.seed_user(email="jw-isol-b@example.com")
    ws_b = await api_db.member_workspace(user_b, slug="jw-isol-b")
    # Pre-pin ``public_id`` on the second workspace's defect — the listener
    # generates ``SUIT-1000`` for every fresh workspace and the column carries a
    # global uniqueness constraint, so a naked add_all here would conflict with
    # the first workspace's auto-assigned ``SUIT-1000``.
    defect_b = Defect(
        workspace_id=ws_b.id,
        public_id="SUIT-ISOL-B-1",
        title="b-side",
        severity=Severity.LOW,
        status=DefectStatus.OPEN,
        created_by="auto",
        agent_diagnosis_kind=DiagnosisKind.MANUAL_TRIAGE,
    )
    await api_db.add_all([defect_b])
    await api_db.add_all(
        [
            ExternalIssue(
                defect_id=defect_b.id,
                provider="jira",
                external_id="BETA-1",
                external_url="https://x/browse/BETA-1",
            )
        ]
    )

    server = fakeredis.FakeServer()
    dedup = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    app = _build_app(api_db, redis=dedup)

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Use workspace A's secret but target workspace B's issue key.
            resp = await c.post(
                f"/api/v1/webhooks/jira?secret={_VALID_SECRET}",
                json=_issue_updated_payload(issue_key="BETA-1", status_name="In Progress"),
            )
    await dedup.aclose()  # type: ignore[no-untyped-call]
    # Resolver finds workspace A's defect... but BETA-1 is owned by B, so the
    # workspace-scoped JOIN returns nothing → ``unknown_issue``.
    assert resp.status_code == 200
    assert resp.json() == {"ignored": True, "reason": "unknown_issue"}
    # And workspace A's own defect is untouched (its key was ALPHA-1).
    refreshed_a = await _fetch_defect(api_db, seeded_a.defect.id)
    assert refreshed_a is not None
    assert refreshed_a.status == DefectStatus.OPEN
    refreshed_b = await _fetch_defect(api_db, defect_b.id)
    assert refreshed_b is not None
    assert refreshed_b.status == DefectStatus.OPEN

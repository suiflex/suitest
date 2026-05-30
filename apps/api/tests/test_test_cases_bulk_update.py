"""M1d-7 — POST /test-cases/bulk-update endpoint tests (docs/API.md §3.3).

Covers the five ``action`` variants (delete / move_to_suite / set_priority /
add_tags / remove_tags), the 100-id cap (``BULK_LIMIT_EXCEEDED``),
cross-workspace ids (``CROSS_WORKSPACE_IDS``), the move-target workspace
check (``INVALID_TARGET_SUITE``), the role gate (QA+ allowed, VIEWER 403),
the single-transaction guarantee (mid-tx failure rolls everything back),
audit rows + their returned ``audit_ids``, and the per-case WS broadcast.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import CaseTag, TestCase
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource, Priority, Role

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "tcbulk-proj") -> Suite:
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


async def _seed_case(
    api_db: ApiDb, suite_id: str, *, public_id: str, name: str = "case"
) -> TestCase:
    case = TestCase(suite_id=suite_id, public_id=public_id, name=name, source=CaseSource.MANUAL)
    await api_db.add_all([case])
    return case


async def _seed_many_cases(
    api_db: ApiDb, suite_id: str, *, count: int, prefix: str = "TC-B"
) -> list[TestCase]:
    """Seed ``count`` cases in one commit to keep the test fast."""
    rows = [
        TestCase(
            suite_id=suite_id,
            public_id=f"{prefix}-{i}",
            name=f"case-{i}",
            source=CaseSource.MANUAL,
        )
        for i in range(count)
    ]
    await api_db.add_all(rows)
    return rows


# ---------------------------------------------------------------------------
# Cap + cross-workspace validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_update_over_100_ids_returns_400_bulk_limit_exceeded(
    api_db: ApiDb,
) -> None:
    """101 ids → 400 ``BULK_LIMIT_EXCEEDED`` with received + limit details."""
    user = await api_db.seed_user(email="tcbulk-cap@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-cap-ws")

    ids = [f"ck_fake_{i:03d}" for i in range(101)]
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={"ids": ids, "action": "delete", "payload": {}},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    err = resp.json()["detail"]["error"]
    assert err["code"] == "BULK_LIMIT_EXCEEDED"
    assert err["details"]["received"] == 101
    assert err["details"]["limit"] == 100


@pytest.mark.asyncio
async def test_bulk_update_cross_workspace_ids_returns_400_with_offending_list(
    api_db: ApiDb,
) -> None:
    """Mixed-workspace ids → 400 ``CROSS_WORKSPACE_IDS`` with offending id list."""
    user = await api_db.seed_user(email="tcbulk-xws@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-xws-ws")
    other = await api_db.seed_workspace(slug="tcbulk-xws-other", name="Other")
    suite_local = await _project_suite(api_db, ws.id)
    suite_other = await _project_suite(api_db, other.id, slug="tcbulk-xws-other-p")

    mine = await _seed_case(api_db, suite_local.id, public_id="TC-LX1")
    theirs = await _seed_case(api_db, suite_other.id, public_id="TC-LX2")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={"ids": [mine.id, theirs.id], "action": "delete", "payload": {}},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    err = resp.json()["detail"]["error"]
    assert err["code"] == "CROSS_WORKSPACE_IDS"
    assert theirs.id in err["details"]["offendingIds"]
    assert mine.id not in err["details"]["offendingIds"]


@pytest.mark.asyncio
async def test_bulk_update_cross_workspace_no_partial_apply(api_db: ApiDb) -> None:
    """Cross-workspace request must NOT mutate the local ids (atomic).

    Verifies the transaction rolls back so the local case stays active even
    though the body listed it alongside a foreign id.
    """
    user = await api_db.seed_user(email="tcbulk-xws-rb@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-xws-rb-ws")
    other = await api_db.seed_workspace(slug="tcbulk-xws-rb-other", name="Other")
    suite_local = await _project_suite(api_db, ws.id)
    suite_other = await _project_suite(api_db, other.id, slug="tcbulk-xws-rb-other-p")
    mine = await _seed_case(api_db, suite_local.id, public_id="TC-RB1")
    theirs = await _seed_case(api_db, suite_other.id, public_id="TC-RB2")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={"ids": [mine.id, theirs.id], "action": "delete", "payload": {}},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400

    async with api_db.maker() as session:
        row = await session.scalar(select(TestCase).where(TestCase.id == mine.id))
    assert row is not None
    assert row.deleted_at is None, "local case must NOT be soft-deleted"


# ---------------------------------------------------------------------------
# delete action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_delete_happy_path_soft_deletes_all(api_db: ApiDb) -> None:
    """``action=delete`` tombstones every id + returns ``updated == len(ids)``."""
    user = await api_db.seed_user(email="tcbulk-del@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-del-ws")
    suite = await _project_suite(api_db, ws.id)
    rows = await _seed_many_cases(api_db, suite.id, count=3, prefix="TC-D")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={"ids": [r.id for r in rows], "action": "delete", "payload": {}},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated"] == 3
    assert len(body["auditIds"]) == 3

    async with api_db.maker() as session:
        live = (
            await session.scalars(select(TestCase).where(TestCase.id.in_([r.id for r in rows])))
        ).all()
    assert all(c.deleted_at is not None for c in live)


@pytest.mark.asyncio
async def test_bulk_delete_writes_one_audit_row_per_case(api_db: ApiDb) -> None:
    """One ``test_case.bulk_deleted`` audit row per id (returned in audit_ids)."""
    user = await api_db.seed_user(email="tcbulk-del-aud@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-del-aud-ws")
    suite = await _project_suite(api_db, ws.id)
    rows = await _seed_many_cases(api_db, suite.id, count=3, prefix="TC-DA")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={"ids": [r.id for r in rows], "action": "delete", "payload": {}},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    returned_audit_ids = resp.json()["auditIds"]

    async with api_db.maker() as session:
        audits = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.workspace_id == ws.id,
                    AuditLog.action == "test_case.bulk_deleted",
                )
            )
        ).all()
    assert len(audits) == 3
    assert {a.id for a in audits} == set(returned_audit_ids)


@pytest.mark.asyncio
async def test_bulk_delete_transaction_rolls_back_on_mid_tx_failure(
    api_db: ApiDb,
) -> None:
    """Patch the bulk_soft_delete repo method to raise; verify NO row mutates.

    Simulates a partial-fail scenario: if any step inside the service
    transaction blows up, the whole batch must roll back — no case ends up
    tombstoned. Demonstrates the single-transaction guarantee.
    """
    user = await api_db.seed_user(email="tcbulk-rb@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-rb-ws")
    suite = await _project_suite(api_db, ws.id)
    rows = await _seed_many_cases(api_db, suite.id, count=3, prefix="TC-RB")

    from suitest_db.repositories.test_cases import TestCaseRepo

    async def _boom(self, ids, *, deleted_at):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated mid-transaction failure")

    with patch.object(TestCaseRepo, "bulk_soft_delete", _boom):
        async with api_db.client(user) as c:
            try:
                resp = await c.post(
                    "/api/v1/test-cases/bulk-update",
                    json={
                        "ids": [r.id for r in rows],
                        "action": "delete",
                        "payload": {},
                    },
                    headers={"X-Workspace-Id": ws.id},
                )
                # FastAPI may surface the RuntimeError as a 500 — both 500
                # and an exception bubble are acceptable; what matters is the
                # DB state.
                assert resp.status_code in (500, 400)
            except RuntimeError:
                pass  # ASGI may re-raise the inner exception in tests

    async with api_db.maker() as session:
        live = (
            await session.scalars(select(TestCase).where(TestCase.id.in_([r.id for r in rows])))
        ).all()
    assert all(c.deleted_at is None for c in live), "no row should be tombstoned"


# ---------------------------------------------------------------------------
# move_to_suite action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_move_to_suite_happy_path_updates_suite_id(api_db: ApiDb) -> None:
    """``action=move_to_suite`` re-parents every id to the target suite."""
    user = await api_db.seed_user(email="tcbulk-mv@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-mv-ws")
    src = await _project_suite(api_db, ws.id, slug="tcbulk-mv-src")
    dst_project = Project(workspace_id=ws.id, slug="tcbulk-mv-dst", name="Dst")
    await api_db.add_all([dst_project])
    dst = Suite(project_id=dst_project.id, name="DstSuite", order=0)
    await api_db.add_all([dst])
    rows = await _seed_many_cases(api_db, src.id, count=2, prefix="TC-MV")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={
                "ids": [r.id for r in rows],
                "action": "move_to_suite",
                "payload": {"target_suite_id": dst.id},
            },
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 2

    async with api_db.maker() as session:
        moved = (
            await session.scalars(select(TestCase).where(TestCase.id.in_([r.id for r in rows])))
        ).all()
    assert all(c.suite_id == dst.id for c in moved)


@pytest.mark.asyncio
async def test_bulk_move_to_suite_cross_workspace_target_returns_400(
    api_db: ApiDb,
) -> None:
    """Target suite in another workspace → 400 ``INVALID_TARGET_SUITE``."""
    user = await api_db.seed_user(email="tcbulk-mv-x@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-mv-x-ws")
    other = await api_db.seed_workspace(slug="tcbulk-mv-x-other", name="Other")
    src = await _project_suite(api_db, ws.id)
    dst_other = await _project_suite(api_db, other.id, slug="tcbulk-mv-x-other-p")
    rows = await _seed_many_cases(api_db, src.id, count=2, prefix="TC-MVX")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={
                "ids": [r.id for r in rows],
                "action": "move_to_suite",
                "payload": {"target_suite_id": dst_other.id},
            },
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    err = resp.json()["detail"]["error"]
    assert err["code"] == "INVALID_TARGET_SUITE"
    assert err["details"]["suiteId"] == dst_other.id

    # No partial apply.
    async with api_db.maker() as session:
        unchanged = (
            await session.scalars(select(TestCase).where(TestCase.id.in_([r.id for r in rows])))
        ).all()
    assert all(c.suite_id == src.id for c in unchanged)


# ---------------------------------------------------------------------------
# set_priority action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_set_priority_updates_priority_for_all(api_db: ApiDb) -> None:
    """``action=set_priority`` changes ``priority`` on every id."""
    user = await api_db.seed_user(email="tcbulk-pri@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-pri-ws")
    suite = await _project_suite(api_db, ws.id)
    rows = await _seed_many_cases(api_db, suite.id, count=2, prefix="TC-PR")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={
                "ids": [r.id for r in rows],
                "action": "set_priority",
                "payload": {"priority": "P0"},
            },
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 2

    async with api_db.maker() as session:
        updated = (
            await session.scalars(select(TestCase).where(TestCase.id.in_([r.id for r in rows])))
        ).all()
    assert all(c.priority == Priority.P0 for c in updated)


# ---------------------------------------------------------------------------
# add_tags / remove_tags actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_add_tags_merges_and_dedupes(api_db: ApiDb) -> None:
    """``add_tags`` merges new tags + does not duplicate existing ones."""
    user = await api_db.seed_user(email="tcbulk-tagadd@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-tagadd-ws")
    suite = await _project_suite(api_db, ws.id)
    rows = await _seed_many_cases(api_db, suite.id, count=2, prefix="TC-TA")
    # Seed one of them with an existing tag — should not duplicate.
    await api_db.add_all([CaseTag(case_id=rows[0].id, tag="smoke")])

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={
                "ids": [r.id for r in rows],
                "action": "add_tags",
                "payload": {"tags": ["smoke", "p0", "smoke"]},
            },
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text

    async with api_db.maker() as session:
        first_tags = sorted(
            (await session.scalars(select(CaseTag.tag).where(CaseTag.case_id == rows[0].id))).all()
        )
        second_tags = sorted(
            (await session.scalars(select(CaseTag.tag).where(CaseTag.case_id == rows[1].id))).all()
        )
    assert first_tags == ["p0", "smoke"]
    assert second_tags == ["p0", "smoke"]


@pytest.mark.asyncio
async def test_bulk_remove_tags_silently_skips_absent(api_db: ApiDb) -> None:
    """``remove_tags`` is a no-op for tags the case does not carry."""
    user = await api_db.seed_user(email="tcbulk-tagrm@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-tagrm-ws")
    suite = await _project_suite(api_db, ws.id)
    rows = await _seed_many_cases(api_db, suite.id, count=2, prefix="TC-TR")
    await api_db.add_all([CaseTag(case_id=rows[0].id, tag="keep")])

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={
                "ids": [r.id for r in rows],
                "action": "remove_tags",
                "payload": {"tags": ["absent"]},
            },
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    # No tags removed → updated == 0.
    assert resp.json()["updated"] == 0

    async with api_db.maker() as session:
        tags = sorted(
            (await session.scalars(select(CaseTag.tag).where(CaseTag.case_id == rows[0].id))).all()
        )
    assert tags == ["keep"]


@pytest.mark.asyncio
async def test_bulk_remove_tags_removes_only_specified(api_db: ApiDb) -> None:
    """Only listed tags are removed; other tags survive."""
    user = await api_db.seed_user(email="tcbulk-tagrm2@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-tagrm2-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-TRR1")
    await api_db.add_all(
        [
            CaseTag(case_id=case.id, tag="keep"),
            CaseTag(case_id=case.id, tag="drop"),
        ]
    )

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={
                "ids": [case.id],
                "action": "remove_tags",
                "payload": {"tags": ["drop"]},
            },
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1

    async with api_db.maker() as session:
        tags = sorted(
            (await session.scalars(select(CaseTag.tag).where(CaseTag.case_id == case.id))).all()
        )
    assert tags == ["keep"]


# ---------------------------------------------------------------------------
# Role gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_update_viewer_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot call bulk-update — writer role gate (QA+)."""
    user = await api_db.seed_user(email="tcbulk-viewer@example.com")
    ws = await api_db.seed_workspace(slug="tcbulk-viewer-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-VWR-BULK")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={"ids": [case.id], "action": "delete", "payload": {}},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_bulk_delete_role_qa_passes(api_db: ApiDb) -> None:
    """QA can issue bulk delete (plan-05b Q7: bulk delete is QA+, not ADMIN+)."""
    user = await api_db.seed_user(email="tcbulk-qa@example.com")
    ws = await api_db.seed_workspace(slug="tcbulk-qa-ws", name="QaWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.QA)
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-QA-BULK")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases/bulk-update",
            json={"ids": [case.id], "action": "delete", "payload": {}},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# WS broadcast
# ---------------------------------------------------------------------------


# mypy: warn_unused_ignores=False
@pytest.mark.asyncio
async def test_bulk_delete_emits_case_deleted_ws_event_per_case(api_db: ApiDb) -> None:
    """Bulk delete broadcasts one ``case.deleted`` event per affected case."""
    import fakeredis
    import fakeredis.aioredis
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    user = await api_db.seed_user(email="tcbulk-ws-del@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-ws-del-ws")
    suite = await _project_suite(api_db, ws.id)
    rows = await _seed_many_cases(api_db, suite.id, count=3, prefix="TC-WSD")

    server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    received: list[bytes] = []

    app = api_db.app_for(user)
    app.state.ws_redis = redis_client

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"workspace:{ws.id}")

    async def _drain(n: int) -> None:
        await pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
        for _ in range(20):
            if len(received) >= n:
                return
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is not None:
                received.append(msg["data"])

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/test-cases/bulk-update",
                json={"ids": [r.id for r in rows], "action": "delete", "payload": {}},
                headers={"X-Workspace-Id": ws.id},
            )
            assert resp.status_code == 200
            await _drain(3)

    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await redis_client.aclose()  # type: ignore[no-untyped-call]
    deletes = [r for r in received if b"case.deleted" in r]
    assert len(deletes) == 3, [r.decode() for r in received]


# mypy: warn_unused_ignores=False
@pytest.mark.asyncio
async def test_bulk_set_priority_emits_case_updated_ws_event_per_case(
    api_db: ApiDb,
) -> None:
    """Non-delete actions broadcast ``case.updated`` per affected case."""
    import fakeredis
    import fakeredis.aioredis
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    user = await api_db.seed_user(email="tcbulk-ws-pri@example.com")
    ws = await api_db.member_workspace(user, slug="tcbulk-ws-pri-ws")
    suite = await _project_suite(api_db, ws.id)
    rows = await _seed_many_cases(api_db, suite.id, count=2, prefix="TC-WSP")

    server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    received: list[bytes] = []

    app = api_db.app_for(user)
    app.state.ws_redis = redis_client

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"workspace:{ws.id}")

    async def _drain(n: int) -> None:
        await pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
        for _ in range(20):
            if len(received) >= n:
                return
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is not None:
                received.append(msg["data"])

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/test-cases/bulk-update",
                json={
                    "ids": [r.id for r in rows],
                    "action": "set_priority",
                    "payload": {"priority": "P1"},
                },
                headers={"X-Workspace-Id": ws.id},
            )
            assert resp.status_code == 200
            await _drain(2)

    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await redis_client.aclose()  # type: ignore[no-untyped-call]
    updates = [r for r in received if b"case.updated" in r]
    assert len(updates) == 2, [r.decode() for r in received]

"""Task 7c — test case read endpoint tests (docs/API.md §3.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.project import Project, Suite
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import (
    AutonomyLevel,
    CaseSource,
    CaseStatus,
    TargetKind,
    Tier,
)

if TYPE_CHECKING:
    from conftest import ApiDb


async def _suite(api_db: ApiDb, ws_id: str, *, slug: str = "tc-proj") -> Suite:
    proj = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([proj])
    suite = Suite(project_id=proj.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


@pytest.mark.asyncio
async def test_list_test_cases_by_suite(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tc-list@example.com")
    ws = await api_db.member_workspace(user, slug="tc-list-ws")
    suite = await _suite(api_db, ws.id)
    await api_db.add_all(
        [
            TestCase(suite_id=suite.id, public_id="TC-1", name="one", source=CaseSource.MANUAL),
            TestCase(suite_id=suite.id, public_id="TC-2", name="two", source=CaseSource.MANUAL),
        ]
    )

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases?suiteId={suite.id}", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


@pytest.mark.asyncio
async def test_list_test_cases_filter_status_active(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tc-status@example.com")
    ws = await api_db.member_workspace(user, slug="tc-status-ws")
    suite = await _suite(api_db, ws.id)
    rows = [
        TestCase(
            suite_id=suite.id,
            public_id=f"TC-A{i}",
            name=f"a{i}",
            source=CaseSource.MANUAL,
            status=CaseStatus.ACTIVE,
        )
        for i in range(3)
    ] + [
        TestCase(
            suite_id=suite.id,
            public_id=f"TC-D{i}",
            name=f"d{i}",
            source=CaseSource.MANUAL,
            status=CaseStatus.DEPRECATED,
        )
        for i in range(2)
    ]
    await api_db.add_all(rows)

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases?suiteId={suite.id}&status=ACTIVE",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3


@pytest.mark.asyncio
async def test_list_test_cases_filter_q(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tc-q@example.com")
    ws = await api_db.member_workspace(user, slug="tc-q-ws")
    suite = await _suite(api_db, ws.id)
    await api_db.add_all(
        [
            TestCase(
                suite_id=suite.id, public_id="TC-L1", name="Login flow", source=CaseSource.MANUAL
            ),
            TestCase(
                suite_id=suite.id, public_id="TC-C1", name="Checkout", source=CaseSource.MANUAL
            ),
            TestCase(
                suite_id=suite.id, public_id="TC-L2", name="Login error", source=CaseSource.MANUAL
            ),
        ]
    )

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases?suiteId={suite.id}&q=login", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2  # case-insensitive ILIKE


@pytest.mark.asyncio
async def test_list_test_cases_filter_tag(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tc-tag@example.com")
    ws = await api_db.member_workspace(user, slug="tc-tag-ws")
    suite = await _suite(api_db, ws.id)
    smoke = TestCase(suite_id=suite.id, public_id="TC-S", name="smoky", source=CaseSource.MANUAL)
    plain = TestCase(suite_id=suite.id, public_id="TC-P", name="plain", source=CaseSource.MANUAL)
    await api_db.add_all([smoke, plain])
    await api_db.add_all([CaseTag(case_id=smoke.id, tag="smoke")])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases?suiteId={suite.id}&tag=smoke", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["public_id"] for i in items} == {"TC-S"}


@pytest.mark.asyncio
async def test_get_test_case_includes_steps_in_order(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tc-steps@example.com")
    ws = await api_db.member_workspace(user, slug="tc-steps-ws")
    suite = await _suite(api_db, ws.id)
    case = TestCase(suite_id=suite.id, public_id="TC-ORD", name="ordered", source=CaseSource.MANUAL)
    await api_db.add_all([case])
    await api_db.add_all(
        [
            TestStep(
                case_id=case.id,
                order=2,
                action="second",
                expected="e2",
                code="x",
                target_kind=TargetKind.FE_WEB,
            ),
            TestStep(
                case_id=case.id,
                order=1,
                action="first",
                expected="e1",
                code="x",
                target_kind=TargetKind.FE_WEB,
            ),
        ]
    )

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/test-cases/{case.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    steps = resp.json()["steps"]
    assert [s["order"] for s in steps] == [1, 2]


@pytest.mark.asyncio
async def test_get_test_case_step_executable_zero_tier(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tc-exec@example.com")
    ws = await api_db.member_workspace(user, slug="tc-exec-ws")
    suite = await _suite(api_db, ws.id)
    case = TestCase(suite_id=suite.id, public_id="TC-EX", name="exec", source=CaseSource.MANUAL)
    await api_db.add_all([case])
    # Action-only step (no code).
    await api_db.add_all(
        [
            TestStep(
                case_id=case.id,
                order=1,
                action="click",
                expected="ok",
                target_kind=TargetKind.FE_WEB,
            )
        ]
    )

    # ZERO tier (default env, no overlay) → executable False.
    async with api_db.client(user) as c:
        zero = await c.get(f"/api/v1/test-cases/{case.id}", headers={"X-Workspace-Id": ws.id})
    assert zero.json()["steps"][0]["executable"] is False

    # CLOUD overlay via WorkspaceCapability → executable True.
    await api_db.add_all(
        [
            WorkspaceCapability(
                workspace_id=ws.id,
                tier=Tier.CLOUD,
                autonomy_level=AutonomyLevel.ASSIST,
                features_json={},
            )
        ]
    )
    async with api_db.client(user) as c:
        cloud = await c.get(f"/api/v1/test-cases/{case.id}", headers={"X-Workspace-Id": ws.id})
    assert cloud.json()["steps"][0]["executable"] is True


@pytest.mark.asyncio
async def test_get_test_case_404_when_cross_workspace(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tc-x@example.com")
    ws = await api_db.member_workspace(user, slug="tc-x-ws")
    other = await api_db.seed_workspace(slug="tc-x-other", name="Other")
    suite = await _suite(api_db, other.id, slug="tc-x-other-proj")
    case = TestCase(suite_id=suite.id, public_id="TC-XX", name="hidden", source=CaseSource.MANUAL)
    await api_db.add_all([case])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/test-cases/{case.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_test_cases_pagination_cursor_stable(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tc-cursor@example.com")
    ws = await api_db.member_workspace(user, slug="tc-cursor-ws")
    suite = await _suite(api_db, ws.id)
    same = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
    c1 = TestCase(suite_id=suite.id, public_id="TC-T1", name="t1", source=CaseSource.MANUAL)
    c2 = TestCase(suite_id=suite.id, public_id="TC-T2", name="t2", source=CaseSource.MANUAL)
    c1.created_at = same
    c2.created_at = same
    await api_db.add_all([c1, c2])

    async with api_db.client(user) as c:
        page1 = (
            await c.get(
                f"/api/v1/test-cases?suiteId={suite.id}&limit=1", headers={"X-Workspace-Id": ws.id}
            )
        ).json()
        assert len(page1["items"]) == 1
        cur = page1["meta"]["nextCursor"]
        assert cur is not None
        page2 = (
            await c.get(
                f"/api/v1/test-cases?suiteId={suite.id}&limit=1&cursor={cur}",
                headers={"X-Workspace-Id": ws.id},
            )
        ).json()
    assert len(page2["items"]) == 1
    assert page1["items"][0]["id"] != page2["items"][0]["id"]

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
)

if TYPE_CHECKING:
    from api_harness import ApiDb


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


@pytest.mark.asyncio
async def test_list_test_case_artifacts(api_db: ApiDb) -> None:
    from suitest_db.models.run import Artifact, Run, RunStep
    from suitest_shared.domain.enums import ArtifactKind, RunStatus, RunTrigger, StepOutcome

    user = await api_db.seed_user(email="tc-art@example.com")
    ws = await api_db.member_workspace(user, slug="tc-art-ws")
    suite = await _suite(api_db, ws.id)
    case = TestCase(
        suite_id=suite.id, public_id="TC-ART-1", name="art-case", source=CaseSource.MANUAL
    )
    await api_db.add_all([case])

    run = Run(
        workspace_id=ws.id,
        project_id=suite.project_id,
        public_id="R-9999",
        name="Test Run",
        trigger=RunTrigger.MANUAL,
        status=RunStatus.PASS,
        tier_at_runtime=Tier.LOCAL,
    )
    await api_db.add_all([run])

    step = RunStep(
        run_id=run.id,
        case_id=case.id,
        step_order=1,
        outcome=StepOutcome.PASS,
    )
    await api_db.add_all([step])

    artifact = Artifact(
        run_step_id=step.id,
        kind=ArtifactKind.SCREENSHOT,
        url="file:///tmp/shot1.png",
        size_bytes=2048,
        mime_type="image/png",
    )
    await api_db.add_all([artifact])

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/artifacts", headers={"X-Workspace-Id": ws.id}
        )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == artifact.id
    assert items[0]["runPublicId"] == "R-9999"
    assert items[0]["runStatus"] == "PASS"
    assert items[0]["kind"] == "SCREENSHOT"
    assert items[0]["stepOrder"] == 1
    assert items[0]["sizeBytes"] == 2048


@pytest.mark.asyncio
async def test_list_test_case_runs_includes_runs_without_artifacts(api_db: ApiDb) -> None:
    from suitest_db.models.run import Run, RunStep
    from suitest_shared.domain.enums import RunStatus, RunTrigger, StepOutcome

    user = await api_db.seed_user(email="tc-runs@example.com")
    ws = await api_db.member_workspace(user, slug="tc-runs-ws")
    suite = await _suite(api_db, ws.id)
    case = TestCase(
        suite_id=suite.id, public_id="TC-RUNS-1", name="runs-case", source=CaseSource.MANUAL
    )
    await api_db.add_all([case])

    # Run 1: with media disabled
    run1 = Run(
        workspace_id=ws.id,
        project_id=suite.project_id,
        public_id="R-1001",
        name="Nomedia Run",
        trigger=RunTrigger.MANUAL,
        status=RunStatus.PASS,
        tier_at_runtime=Tier.LOCAL,
        metadata_json={
            "playwright_config": {
                "headless": True,
                "screenshot": "off",
                "video": "off",
                "highlight_steps": False,
            }
        },
    )
    # Run 2: with screenshot enabled
    run2 = Run(
        workspace_id=ws.id,
        project_id=suite.project_id,
        public_id="R-1002",
        name="Media Run",
        trigger=RunTrigger.MANUAL,
        status=RunStatus.PASS,
        tier_at_runtime=Tier.LOCAL,
        metadata_json={
            "playwright_config": {
                "headless": True,
                "screenshot": "on",
                "video": "off",
                "highlight_steps": True,
            }
        },
    )
    await api_db.add_all([run1, run2])

    step1 = RunStep(
        run_id=run1.id,
        case_id=case.id,
        step_order=1,
        outcome=StepOutcome.PASS,
    )
    step2 = RunStep(
        run_id=run2.id,
        case_id=case.id,
        step_order=1,
        outcome=StepOutcome.PASS,
    )
    await api_db.add_all([step1, step2])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/test-cases/{case.id}/runs", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 2
    public_ids = [r["publicId"] for r in runs]
    assert "R-1001" in public_ids
    assert "R-1002" in public_ids

    nomedia_run = next(r for r in runs if r["publicId"] == "R-1001")
    assert nomedia_run["playwrightConfig"] is not None
    assert nomedia_run["playwrightConfig"]["screenshot"] == "off"
    assert nomedia_run["playwrightConfig"]["highlightSteps"] is False

    async with api_db.client(user) as c:
        resp_limited = await c.get(
            f"/api/v1/test-cases/{case.id}/runs?limit=1", headers={"X-Workspace-Id": ws.id}
        )
    assert resp_limited.status_code == 200
    assert len(resp_limited.json()) == 1


@pytest.mark.asyncio
async def test_get_test_case_falls_back_to_latest_run(api_db: ApiDb) -> None:
    from suitest_db.models.run import Run, RunStep
    from suitest_shared.domain.enums import RunStatus, RunTrigger, StepOutcome

    user = await api_db.seed_user(email="tc-fb@example.com")
    ws = await api_db.member_workspace(user, slug="tc-fb-ws")
    suite = await _suite(api_db, ws.id)
    case = TestCase(
        suite_id=suite.id,
        public_id="TC-FB-1",
        name="fallback-case",
        source=CaseSource.MANUAL,
        last_run_id=None,
    )
    await api_db.add_all([case])

    run = Run(
        workspace_id=ws.id,
        project_id=suite.project_id,
        public_id="R-FALLBACK",
        name="Fallback Run",
        trigger=RunTrigger.MANUAL,
        status=RunStatus.PASS,
        tier_at_runtime=Tier.LOCAL,
    )
    await api_db.add_all([run])

    step = RunStep(
        run_id=run.id,
        case_id=case.id,
        step_order=1,
        outcome=StepOutcome.PASS,
    )
    await api_db.add_all([step])

    async with api_db.client(user) as c:
        resp = await c.get(f"/api/v1/test-cases/{case.id}", headers={"X-Workspace-Id": ws.id})
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["last_run_id"] == run.id
    assert detail["last_run_result"] == "PASS"

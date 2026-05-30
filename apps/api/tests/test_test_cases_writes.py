"""M1d-2 — test case write endpoint tests (docs/API.md §3.3).

Covers ``POST /test-cases``, ``PATCH /test-cases/:id``, ``PATCH /test-cases/:id/steps``,
``POST /test-cases/:id/steps``, ``PATCH /test-cases/:id/steps/reorder`` and
``POST /test-cases/:id/duplicate``. Each test exercises ONE acceptance
criterion from plan-05b — happy paths first, then the cross-workspace 404,
concurrent edit 409, role-gate 403, validator 400, MCP-not-registered 404,
duplicate suffix, append race, audit + WS broadcast.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from suitest_db.models.audit import AuditLog
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.mcp_provider import McpProvider
from suitest_db.models.project import Project, Suite
from suitest_db.models.workspace_capability import WorkspaceCapability
from suitest_shared.domain.enums import (
    AutonomyLevel,
    CaseSource,
    McpTransport,
    Role,
    TargetKind,
    Tier,
)

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "tcw-proj") -> Suite:
    """Seed a project + suite under ``ws_id`` and return the suite row."""
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


async def _seed_case(
    api_db: ApiDb, suite_id: str, *, public_id: str = "TC-W1", name: str = "case"
) -> TestCase:
    case = TestCase(suite_id=suite_id, public_id=public_id, name=name, source=CaseSource.MANUAL)
    await api_db.add_all([case])
    return case


async def _seed_capability(api_db: ApiDb, ws_id: str, tier: Tier) -> None:
    await api_db.add_all(
        [
            WorkspaceCapability(
                workspace_id=ws_id,
                tier=tier,
                autonomy_level=AutonomyLevel.MANUAL,
                features_json={},
            )
        ]
    )


def _step_payload(
    *,
    action: str = "Open /login",
    expected: str = "Login form visible",
    code: str | None = "await page.goto('/login');",
    mcp_provider: str = "playwright-mcp",
    target_kind: str = "FE_WEB",
    order: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "action": action,
        "expected": expected,
        "mcpProvider": mcp_provider,
        "targetKind": target_kind,
    }
    if code is not None:
        payload["code"] = code
    if order is not None:
        payload["order"] = order
    return payload


def _case_body(
    suite_id: str, *, steps: list[dict[str, object]] | None = None, **overrides: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "suiteId": suite_id,
        "name": "Login flow",
        "description": "demo",
        "priority": "P0",
        "source": "MANUAL",
        "steps": steps if steps is not None else [_step_payload()],
        "tags": ["smoke", "auth"],
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# POST /test-cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_test_cases_creates_with_steps_and_returns_TC_public_id(
    api_db: ApiDb,
) -> None:
    """Happy path: 201, returned ``publicId`` matches ``TC-\\d+`` per docs/DATA_MODEL §8."""
    user = await api_db.seed_user(email="tcw-create@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-create-ws")
    suite = await _project_suite(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=_case_body(suite.id),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["suite_id"] == suite.id
    assert body["public_id"].startswith("TC-")
    assert body["name"] == "Login flow"
    assert {t for t in body["tags"]} == {"smoke", "auth"}
    assert len(body["steps"]) == 1
    assert body["steps"][0]["mcp_provider"] == "playwright-mcp"
    assert body["steps"][0]["target_kind"] == "FE_WEB"


@pytest.mark.asyncio
async def test_post_test_cases_zero_tier_rejects_step_without_code(api_db: ApiDb) -> None:
    """ZERO tier + strict validation → 400 with ``STEPS_REQUIRE_CODE_IN_ZERO_LLM`` + stepIndex."""
    user = await api_db.seed_user(email="tcw-zero@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-zero-ws")
    suite = await _project_suite(api_db, ws.id)

    body = _case_body(
        suite.id,
        steps=[
            _step_payload(code="await ok()"),
            _step_payload(action="step without code", code=None),
        ],
    )
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=body,
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "STEPS_REQUIRE_CODE_IN_ZERO_LLM"
    assert envelope["details"]["stepIndex"] == 1


@pytest.mark.asyncio
async def test_post_test_cases_strict_zero_false_allows_stepless(api_db: ApiDb) -> None:
    """ZERO + ``strict_zero_validation=false`` → action-only step is accepted."""
    user = await api_db.seed_user(email="tcw-zero-lax@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-zero-lax-ws")
    # Flip the workspace flag off.
    async with api_db.maker() as session:
        from sqlalchemy import update
        from suitest_db.models.workspace import Workspace

        await session.execute(
            update(Workspace).where(Workspace.id == ws.id).values(strict_zero_validation=False)
        )
        await session.commit()
    suite = await _project_suite(api_db, ws.id)

    body = _case_body(suite.id, steps=[_step_payload(code=None, action="no code")])
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=body,
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_post_test_cases_cloud_tier_allows_stepless(api_db: ApiDb) -> None:
    """CLOUD overlay → action-only steps land without ``STEPS_REQUIRE_CODE`` error."""
    user = await api_db.seed_user(email="tcw-cloud@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-cloud-ws")
    await _seed_capability(api_db, ws.id, Tier.CLOUD)
    suite = await _project_suite(api_db, ws.id)

    body = _case_body(suite.id, steps=[_step_payload(code=None)])
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=body,
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_post_test_cases_unregistered_mcp_provider_returns_404(
    api_db: ApiDb,
) -> None:
    """Step references unknown MCP name → 404 ``MCP_PROVIDER_NOT_REGISTERED``."""
    user = await api_db.seed_user(email="tcw-mcp@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-mcp-ws")
    suite = await _project_suite(api_db, ws.id)

    body = _case_body(
        suite.id,
        steps=[_step_payload(mcp_provider="not-a-real-mcp")],
    )
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=body,
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "MCP_PROVIDER_NOT_REGISTERED"
    assert envelope["details"]["name"] == "not-a-real-mcp"


@pytest.mark.asyncio
async def test_post_test_cases_registered_workspace_mcp_is_accepted(
    api_db: ApiDb,
) -> None:
    """Workspace-registered MCP (not bundled) is accepted by the validator."""
    user = await api_db.seed_user(email="tcw-mcp-ok@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-mcp-ok-ws")
    suite = await _project_suite(api_db, ws.id)
    await api_db.add_all(
        [
            McpProvider(
                workspace_id=ws.id,
                name="acme-mcp",
                kind="custom",
                endpoint="http://localhost:9999",
                transport=McpTransport.SSE,
            )
        ]
    )
    body = _case_body(suite.id, steps=[_step_payload(mcp_provider="acme-mcp")])
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=body,
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_post_test_cases_cross_workspace_suite_returns_404(api_db: ApiDb) -> None:
    """Suite belongs to another workspace → 404 (NOT 403)."""
    user = await api_db.seed_user(email="tcw-xws@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-xws-ws")
    other = await api_db.seed_workspace(slug="tcw-xws-other", name="Other")
    suite = await _project_suite(api_db, other.id, slug="tcw-xws-other-proj")

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=_case_body(suite.id),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_test_cases_role_VIEWER_returns_403(api_db: ApiDb) -> None:
    """VIEWER cannot create test cases per docs/API.md role gate."""
    user = await api_db.seed_user(email="tcw-viewer@example.com")
    ws = await api_db.seed_workspace(slug="tcw-viewer-ws", name="ViewerWs")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    suite = await _project_suite(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=_case_body(suite.id),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_test_cases_audit_row_written(api_db: ApiDb) -> None:
    """Every create writes a ``test_case.created`` audit row + the listener insert row."""
    user = await api_db.seed_user(email="tcw-audit@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-audit-ws")
    suite = await _project_suite(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/test-cases",
            json=_case_body(suite.id),
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201
    async with api_db.maker() as session:
        rows = (await session.scalars(select(AuditLog).where(AuditLog.workspace_id == ws.id))).all()
    actions = {r.action for r in rows}
    assert "test_case.created" in actions


# ---------------------------------------------------------------------------
# PATCH /test-cases/:id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_test_cases_metadata_only_does_not_touch_steps(api_db: ApiDb) -> None:
    """PATCH metadata fields → steps untouched, name updated."""
    user = await api_db.seed_user(email="tcw-patch@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-patch-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-P1")
    await api_db.add_all(
        [
            TestStep(
                case_id=case.id,
                order=1,
                action="x",
                expected="y",
                code="z",
                target_kind=TargetKind.FE_WEB,
            )
        ]
    )

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}",
            json={"name": "renamed", "priority": "P0"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "renamed"
    assert body["priority"] == "P0"
    assert len(body["steps"]) == 1


@pytest.mark.asyncio
async def test_patch_test_cases_concurrent_modification_returns_409(
    api_db: ApiDb,
) -> None:
    """Stale ``If-Unmodified-Since`` → 409 + ``serverUpdatedAt`` in details."""
    user = await api_db.seed_user(email="tcw-409@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-409-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-P2")

    stale = (case.updated_at - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}",
            json={"name": "should-fail"},
            headers={"X-Workspace-Id": ws.id, "If-Unmodified-Since": stale},
        )
    assert resp.status_code == 409, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "CONCURRENT_MODIFICATION"
    assert "serverUpdatedAt" in envelope["details"]


@pytest.mark.asyncio
async def test_patch_test_cases_without_if_unmodified_since_last_write_wins(
    api_db: ApiDb,
) -> None:
    """Without the header the PATCH always wins (per docs/API.md §47)."""
    user = await api_db.seed_user(email="tcw-lww@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-lww-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-P3")

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}",
            json={"name": "lww"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_patch_test_cases_cross_workspace_returns_404(api_db: ApiDb) -> None:
    """A case in another workspace is invisible — PATCH returns 404."""
    user = await api_db.seed_user(email="tcw-xws-patch@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-xws-patch-ws")
    other = await api_db.seed_workspace(slug="tcw-xws-patch-other", name="Other")
    suite = await _project_suite(api_db, other.id, slug="tcw-xws-patch-p")
    case = await _seed_case(api_db, suite.id, public_id="TC-XWS")

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}",
            json={"name": "x"},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_test_cases_tag_replace(api_db: ApiDb) -> None:
    """PATCH with ``tags`` replaces the full set."""
    user = await api_db.seed_user(email="tcw-tags@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-tags-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-T1")
    await api_db.add_all([CaseTag(case_id=case.id, tag="old")])

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}",
            json={"tags": ["new", "shiny"]},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["tags"]) == {"new", "shiny"}


# ---------------------------------------------------------------------------
# PATCH /test-cases/:id/steps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_steps_atomic_replace_succeeds(api_db: ApiDb) -> None:
    """Replace flushes a clean step set + bumps ``updated_at``."""
    user = await api_db.seed_user(email="tcw-replace@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-replace-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-R1")
    await api_db.add_all(
        [
            TestStep(
                case_id=case.id,
                order=0,
                action="old",
                expected="",
                code="x",
                target_kind=TargetKind.FE_WEB,
            )
        ]
    )

    body = {
        "steps": [
            _step_payload(action="new step 1"),
            _step_payload(action="new step 2"),
        ]
    }
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}/steps",
            json=body,
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    assert [s["action"] for s in resp.json()["steps"]] == ["new step 1", "new step 2"]


@pytest.mark.asyncio
async def test_patch_steps_validates_each_step_code_zero_tier(api_db: ApiDb) -> None:
    """ZERO tier rejects an action-only step inside the new list with the correct stepIndex."""
    user = await api_db.seed_user(email="tcw-replace-zero@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-replace-zero-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-R2")

    body = {
        "steps": [
            _step_payload(action="ok", code="ok"),
            _step_payload(action="bad", code=None),
        ]
    }
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}/steps",
            json=body,
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "STEPS_REQUIRE_CODE_IN_ZERO_LLM"
    assert envelope["details"]["stepIndex"] == 1


@pytest.mark.asyncio
async def test_patch_steps_concurrent_modification(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tcw-replace-409@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-replace-409-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-R3")

    stale = (case.updated_at - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    body = {"steps": [_step_payload(action="x", code="y")]}
    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}/steps",
            json=body,
            headers={"X-Workspace-Id": ws.id, "If-Unmodified-Since": stale},
        )
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# POST /test-cases/:id/steps (append)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_step_appends_with_monotonic_order(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tcw-append@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-append-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-A1")
    await api_db.add_all(
        [
            TestStep(
                case_id=case.id,
                order=0,
                action="first",
                expected="",
                code="x",
                target_kind=TargetKind.FE_WEB,
            )
        ]
    )

    body = _step_payload(action="appended", code="y")
    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/test-cases/{case.id}/steps",
            json=body,
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    orders = [s["order"] for s in resp.json()["steps"]]
    assert orders == sorted(orders)
    assert max(orders) == 1


@pytest.mark.asyncio
async def test_post_step_concurrent_appends_assign_distinct_orders(
    api_db: ApiDb,
) -> None:
    """Two concurrent appends serialise on the row-lock and land at distinct orders."""
    user = await api_db.seed_user(email="tcw-append-race@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-append-race-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-A2")

    async def _post(body: dict[str, object]) -> int:
        async with api_db.client(user) as c:
            r = await c.post(
                f"/api/v1/test-cases/{case.id}/steps",
                json=body,
                headers={"X-Workspace-Id": ws.id},
            )
        return r.status_code

    bodies = [
        _step_payload(action="a", code="a()"),
        _step_payload(action="b", code="b()"),
    ]
    results = await asyncio.gather(*(_post(b) for b in bodies))
    assert all(code == 201 for code in results), results

    async with api_db.maker() as session:
        steps = (await session.scalars(select(TestStep).where(TestStep.case_id == case.id))).all()
    orders = sorted(s.order for s in steps)
    assert orders == [0, 1], orders


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_steps_reorder_atomic_succeeds(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tcw-reorder@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-reorder-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-RR1")
    step_a = TestStep(
        case_id=case.id, order=0, action="A", expected="", code="x", target_kind=TargetKind.FE_WEB
    )
    step_b = TestStep(
        case_id=case.id, order=1, action="B", expected="", code="y", target_kind=TargetKind.FE_WEB
    )
    await api_db.add_all([step_a, step_b])

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}/steps/reorder",
            json={"stepIdsInOrder": [step_b.id, step_a.id]},
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text
    actions = [s["action"] for s in resp.json()["steps"]]
    assert actions == ["B", "A"]


@pytest.mark.asyncio
async def test_patch_steps_reorder_missing_id_returns_400(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="tcw-reorder-bad@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-reorder-bad-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-RR2")
    step_a = TestStep(
        case_id=case.id, order=0, action="A", expected="", code="x", target_kind=TargetKind.FE_WEB
    )
    step_b = TestStep(
        case_id=case.id, order=1, action="B", expected="", code="y", target_kind=TargetKind.FE_WEB
    )
    await api_db.add_all([step_a, step_b])

    async with api_db.client(user) as c:
        resp = await c.patch(
            f"/api/v1/test-cases/{case.id}/steps/reorder",
            json={"stepIdsInOrder": [step_a.id]},  # missing step_b
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 400, resp.text
    envelope = resp.json()["detail"]["error"]
    assert envelope["code"] == "INVALID_STEP_REORDER"
    assert envelope["details"]["missing"] == [step_b.id]


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_duplicate_clones_metadata_steps_tags_with_new_public_id(
    api_db: ApiDb,
) -> None:
    user = await api_db.seed_user(email="tcw-dup@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-dup-ws")
    suite = await _project_suite(api_db, ws.id)
    case = await _seed_case(api_db, suite.id, public_id="TC-D1", name="orig")
    await api_db.add_all(
        [
            TestStep(
                case_id=case.id,
                order=0,
                action="first",
                expected="",
                code="x",
                target_kind=TargetKind.FE_WEB,
            ),
            TestStep(
                case_id=case.id,
                order=1,
                action="second",
                expected="",
                code="y",
                target_kind=TargetKind.FE_WEB,
            ),
            CaseTag(case_id=case.id, tag="smoke"),
        ]
    )

    async with api_db.client(user) as c:
        resp = await c.post(
            f"/api/v1/test-cases/{case.id}/duplicate",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["public_id"] != "TC-D1"
    assert body["public_id"].startswith("TC-")
    assert body["name"] == "orig (Copy)"
    assert body["suite_id"] == suite.id
    assert [s["action"] for s in body["steps"]] == ["first", "second"]
    assert body["tags"] == ["smoke"]


# ---------------------------------------------------------------------------
# WS broadcast
# ---------------------------------------------------------------------------


# mypy: warn_unused_ignores=False
@pytest.mark.asyncio
async def test_post_test_cases_emits_case_created_ws_event(api_db: ApiDb) -> None:
    """A successful create publishes ``case.created`` on ``workspace:<wsId>``."""
    import fakeredis
    import fakeredis.aioredis
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    user = await api_db.seed_user(email="tcw-ws-event@example.com")
    ws = await api_db.member_workspace(user, slug="tcw-ws-event-ws")
    suite = await _project_suite(api_db, ws.id)

    server = fakeredis.FakeServer()
    redis_client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    received: list[bytes] = []

    app = api_db.app_for(user)
    app.state.ws_redis = redis_client

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"workspace:{ws.id}")

    async def _drain() -> None:
        # Skip the subscribe-ack frame.
        await pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
        for _ in range(5):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is not None:
                received.append(msg["data"])
                return

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/test-cases",
                json=_case_body(suite.id),
                headers={"X-Workspace-Id": ws.id},
            )
            assert resp.status_code == 201
            await _drain()

    await pubsub.aclose()  # type: ignore[no-untyped-call]
    await redis_client.aclose()  # type: ignore[no-untyped-call]
    assert received, "WS publish must reach the workspace:<id> channel"
    decoded = received[0].decode()
    assert "case.created" in decoded

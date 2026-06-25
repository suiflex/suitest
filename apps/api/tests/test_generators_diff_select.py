"""Integration tests for ``POST /api/v1/generators/diff-select`` (M6-1).

Drives the endpoint against a real DB (via ``api_db`` fixture).  The LLM path
is exercised using the ``mock`` provider — activating an ``LLMConfig`` with
``provider="mock"`` makes the workspace appear as CLOUD tier to the service.

Coverage:
  - ZERO tier (no LLM config): returns all cases with ``tier_used="fallback_full"``.
  - CLOUD/LOCAL tier (mock LLM): returns LLM-selected subset with ``tier_used="llm"``.
  - diff_text exceeds 50 000 chars: 400.
  - Unknown suite (no cases): 404.
  - Unauthenticated: 401.
  - Response shape: ``selected_case_ids``, ``rationale``, ``tier_used``,
    ``parsed_files_count``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from suitest_db.models.llm_config import LLMConfig
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority

if TYPE_CHECKING:
    import httpx
    from api_harness import ApiDb

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_DIFF = """\
--- a/src/auth.py
+++ b/src/auth.py
@@ -1,2 +1,4 @@
+def new_login(user, pwd):
+    return True
 pass
"""


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "ds-proj") -> Suite:
    project = Project(workspace_id=ws_id, slug=slug, name="DiffSelect P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="DS Suite", order=0)
    await api_db.add_all([suite])
    return suite


async def _add_cases(api_db: ApiDb, suite_id: str, workspace_id: str, count: int = 3) -> list[str]:
    """Insert ``count`` minimal test cases into ``suite_id``; return their ids.

    ``workspace_id`` is required by the ``before_insert`` listener that assigns
    ``public_id`` from the per-workspace ``TC`` sequence.
    """
    from suitest_db.models.case import TestCase
    from suitest_db.public_id import set_workspace_id

    cases: list[TestCase] = []
    for i in range(count):
        tc = TestCase(
            suite_id=suite_id,
            name=f"DS Case {i}",
            source=CaseSource.MANUAL,
            status=CaseStatus.ACTIVE,
            priority=Priority.P2,
        )
        set_workspace_id(tc, workspace_id)
        cases.append(tc)
    await api_db.add_all(cases)
    return [tc.id for tc in cases]


async def _activate_mock_llm(api_db: ApiDb, ws_id: str) -> None:
    """Register ``mock`` as the active LLM so the workspace resolves to CLOUD tier."""
    await api_db.add_all(
        [
            LLMConfig(
                workspace_id=ws_id,
                provider="mock",
                model="mock-1",
                api_key_encrypted=None,
                config_json={},
                is_active=True,
            )
        ]
    )


async def _post(
    client: httpx.AsyncClient, ws_id: str, payload: dict[str, object]
) -> httpx.Response:
    return await client.post(
        "/api/v1/generators/diff-select",
        headers={"X-Workspace-Id": ws_id},
        json=payload,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_select_zero_tier_returns_full_suite(api_db: ApiDb) -> None:
    """ZERO tier (no LLM configured) → all cases returned with fallback_full."""
    user = await api_db.seed_user(email="ds-zero@example.com")
    ws = await api_db.member_workspace(user, slug="ds-zero-ws")
    suite = await _project_suite(api_db, ws.id, slug="ds-zero-proj")
    case_ids = await _add_cases(api_db, suite.id, ws.id, count=3)

    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"suite_id": suite.id, "diff_text": _SIMPLE_DIFF})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tier_used"] == "fallback_full"
    assert set(body["selected_case_ids"]) == set(case_ids)
    assert body["rationale"] is None  # no rationale at ZERO tier
    assert body["parsed_files_count"] == 1


@pytest.mark.asyncio
async def test_diff_select_cloud_tier_returns_llm_selection(api_db: ApiDb) -> None:
    """CLOUD tier (mock LLM) → response comes back with tier_used="llm"."""
    user = await api_db.seed_user(email="ds-cloud@example.com")
    ws = await api_db.member_workspace(user, slug="ds-cloud-ws")
    suite = await _project_suite(api_db, ws.id, slug="ds-cloud-proj")
    case_ids = await _add_cases(api_db, suite.id, ws.id, count=4)
    await _activate_mock_llm(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"suite_id": suite.id, "diff_text": _SIMPLE_DIFF})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Mock provider echoes back non-JSON → fallback to all cases, but tier is "llm"
    assert body["tier_used"] == "llm"
    # All case ids are present (mock fallback) but the selected list is valid.
    assert isinstance(body["selected_case_ids"], list)
    assert all(cid in case_ids for cid in body["selected_case_ids"])
    assert body["parsed_files_count"] == 1


@pytest.mark.asyncio
async def test_diff_select_parsed_files_count_reflects_diff(api_db: ApiDb) -> None:
    """``parsed_files_count`` equals the number of files touched in the diff."""
    user = await api_db.seed_user(email="ds-count@example.com")
    ws = await api_db.member_workspace(user, slug="ds-count-ws")
    suite = await _project_suite(api_db, ws.id, slug="ds-count-proj")
    await _add_cases(api_db, suite.id, ws.id, count=1)

    multi_file_diff = """\
--- a/a.py
+++ b/a.py
@@ -1 +1,2 @@
+def f(): pass
--- a/b.py
+++ b/b.py
@@ -1 +1,2 @@
+def g(): pass
"""
    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"suite_id": suite.id, "diff_text": multi_file_diff})

    assert resp.status_code == 200, resp.text
    assert resp.json()["parsed_files_count"] == 2


@pytest.mark.asyncio
async def test_diff_select_diff_too_large_returns_400(api_db: ApiDb) -> None:
    """diff_text > 50 000 chars → HTTP 400."""
    user = await api_db.seed_user(email="ds-large@example.com")
    ws = await api_db.member_workspace(user, slug="ds-large-ws")
    suite = await _project_suite(api_db, ws.id, slug="ds-large-proj")

    huge_diff = "+" + "x" * 50_001

    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"suite_id": suite.id, "diff_text": huge_diff})

    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_diff_select_unknown_suite_returns_404(api_db: ApiDb) -> None:
    """Suite with no cases → 404."""
    user = await api_db.seed_user(email="ds-404@example.com")
    ws = await api_db.member_workspace(user, slug="ds-404-ws")
    # Create a suite but add NO cases — service raises SuiteNotFoundError.
    suite = await _project_suite(api_db, ws.id, slug="ds-404-proj")

    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"suite_id": suite.id, "diff_text": _SIMPLE_DIFF})

    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_diff_select_nonexistent_suite_id_returns_404(api_db: ApiDb) -> None:
    """Completely non-existent suite_id → 404."""
    user = await api_db.seed_user(email="ds-nosuit@example.com")
    ws = await api_db.member_workspace(user, slug="ds-nosuit-ws")

    async with api_db.client(user) as c:
        resp = await _post(
            c,
            ws.id,
            {"suite_id": "nonexistentsuiteid00000000000000", "diff_text": _SIMPLE_DIFF},
        )

    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_diff_select_unauthenticated_returns_401(api_db: ApiDb) -> None:
    """No auth token → 401."""
    user = await api_db.seed_user(email="ds-unauth@example.com")
    ws = await api_db.member_workspace(user, slug="ds-unauth-ws")
    suite = await _project_suite(api_db, ws.id, slug="ds-unauth-proj")

    import httpx
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport
    from suitest_api.main import create_app

    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/generators/diff-select",
                headers={"X-Workspace-Id": ws.id},
                json={"suite_id": suite.id, "diff_text": _SIMPLE_DIFF},
            )

    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_diff_select_empty_diff_zero_tier_returns_all_cases(api_db: ApiDb) -> None:
    """Empty diff at ZERO tier → all cases (full-run fallback)."""
    user = await api_db.seed_user(email="ds-empty@example.com")
    ws = await api_db.member_workspace(user, slug="ds-empty-ws")
    suite = await _project_suite(api_db, ws.id, slug="ds-empty-proj")
    case_ids = await _add_cases(api_db, suite.id, ws.id, count=2)

    async with api_db.client(user) as c:
        resp = await _post(c, ws.id, {"suite_id": suite.id, "diff_text": ""})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["selected_case_ids"]) == set(case_ids)
    assert body["parsed_files_count"] == 0

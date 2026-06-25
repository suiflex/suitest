"""M2-12 — GET /api/v1/test-cases/:id/export tests (docs/API.md §3.18).

Covers:
* Happy path: playwright (default) — 200, text/plain, Content-Disposition.
* All three targets: playwright (.spec.ts), cypress (.cy.js), selenium (.py).
* Steps with no ``code``: rendered as TODO comments, not an error.
* Invalid target: 400 INVALID_EXPORT_TARGET.
* Cross-workspace case: 404 (no enumeration oracle).
* Soft-deleted case: 404.
* Unauthenticated request: 401.
* CodeExport row actually written to DB after a successful request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import UUID  # noqa: F401 — type hint only
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.code_export import CodeExport
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseSource, TargetKind

if TYPE_CHECKING:
    from api_harness import ApiDb


# ---------------------------------------------------------------------------
# Seed helper
# ---------------------------------------------------------------------------


async def _seed_exportable_case(
    api_db: ApiDb,
    ws_id: str,
    *,
    slug: str = "exp-p",
    case_public_id: str = "TC-EX1",
    steps_code: list[str | None] | None = None,
) -> tuple[Project, Suite, TestCase, list[TestStep]]:
    """Seed project + suite + case with configurable steps."""
    if steps_code is None:
        steps_code = ["await page.goto('/login');", "await page.click('#submit');"]

    project = Project(workspace_id=ws_id, slug=slug, name="Export P")
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
    step_rows: list[TestStep] = []
    for i, code in enumerate(steps_code):
        step = TestStep(
            case_id=case.id,
            order=i,
            action=f"Step {i + 1}",
            expected=f"Expected {i + 1}",
            code=code,
            mcp_provider="playwright-mcp",
            target_kind=TargetKind.FE_WEB,
        )
        step_rows.append(step)
    await api_db.add_all(step_rows)
    return project, suite, case, step_rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_playwright_200(api_db: ApiDb) -> None:
    """Playwright (default) — 200, correct content-type, content-disposition."""
    user = await api_db.seed_user(email="export-pw@example.com")
    ws = await api_db.member_workspace(user, slug="export-pw-ws")
    _, _, case, _ = await _seed_exportable_case(api_db, ws.id)

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export",
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 200, resp.text
    assert "text/plain" in resp.headers["content-type"]
    cd = resp.headers["content-disposition"]
    assert "attachment" in cd
    assert f"{case.public_id}.spec.ts" in cd
    body = resp.text
    assert "import { test, expect } from '@playwright/test';" in body
    assert "Login flow" in body
    assert "await page.goto('/login');" in body
    assert "await page.click('#submit');" in body


@pytest.mark.asyncio
async def test_export_cypress_200(api_db: ApiDb) -> None:
    """cypress target returns .cy.js Cypress scaffold."""
    user = await api_db.seed_user(email="export-cy@example.com")
    ws = await api_db.member_workspace(user, slug="export-cy-ws")
    _, _, case, _ = await _seed_exportable_case(
        api_db, ws.id, slug="exp-cy-p", case_public_id="TC-EX2"
    )

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export?target=cypress",
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 200, resp.text
    cd = resp.headers["content-disposition"]
    assert f"{case.public_id}.cy.js" in cd
    body = resp.text
    assert "describe(" in body
    assert "it(" in body
    assert "await page.goto('/login');" in body


@pytest.mark.asyncio
async def test_export_selenium_200(api_db: ApiDb) -> None:
    """selenium target returns Python Selenium test file."""
    user = await api_db.seed_user(email="export-se@example.com")
    ws = await api_db.member_workspace(user, slug="export-se-ws")
    _, _, case, _ = await _seed_exportable_case(
        api_db, ws.id, slug="exp-se-p", case_public_id="TC-EX3"
    )

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export?target=selenium",
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 200, resp.text
    cd = resp.headers["content-disposition"]
    assert f"{case.public_id}.py" in cd
    body = resp.text
    assert "def test_" in body
    assert "webdriver.Chrome()" in body
    assert "driver.quit()" in body
    assert "Login flow" in body


@pytest.mark.asyncio
async def test_export_no_code_steps_renders_todo(api_db: ApiDb) -> None:
    """Steps with code=None render as TODO comments — no error."""
    user = await api_db.seed_user(email="export-nocode@example.com")
    ws = await api_db.member_workspace(user, slug="export-nocode-ws")
    _, _, case, _ = await _seed_exportable_case(
        api_db,
        ws.id,
        slug="exp-nc-p",
        case_public_id="TC-EX4",
        steps_code=[None, "await page.click('#btn');"],
    )

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export",
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 200, resp.text
    assert "TODO: no code defined for this step" in resp.text
    assert "await page.click('#btn');" in resp.text


@pytest.mark.asyncio
async def test_export_invalid_target_returns_400(api_db: ApiDb) -> None:
    """Unknown target → 400 INVALID_EXPORT_TARGET."""
    user = await api_db.seed_user(email="export-bad@example.com")
    ws = await api_db.member_workspace(user, slug="export-bad-ws")
    _, _, case, _ = await _seed_exportable_case(
        api_db, ws.id, slug="exp-bad-p", case_public_id="TC-EX5"
    )

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export?target=jest",
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error"]["code"] == "INVALID_EXPORT_TARGET"


@pytest.mark.asyncio
async def test_export_cross_workspace_returns_404(api_db: ApiDb) -> None:
    """Case in another workspace → 404 (no enumeration oracle)."""
    user = await api_db.seed_user(email="export-xws@example.com")
    ws = await api_db.member_workspace(user, slug="export-xws-ws")
    other = await api_db.seed_workspace(slug="export-xws-other", name="Other")
    _, _, case, _ = await _seed_exportable_case(
        api_db, other.id, slug="exp-xws-p", case_public_id="TC-EX6"
    )

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export",
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_soft_deleted_returns_404(api_db: ApiDb) -> None:
    """Tombstoned case → 404."""
    user = await api_db.seed_user(email="export-del@example.com")
    ws = await api_db.member_workspace(user, slug="export-del-ws")
    _, _, case, _ = await _seed_exportable_case(
        api_db, ws.id, slug="exp-del-p", case_public_id="TC-EX7"
    )

    async with api_db.maker() as session:
        await session.execute(
            update(TestCase).where(TestCase.id == case.id).values(deleted_at=datetime.now(UTC))
        )
        await session.commit()

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export",
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_writes_code_export_row(api_db: ApiDb) -> None:
    """Successful export persists a CodeExport row with matching text."""
    user = await api_db.seed_user(email="export-row@example.com")
    ws = await api_db.member_workspace(user, slug="export-row-ws")
    _, _, case, _ = await _seed_exportable_case(
        api_db, ws.id, slug="exp-row-p", case_public_id="TC-EX8"
    )

    async with api_db.client(user) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export?target=playwright",
            headers={"X-Workspace-Id": ws.id},
        )
    assert resp.status_code == 200, resp.text

    async with api_db.maker() as session:
        rows = list(
            await session.scalars(
                select(CodeExport).where(
                    CodeExport.case_id == case.id,
                    CodeExport.target == "playwright",
                )
            )
        )
    assert len(rows) == 1
    assert rows[0].exported_code_text == resp.text


@pytest.mark.asyncio
async def test_export_unauthenticated_returns_401(api_db: ApiDb) -> None:
    """No authentication → 401."""
    user = await api_db.seed_user(email="export-noauth@example.com")
    ws = await api_db.member_workspace(user, slug="export-noauth-ws")
    _, _, case, _ = await _seed_exportable_case(
        api_db, ws.id, slug="exp-noauth-p", case_public_id="TC-EX9"
    )

    async with api_db.client(None) as c:
        resp = await c.get(
            f"/api/v1/test-cases/{case.id}/export",
            headers={"X-Workspace-Id": ws.id},
        )

    assert resp.status_code == 401

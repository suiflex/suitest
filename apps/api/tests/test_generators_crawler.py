"""Tests for ``POST /api/v1/generators/crawler`` (M2 Task 3).

Drive the heuristic crawler end-to-end against a real DB but a MOCKED
:class:`McpInvoker` (no browser): the router's ``_build_mcp_invoker`` is
monkeypatched to return a canned fake serving a small synthetic 2-page site, so
we can assert persistence (GeneratorRun row + DRAFT cases), the playwright-mcp
provider on every step, strict SSE framing, and the auth/scope contract
(401 / 403 / 404).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import suitest_api.routers.generators as generators_router
from sqlalchemy import select
from suitest_db.models.case import TestCase, TestStep
from suitest_db.models.generator_run import GeneratorRun
from suitest_db.models.project import Project, Suite
from suitest_mcp.models import McpToolResult
from suitest_shared.domain.enums import CaseSource, CaseStatus, Role

if TYPE_CHECKING:
    import httpx
    from api_harness import ApiDb
    from suitest_mcp.invoker import InvokeContext

_ORIGIN = "https://crawl.test"
_INDEX = f"{_ORIGIN}/"
_NEXT = f"{_ORIGIN}/next"

_SITE: dict[str, dict[str, object]] = {
    _INDEX: {
        "forms": [
            {
                "id": "contact",
                "method": "post",
                "fields": [
                    {"name": "email", "type": "email", "selector": "#email"},
                    {"name": "msg", "type": "textarea", "selector": "#msg"},
                ],
                "submit_selector": "#send",
            }
        ],
        "links": [_NEXT],
    },
    _NEXT: {"forms": [], "links": [_INDEX]},
}


class _FakeInvoker:
    def __init__(self) -> None:
        self._current = ""

    async def invoke(
        self,
        *,
        explicit_provider: str | None,
        tool: str,
        arguments: dict[str, object],
        ctx: InvokeContext,
    ) -> McpToolResult:
        if tool == "browser.navigate":
            self._current = str(arguments["url"])
            return McpToolResult(ok=True, output={"result": {"loaded": True}}, duration_ms=1)
        if tool == "browser.evaluate":
            expr = str(arguments.get("expression", ""))
            if "__suitest_console_errors__" in expr:
                return McpToolResult(ok=True, output={"result": []}, duration_ms=1)
            payload = _SITE.get(self._current, {"forms": [], "links": []})
            return McpToolResult(ok=True, output={"result": payload}, duration_ms=1)
        return McpToolResult(ok=True, output={}, duration_ms=1)


@pytest.fixture(autouse=True)
def _mock_invoker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the router's real invoker wiring with the canned fake."""
    monkeypatch.setattr(
        generators_router,
        "_build_mcp_invoker",
        lambda workspace_id, request: _FakeInvoker(),
    )


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "gen-crawl-proj") -> Suite:
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        lines = block.split("\n")
        assert lines[0].startswith("event: "), f"bad event line: {lines[0]!r}"
        assert lines[1].startswith("data: "), f"bad data line: {lines[1]!r}"
        events.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return events


async def _read_stream(client: httpx.AsyncClient, ws_id: str, payload: dict[str, object]) -> str:
    resp = await client.post(
        "/api/v1/generators/crawler",
        headers={"X-Workspace-Id": ws_id},
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    return resp.text


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_emits_smoke_and_form_cases(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cr-ok@example.com")
    ws = await api_db.member_workspace(user, slug="cr-ok-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(c, ws.id, {"target_suite_id": suite.id, "start_url": _INDEX})
    events = _parse_sse(body)
    assert events[0][0] == "progress"
    assert events[-1][0] == "complete"
    case_events = [d for k, d in events if k == "case"]
    kinds = [d["case_kind"] for d in case_events]
    assert kinds.count("smoke") == 2  # index + next
    assert kinds.count("form") == 1  # contact form on index


@pytest.mark.asyncio
async def test_crawl_persists_generator_run(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cr-run@example.com")
    ws = await api_db.member_workspace(user, slug="cr-run-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(c, ws.id, {"target_suite_id": suite.id, "start_url": _INDEX})
    complete = _parse_sse(body)[-1][1]
    async with api_db.maker() as session:
        run = (
            await session.scalars(select(GeneratorRun).where(GeneratorRun.workspace_id == ws.id))
        ).one()
        assert run.source == "crawler"
        assert run.duration_ms is not None
        assert run.output_case_ids_json == complete["public_ids"]
        assert len(run.output_case_ids_json) == complete["cases_created"]


@pytest.mark.asyncio
async def test_crawl_cases_persist_as_draft(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cr-draft@example.com")
    ws = await api_db.member_workspace(user, slug="cr-draft-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        await _read_stream(c, ws.id, {"target_suite_id": suite.id, "start_url": _INDEX})
    async with api_db.maker() as session:
        cases = (await session.scalars(select(TestCase).where(TestCase.suite_id == suite.id))).all()
        assert cases
        assert all(c.status is CaseStatus.DRAFT for c in cases)
        assert all(c.source is CaseSource.HEURISTIC_CRAWL for c in cases)
        assert all(c.generated_by == "url-crawler" for c in cases)


@pytest.mark.asyncio
async def test_crawl_steps_use_playwright_mcp(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cr-mcp@example.com")
    ws = await api_db.member_workspace(user, slug="cr-mcp-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        await _read_stream(c, ws.id, {"target_suite_id": suite.id, "start_url": _INDEX})
    async with api_db.maker() as session:
        steps = (
            await session.scalars(
                select(TestStep)
                .join(TestCase, TestStep.case_id == TestCase.id)
                .where(TestCase.suite_id == suite.id)
            )
        ).all()
        assert steps
        assert all(s.mcp_provider == "playwright-mcp" for s in steps)


@pytest.mark.asyncio
async def test_crawl_no_form_cases_when_disabled(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cr-noform@example.com")
    ws = await api_db.member_workspace(user, slug="cr-noform-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(
            c,
            ws.id,
            {
                "target_suite_id": suite.id,
                "start_url": _INDEX,
                "options": {"include_form_cases": False},
            },
        )
    case_events = [d for k, d in _parse_sse(body) if k == "case"]
    assert all(d["case_kind"] == "smoke" for d in case_events)


@pytest.mark.asyncio
async def test_crawl_sse_format_strict(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cr-sse@example.com")
    ws = await api_db.member_workspace(user, slug="cr-sse-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(c, ws.id, {"target_suite_id": suite.id, "start_url": _INDEX})
    assert body.endswith("\n\n")
    events = _parse_sse(body)
    assert all(k in {"progress", "case", "complete", "error"} for k, _ in events)


@pytest.mark.asyncio
async def test_crawl_unauthenticated_returns_401(api_db: ApiDb) -> None:
    async with api_db.client(None) as c:
        resp = await c.post(
            "/api/v1/generators/crawler",
            headers={"X-Workspace-Id": "00000000-0000-0000-0000-000000000000"},
            json={"target_suite_id": "x", "start_url": _INDEX},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_crawl_viewer_role_forbidden(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cr-viewer@example.com")
    ws = await api_db.seed_workspace(slug="cr-viewer-ws", name="V")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/crawler",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": suite.id, "start_url": _INDEX},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_crawl_unknown_suite_returns_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="cr-404@example.com")
    ws = await api_db.member_workspace(user, slug="cr-404-ws")
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/crawler",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": "nonexistent-suite-id", "start_url": _INDEX},
        )
    assert resp.status_code == 404

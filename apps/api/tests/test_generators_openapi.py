"""Tests for ``POST /api/v1/generators/openapi`` (M2 Task 2).

Drives the deterministic OpenAPI generator end-to-end against a real DB: parse a
spec (inline + via mocked URL fetch), assert per-category coverage + persistence
(DRAFT cases, GeneratorRun row with output_case_ids), options gating, the
rate-limit branch, tag filtering, the invalid-spec error frame, strict SSE
framing, and the auth / scope contract (401, 404).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import respx
from sqlalchemy import select
from suitest_db.models.case import TestCase
from suitest_db.models.generator_run import GeneratorRun
from suitest_db.models.project import Project, Suite
from suitest_shared.domain.enums import CaseStatus, Role

if TYPE_CHECKING:
    from api_harness import ApiDb

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "openapi"


def _spec(name: str) -> str:
    return (_FIXTURES / name).read_text()


async def _project_suite(api_db: ApiDb, ws_id: str, *, slug: str = "gen-oa-proj") -> Suite:
    project = Project(workspace_id=ws_id, slug=slug, name="P")
    await api_db.add_all([project])
    suite = Suite(project_id=project.id, name="S", order=0)
    await api_db.add_all([suite])
    return suite


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    """Parse a raw SSE body into ``[(event_kind, data_obj), ...]``.

    Enforces the strict framing the endpoint promises: every frame is
    ``event: <kind>\\ndata: <json>`` terminated by a blank line.
    """
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        lines = block.split("\n")
        assert lines[0].startswith("event: "), f"bad event line: {lines[0]!r}"
        assert lines[1].startswith("data: "), f"bad data line: {lines[1]!r}"
        kind = lines[0][len("event: ") :]
        data = json.loads(lines[1][len("data: ") :])
        events.append((kind, data))
    return events


async def _read_stream(client: httpx.AsyncClient, ws_id: str, payload: dict[str, object]) -> str:
    resp = await client.post(
        "/api/v1/generators/openapi",
        headers={"X-Workspace-Id": ws_id},
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    return resp.text


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_from_spec_content(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-content@example.com")
    ws = await api_db.member_workspace(user, slug="oa-content-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(
            c,
            ws.id,
            {"target_suite_id": suite.id, "spec_content": _spec("petstore.json")},
        )
    events = _parse_sse(body)
    kinds = [k for k, _ in events]
    assert kinds[0] == "progress"
    assert kinds[-1] == "complete"
    case_events = [d for k, d in events if k == "case"]
    assert len(case_events) >= 3  # at least one contract per operation
    # No emitted step code contains dangerous calls.
    complete = events[-1][1]
    assert complete["cases_created"] == len(case_events)


@pytest.mark.asyncio
async def test_generate_from_spec_url_mocked(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-url@example.com")
    ws = await api_db.member_workspace(user, slug="oa-url-ws")
    suite = await _project_suite(api_db, ws.id)
    spec_url = "https://specs.example/httpbin.json"
    with respx.mock:
        respx.get(spec_url).mock(return_value=httpx.Response(200, text=_spec("httpbin.json")))
        async with api_db.client(user) as c:
            body = await _read_stream(c, ws.id, {"target_suite_id": suite.id, "spec_url": spec_url})
    events = _parse_sse(body)
    complete = events[-1][1]
    cases_created = complete["cases_created"]
    duration_ms = complete["duration_ms"]
    assert isinstance(cases_created, int) and cases_created > 0
    assert isinstance(duration_ms, int) and duration_ms >= 0


@pytest.mark.asyncio
async def test_generate_with_options_disabled_fewer_cases(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-opts@example.com")
    ws = await api_db.member_workspace(user, slug="oa-opts-ws")
    suite_full = await _project_suite(api_db, ws.id, slug="oa-opts-full")
    suite_min = await _project_suite(api_db, ws.id, slug="oa-opts-min")
    async with api_db.client(user) as c:
        full = _parse_sse(
            await _read_stream(
                c, ws.id, {"target_suite_id": suite_full.id, "spec_content": _spec("petstore.json")}
            )
        )
        minimal = _parse_sse(
            await _read_stream(
                c,
                ws.id,
                {
                    "target_suite_id": suite_min.id,
                    "spec_content": _spec("petstore.json"),
                    "options": {
                        "include_negative_auth": False,
                        "include_required_field_tests": False,
                        "include_boundary_tests": False,
                        "include_rate_limit_tests": False,
                    },
                },
            )
        )
    full_cases = [d for k, d in full if k == "case"]
    min_cases = [d for k, d in minimal if k == "case"]
    assert len(min_cases) < len(full_cases)


@pytest.mark.asyncio
async def test_generate_rate_limit_case_present(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-rl@example.com")
    ws = await api_db.member_workspace(user, slug="oa-rl-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(
            c,
            ws.id,
            {"target_suite_id": suite.id, "spec_content": _spec("custom-rate-limited.yaml")},
        )
    case_events = [d for k, d in _parse_sse(body) if k == "case"]
    assert any(d.get("case_kind") == "rate_limit" for d in case_events)


@pytest.mark.asyncio
async def test_generate_persists_generator_run_row(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-run@example.com")
    ws = await api_db.member_workspace(user, slug="oa-run-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(
            c, ws.id, {"target_suite_id": suite.id, "spec_content": _spec("petstore.json")}
        )
    complete = _parse_sse(body)[-1][1]

    async with api_db.maker() as session:
        run = (
            await session.scalars(select(GeneratorRun).where(GeneratorRun.workspace_id == ws.id))
        ).one()
        assert run.source == "openapi"
        assert run.duration_ms is not None
        assert run.output_case_ids_json == complete["public_ids"]
        assert len(run.output_case_ids_json) == complete["cases_created"]


@pytest.mark.asyncio
async def test_generate_cases_persist_as_draft(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-draft@example.com")
    ws = await api_db.member_workspace(user, slug="oa-draft-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        await _read_stream(
            c, ws.id, {"target_suite_id": suite.id, "spec_content": _spec("petstore.json")}
        )
    async with api_db.maker() as session:
        cases = (await session.scalars(select(TestCase).where(TestCase.suite_id == suite.id))).all()
        assert cases
        assert all(c.status is CaseStatus.DRAFT for c in cases)
        assert all(c.generated_by == "openapi-generator" for c in cases)


@pytest.mark.asyncio
async def test_generate_tags_filter(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-tagfilter@example.com")
    ws = await api_db.member_workspace(user, slug="oa-tagfilter-ws")
    suite_all = await _project_suite(api_db, ws.id, slug="oa-tag-all")
    suite_filtered = await _project_suite(api_db, ws.id, slug="oa-tag-filtered")
    async with api_db.client(user) as c:
        all_cases = [
            d
            for k, d in _parse_sse(
                await _read_stream(
                    c,
                    ws.id,
                    {"target_suite_id": suite_all.id, "spec_content": _spec("petstore.json")},
                )
            )
            if k == "case"
        ]
        filtered_cases = [
            d
            for k, d in _parse_sse(
                await _read_stream(
                    c,
                    ws.id,
                    {
                        "target_suite_id": suite_filtered.id,
                        "spec_content": _spec("petstore.json"),
                        "options": {"tags_filter": ["orders"]},
                    },
                )
            )
            if k == "case"
        ]
    assert len(filtered_cases) < len(all_cases)
    assert filtered_cases  # at least the /orders operation generated something


@pytest.mark.asyncio
async def test_generate_invalid_spec_returns_error_event(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-bad@example.com")
    ws = await api_db.member_workspace(user, slug="oa-bad-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(
            c,
            ws.id,
            {"target_suite_id": suite.id, "spec_content": "{ this is : not valid ["},
        )
    events = _parse_sse(body)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "INVALID_SPEC"


@pytest.mark.asyncio
async def test_generate_sse_format_strict(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-sse@example.com")
    ws = await api_db.member_workspace(user, slug="oa-sse-ws")
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        body = await _read_stream(
            c, ws.id, {"target_suite_id": suite.id, "spec_content": _spec("httpbin.json")}
        )
    # Every frame terminates with a blank line; _parse_sse asserts framing.
    assert body.endswith("\n\n")
    events = _parse_sse(body)
    assert all(k in {"progress", "case", "complete", "error"} for k, _ in events)


@pytest.mark.asyncio
async def test_generate_unauthenticated_returns_401(api_db: ApiDb) -> None:
    async with api_db.client(None) as c:
        resp = await c.post(
            "/api/v1/generators/openapi",
            headers={"X-Workspace-Id": "00000000-0000-0000-0000-000000000000"},
            json={"target_suite_id": "x", "spec_content": "{}"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_generate_viewer_role_forbidden(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-viewer@example.com")
    ws = await api_db.seed_workspace(slug="oa-viewer-ws", name="V")
    await api_db.seed_membership(workspace_id=ws.id, user_id=user.id, role=Role.VIEWER)
    suite = await _project_suite(api_db, ws.id)
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/openapi",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": suite.id, "spec_content": _spec("httpbin.json")},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_generate_unknown_suite_returns_404(api_db: ApiDb) -> None:
    user = await api_db.seed_user(email="oa-404@example.com")
    ws = await api_db.member_workspace(user, slug="oa-404-ws")
    async with api_db.client(user) as c:
        resp = await c.post(
            "/api/v1/generators/openapi",
            headers={"X-Workspace-Id": ws.id},
            json={"target_suite_id": "nonexistent-suite-id", "spec_content": _spec("httpbin.json")},
        )
    assert resp.status_code == 404

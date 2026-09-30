"""Unit tests for the zero-install web recorder proxy and agent script (M2 Task 4)."""

from __future__ import annotations

import pytest
from suitest_api.routers.generators import (
    get_recorder_agent_script,
)


@pytest.mark.asyncio
async def test_get_recorder_agent_script():
    """Verify get_recorder_agent_script returns javascript media type."""
    response = await get_recorder_agent_script()
    assert response.media_type == "application/javascript"
    assert len(response.body) > 0
    assert b"Suitest" in response.body or b"function" in response.body


@pytest.mark.asyncio
async def test_append_event_normalizes_naive_datetime():
    """Verify offset-naive expires_at from SQLite does not cause TypeError."""
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import Request, Response
    from suitest_api.routers.generators import append_recorder_session_event
    from suitest_shared.schemas.generator_input import RecorderEvent, RecorderEventKind

    naive_future = datetime.now() + timedelta(minutes=10)
    assert naive_future.tzinfo is None  # confirm naive

    mock_row = MagicMock()
    mock_row.id = "rec_naive_123"
    mock_row.workspace_id = "ws_test"
    mock_row.status = "active"
    mock_row.expires_at = naive_future
    mock_row.captured_events_json = [{"kind": "navigate"}]

    mock_session = AsyncMock()

    class MockRepo:
        def __init__(self, s):
            pass

        async def get_by_id(self, sid, workspace_id=None):
            return mock_row

    class MockManager:
        def __init__(self, *args, **kwargs):
            pass

        async def append_event(self, sid, wid, payload):
            pass

    import suitest_api.routers.generators as gen_mod

    orig_repo = gen_mod.RecorderSessionRepo
    orig_mgr = gen_mod.RecorderSessionManager
    orig_invoker = gen_mod._build_mcp_invoker
    gen_mod.RecorderSessionRepo = MockRepo
    gen_mod.RecorderSessionManager = MockManager
    gen_mod._build_mcp_invoker = MagicMock(return_value=MagicMock())

    try:
        mock_req = MagicMock(spec=Request)
        mock_req.headers = {"x-workspace-id": "ws_test"}
        mock_req.query_params = {}
        mock_resp = MagicMock(spec=Response)
        mock_resp.headers = {}

        event_payload = RecorderEvent(
            kind=RecorderEventKind.CLICK,
            timestamp=datetime.now(),
            selector="#btn-submit",
        )

        res = await append_recorder_session_event(
            session_id="rec_naive_123",
            payload=event_payload,
            request=mock_req,
            response=mock_resp,
            session=mock_session,
        )

        assert res["ok"] is True
        assert res["count"] == 1
        assert mock_resp.headers["Access-Control-Allow-Origin"] == "*"
    finally:
        gen_mod.RecorderSessionRepo = orig_repo
        gen_mod.RecorderSessionManager = orig_mgr
        gen_mod._build_mcp_invoker = orig_invoker


@pytest.mark.asyncio
async def test_options_recorder_session_sync():
    """Verify CORS preflight options for sync endpoint returns 204 with PUT allowed."""
    from unittest.mock import MagicMock

    from fastapi import Request
    from suitest_api.routers.generators import options_recorder_session_sync

    mock_req = MagicMock(spec=Request)
    mock_req.headers = {"origin": "https://example.com"}

    resp = await options_recorder_session_sync(session_id="rec_test", request=mock_req)
    assert resp.status_code == 204
    assert resp.headers["Access-Control-Allow-Origin"] == "https://example.com"
    assert "PUT" in resp.headers["Access-Control-Allow-Methods"]


@pytest.mark.asyncio
async def test_sync_recorder_session_events_success():
    """Verify sync_recorder_session_events replaces events and returns updated count."""
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    import suitest_api.routers.generators as gen_mod
    from fastapi import Request, Response
    from suitest_api.routers.generators import sync_recorder_session_events
    from suitest_shared.schemas.generator_input import RecorderSyncRequest

    mock_session = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = "rec_sync_123"
    mock_row.workspace_id = "ws_sync"
    mock_row.status = "active"
    mock_row.expires_at = datetime.now(tz=UTC) + timedelta(minutes=10)

    class MockRepo:
        def __init__(self, s):
            pass

        async def get_by_id(self, sid, workspace_id=None):
            return mock_row

    class MockManager:
        def __init__(self, *args, **kwargs):
            pass

        async def sync_events(self, sid, wid, events):
            pass

    orig_repo = gen_mod.RecorderSessionRepo
    orig_mgr = gen_mod.RecorderSessionManager
    orig_invoker = gen_mod._build_mcp_invoker
    gen_mod.RecorderSessionRepo = MockRepo
    gen_mod.RecorderSessionManager = MockManager
    gen_mod._build_mcp_invoker = MagicMock(return_value=MagicMock())

    try:
        mock_req = MagicMock(spec=Request)
        mock_req.headers = {"x-workspace-id": "ws_sync"}
        mock_req.query_params = {}
        mock_resp = MagicMock(spec=Response)
        mock_resp.headers = {}

        sync_payload = RecorderSyncRequest(
            events=[
                {"kind": "navigate", "url": "https://example.com/app"},
                {"kind": "click", "selector": "#btn-ok"},
            ]
        )

        res = await sync_recorder_session_events(
            session_id="rec_sync_123",
            payload=sync_payload,
            request=mock_req,
            response=mock_resp,
            session=mock_session,
        )

        assert res["ok"] is True
        assert res["count"] == 2
        assert mock_resp.headers["Access-Control-Allow-Origin"] == "*"
    finally:
        gen_mod.RecorderSessionRepo = orig_repo
        gen_mod.RecorderSessionManager = orig_mgr
        gen_mod._build_mcp_invoker = orig_invoker

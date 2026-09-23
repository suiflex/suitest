"""Unit tests for the zero-install web recorder proxy and agent script (M2 Task 4)."""

from __future__ import annotations

import pytest
from suitest_api.routers.generators import (
    _inject_recorder_script,
    get_recorder_agent_script,
)


def test_inject_recorder_script_in_head():
    """Verify script and base tag are injected inside the <head> tag."""
    html = "<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
    result = _inject_recorder_script(
        html, session_id="rec_123", target_url="https://example.com/app"
    )

    assert '<base href="https://example.com/app">' in result
    assert '<script src="/recorder_agent.js" data-session-id="rec_123"></script>' in result
    assert result.index('<base href="https://example.com/app">') > result.index("<head>")
    assert result.index('<base href="https://example.com/app">') < result.index("</head>")


def test_inject_recorder_script_in_body_fallback():
    """Verify script and base tag are injected inside <body> if no <head> exists."""
    html = "<html><body><h1>No head</h1></body></html>"
    result = _inject_recorder_script(
        html, session_id="rec_456", target_url="https://example.com/login"
    )

    assert '<base href="https://example.com/login">' in result
    assert '<script src="/recorder_agent.js" data-session-id="rec_456"></script>' in result
    assert result.index('<base href="https://example.com/login">') > result.index("<body>")


def test_inject_recorder_script_no_head_or_body():
    """Verify script and base tag are prepended if neither head nor body exists."""
    html = "<div>Fragment</div>"
    result = _inject_recorder_script(
        html, session_id="rec_789", target_url="https://example.com/fragment"
    )

    assert result.startswith('<base href="https://example.com/fragment">')
    assert 'data-session-id="rec_789"' in result


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


def test_validate_target_url_ssrf_guards():
    """Verify SSRF guards block private IPs, loopback, cloud metadata, and internal hostnames."""
    from fastapi import HTTPException
    from suitest_api.routers.generators import _validate_target_url

    # Localhost and loopback
    with pytest.raises(HTTPException) as exc1:
        _validate_target_url("http://localhost:8080")
    assert exc1.value.status_code == 400

    with pytest.raises(HTTPException) as exc2:
        _validate_target_url("http://127.0.0.1:3000")
    assert exc2.value.status_code == 400

    # Private IP literals
    with pytest.raises(HTTPException) as exc3:
        _validate_target_url("http://192.168.1.10/admin")
    assert exc3.value.status_code == 400

    with pytest.raises(HTTPException) as exc4:
        _validate_target_url("http://10.0.0.1")
    assert exc4.value.status_code == 400

    # Link-local / cloud metadata service
    with pytest.raises(HTTPException) as exc5:
        _validate_target_url("http://169.254.169.254/latest/meta-data")
    assert exc5.value.status_code == 400

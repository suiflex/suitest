"""Unit tests for the recorder session manager and codegen step conversion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_agent.generators.recorder import (
    RecorderEvent,
    RecorderEventKind,
    RecorderSessionManager,
)
from suitest_mcp.invoker import NullPublisher
from suitest_shared.schemas.generator_input import (
    RecorderFinalizeRequest,
    RecorderSessionStartRequest,
)


class _FakeSessionRow:
    def __init__(
        self,
        session_id: str = "rec_sess_test",
        workspace_id: str = "ws_test",
        status: str = "active",
        events: list[dict[str, Any]] | None = None,
        mcp_provider: str = "playwright-mcp",
        start_url: str = "https://app.example.com",
    ) -> None:
        self.id = session_id
        self.workspace_id = workspace_id
        self.status = status
        self.events = events or []
        self.captured_events_json = self.events
        self.mcp_provider = mcp_provider
        self.expires_at = datetime.now(tz=UTC) + timedelta(minutes=30)
        self.start_url = start_url
        self.browser_session_handle = "bsh_1"
        self.created_by_user_id = "usr_1"
        self.ws_room = f"recorder:{session_id}"


class _FakeRecorderRepo:
    def __init__(self) -> None:
        self.sessions: dict[str, _FakeSessionRow] = {}

    async def create(self, data: Any) -> _FakeSessionRow:
        row = _FakeSessionRow(
            session_id=f"rec_sess_{len(self.sessions) + 1}",
            workspace_id=data.workspace_id,
            status="active",
            events=[],
            mcp_provider=data.mcp_provider,
            start_url=data.start_url,
        )
        self.sessions[row.id] = row
        return row

    async def get_by_id(self, session_id: str, workspace_id: str) -> _FakeSessionRow | None:
        row = self.sessions.get(session_id)
        if row and row.workspace_id == workspace_id:
            return row
        return None

    async def append_event(
        self, session_id: str, event_dict: dict[str, Any], workspace_id: str | None = None
    ) -> _FakeSessionRow:
        row = self.sessions[session_id]
        row.events.append(event_dict)
        return row

    async def set_finalized(self, session_id: str, generated_case_id: str) -> _FakeSessionRow:
        row = self.sessions[session_id]
        row.status = "finalized"
        return row

    async def set_cancelled(self, session_id: str) -> _FakeSessionRow:
        row = self.sessions[session_id]
        row.status = "cancelled"
        return row

    async def update_status(
        self, session_id: str, status: str, workspace_id: str | None = None
    ) -> _FakeSessionRow:
        row = self.sessions[session_id]
        row.status = status
        return row

    async def mark_finalized(
        self, session_id: str, finalized_case_id: str, finalized_at: Any, workspace_id: str
    ) -> None:
        row = self.sessions[session_id]
        row.status = "finalized"


@pytest.mark.asyncio
async def test_recorder_session_manager_with_null_publisher() -> None:
    """When redis is None or NullPublisher (local bundle mode), session starts and appends cleanly."""
    fake_invoker = MagicMock()
    fake_invoker.invoke = AsyncMock(
        return_value=MagicMock(success=True, output={"browser_url": "http://localhost:9222"})
    )
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(
        mcp_invoker=fake_invoker,
        recorder_repo=repo,  # type: ignore[arg-type]
        redis=NullPublisher(),
    )

    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://app.example.com",
        mcp_provider="playwright-mcp",
    )
    row, browser_url = await mgr.start("ws_1", "usr_1", req)
    assert row.id.startswith("rec_sess_")
    assert row.status == "active"
    assert browser_url == "http://localhost:9222"

    # Append an event
    now = datetime.now(tz=UTC)
    event = RecorderEvent(
        kind=RecorderEventKind.NAVIGATE,
        timestamp=now,
        url="https://app.example.com/login",
    )
    await mgr.append_event(row.id, "ws_1", event)
    assert len(repo.sessions[row.id].events) == 1
    assert repo.sessions[row.id].events[0]["kind"] == "navigate"
    assert repo.sessions[row.id].events[0]["url"] == "https://app.example.com/login"


@pytest.mark.asyncio
async def test_recorder_session_manager_with_none_redis() -> None:
    """When redis is explicitly None, no exception is raised on publish."""
    fake_invoker = MagicMock()
    fake_invoker.invoke = AsyncMock(return_value=MagicMock(success=False, output={}))
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(
        mcp_invoker=fake_invoker,
        recorder_repo=repo,  # type: ignore[arg-type]
        redis=None,
    )

    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://app.example.com",
    )
    row, browser_url = await mgr.start("ws_1", "usr_1", req)
    assert browser_url is None

    # Appending event without redis must not throw
    event = RecorderEvent(
        kind=RecorderEventKind.CLICK,
        timestamp=datetime.now(tz=UTC),
        selector="#submit-btn",
    )
    await mgr.append_event(row.id, "ws_1", event)
    assert len(repo.sessions[row.id].events) == 1


def test_events_to_steps_codegen() -> None:
    """Events recorded from browser codegen are properly mapped into test steps."""
    fake_invoker = MagicMock()
    mgr = RecorderSessionManager(fake_invoker, _FakeRecorderRepo())  # type: ignore[arg-type]

    now = datetime.now(tz=UTC).isoformat()
    raw_events = [
        {"kind": "navigate", "timestamp": now, "url": "https://app.example.com/login"},
        {
            "kind": "type",
            "timestamp": now,
            "selector": "input#username",
            "text": "tester@example.com",
        },
        {
            "kind": "type",
            "timestamp": now,
            "selector": "input#password",
            "text": "supersecret",
            "masked": True,
        },
        {"kind": "click", "timestamp": now, "selector": "button#login-btn"},
        {
            "kind": "assert",
            "timestamp": now,
            "assertion": {
                "expected": "Welcome message",
                "code": "expect(page.locator('.welcome')).toBeVisible()",
            },
        },
    ]

    req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Recorded Login Flow",
        priority="P1",
    )
    case_draft = mgr._convert_events_to_case(
        raw_events,
        start_url="https://app.example.com",
        session_id="rec_sess_1",
        request=req,
    )

    assert case_draft.name == "Recorded Login Flow"
    assert len(case_draft.steps) == 5

    assert "navigate" in case_draft.steps[0].code
    assert "https://app.example.com/login" in case_draft.steps[0].code

    assert "type" in case_draft.steps[1].code
    assert "tester@example.com" in case_draft.steps[1].code

    assert case_draft.steps[2].data.get("masked") is True
    assert "raw_value" not in case_draft.steps[2].data
    assert "{{password}}" in case_draft.steps[2].code

    assert "click" in case_draft.steps[3].code
    assert "button#login-btn" in case_draft.steps[3].code

    assert case_draft.steps[4].expected == "Welcome message"


def test_recorder_coalesces_intermediate_typing_and_focus_clicks() -> None:
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(mcp_invoker=MagicMock(), recorder_repo=repo)  # type: ignore[arg-type]

    now = datetime.now(tz=UTC)
    raw_events = [
        {"kind": "navigate", "url": "https://app.example.com/login", "timestamp": now},
        # Partial typing for username
        {
            "kind": "type",
            "selector": "input#email",
            "text": "test",
            "masked": False,
            "timestamp": now,
        },
        {
            "kind": "type",
            "selector": "input#email",
            "text": "tester@example.com",
            "masked": False,
            "timestamp": now,
        },
        # Focus click on password field immediately followed by typing
        {"kind": "click", "selector": "input#pass", "timestamp": now},
        # Partial typing for password
        {"kind": "type", "selector": "input#pass", "text": "sec", "masked": True, "timestamp": now},
        {
            "kind": "type",
            "selector": "input#pass",
            "text": "secret123",
            "masked": True,
            "timestamp": now,
        },
        {"kind": "click", "selector": "button#login-btn", "timestamp": now},
    ]

    req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Coalesced Login Flow",
        priority="P1",
    )
    case_draft = mgr._convert_events_to_case(
        raw_events,
        start_url="https://app.example.com",
        session_id="rec_sess_2",
        request=req,
    )

    # 4 steps: navigate, 1 coalesced username type, 1 coalesced password type (click removed), 1 button click
    assert len(case_draft.steps) == 4
    assert "tester@example.com" in case_draft.steps[1].code
    assert case_draft.steps[2].data.get("masked") is True
    assert "raw_value" not in case_draft.steps[2].data
    assert "button#login-btn" in case_draft.steps[3].code


@pytest.mark.asyncio
async def test_recorder_session_mcp_exceptions_tolerated() -> None:
    """Unexpected MCP runtime errors (spawn failures, connection resets) must be tolerated."""
    fake_invoker = MagicMock()
    fake_invoker.invoke = AsyncMock(side_effect=RuntimeError("MCP spawn/protocol failed"))
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(
        mcp_invoker=fake_invoker,
        recorder_repo=repo,  # type: ignore[arg-type]
        redis=None,
    )

    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://app.example.com",
    )
    # Start does not crash with 500 when advisory browser.start_recording fails
    row, browser_url = await mgr.start("ws_1", "usr_1", req)
    assert row.status == "active"
    assert browser_url is None

    # Finalize does not crash when advisory browser.stop_recording fails
    fin_req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Recorded Flow",
    )
    sess, draft = await mgr.finalize(row.id, "ws_1", "usr_1", fin_req)
    assert sess.id == row.id
    assert draft.name == "Recorded Flow"

    # Cancel does not crash when advisory browser.stop_recording fails
    cancelled_row = await mgr.cancel(row.id, "ws_1")
    assert cancelled_row.status == "cancelled"


def test_recorder_auto_prepends_start_url() -> None:
    """When captured events don't start with a navigation, Navigate to start_url is prepended."""
    fake_invoker = MagicMock()
    mgr = RecorderSessionManager(fake_invoker, _FakeRecorderRepo())  # type: ignore[arg-type]

    now = datetime.now(tz=UTC).isoformat()
    raw_events = [
        {"kind": "click", "timestamp": now, "selector": "#btn-login"},
    ]
    req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Auto Nav Test",
        priority="P2",
    )
    draft = mgr._convert_events_to_case(
        raw_events,
        start_url="https://www.saucedemo.com",
        session_id="rec_sess_auto",
        request=req,
    )
    assert len(draft.steps) == 2
    assert draft.steps[0].order == 1
    assert draft.steps[0].action == "Navigate to https://www.saucedemo.com"
    assert "browser_navigate" in draft.steps[0].code
    assert draft.steps[1].order == 2
    assert draft.steps[1].action == "Click #btn-login"


@pytest.mark.asyncio
async def test_recorder_custom_events_finalize() -> None:
    """When request.events is provided, finalize uses the user-edited events instead of session events."""
    fake_invoker = MagicMock()
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(fake_invoker, repo)  # type: ignore[arg-type]

    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://example.com",
    )
    row, _ = await mgr.start("ws_1", "usr_1", req)

    # Pretend session has 3 events
    now = datetime.now(tz=UTC).isoformat()
    row.events = [
        {"kind": "click", "timestamp": now, "selector": "#bad-click-1"},
        {"kind": "click", "timestamp": now, "selector": "#bad-click-2"},
        {"kind": "click", "timestamp": now, "selector": "#good-click"},
    ]

    # User filtered out the bad clicks in the UI
    user_edited_events = [
        {"kind": "click", "timestamp": now, "selector": "#good-click"},
    ]
    fin_req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Filtered Flow",
        events=user_edited_events,
    )
    sess, draft = await mgr.finalize(row.id, "ws_1", "usr_1", fin_req)
    assert sess.id == row.id
    # Should have step 1 (auto prepended navigate) + step 2 (good-click)
    assert len(draft.steps) == 2
    assert draft.steps[0].action == "Navigate to https://example.com"
    assert draft.steps[1].action == "Click #good-click"

"""Unit tests for the recorder session manager and codegen step conversion."""

from __future__ import annotations

import json
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
        self.mcp_provider = mcp_provider
        self.expires_at = datetime.now(tz=UTC) + timedelta(minutes=30)
        self.start_url = start_url
        self.browser_session_handle = "bsh_1"
        self.created_by_user_id = "usr_1"
        self.ws_room = f"recorder:{session_id}"

    @property
    def captured_events_json(self) -> list[dict[str, Any]]:
        return self.events


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
    assert case_draft.steps[2].data.get("encoded_value") == "c3VwZXJzZWNyZXQ="
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


@pytest.mark.asyncio
async def test_recorder_resume_session() -> None:
    """Resuming an active session finds the last captured URL and generates the browser browse URL."""
    fake_invoker = MagicMock()
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(fake_invoker, repo)  # type: ignore[arg-type]

    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://example.com",
    )
    row, _ = await mgr.start("ws_1", "usr_1", req)

    now = datetime.now(tz=UTC).isoformat()
    row.events = [
        {"kind": "navigate", "timestamp": now, "url": "https://example.com/login"},
        {
            "kind": "click",
            "timestamp": now,
            "selector": "#login-btn",
            "url": "https://example.com/dashboard",
        },
    ]

    from urllib.parse import quote

    sess, browser_url = await mgr.resume(row.id, "ws_1", "usr_1")
    assert sess.id == row.id
    assert quote("https://example.com/dashboard", safe="") in (browser_url or "")


@pytest.mark.asyncio
async def test_recorder_select_upload_assert_events_conversion() -> None:
    """Verifies that select, upload, and assert events are mapped to corresponding TestStepDrafts."""
    fake_invoker = MagicMock()
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(fake_invoker, repo)  # type: ignore[arg-type]

    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://example.com",
    )
    row, _ = await mgr.start("ws_1", "usr_1", req)

    now = datetime.now(tz=UTC).isoformat()
    events = [
        {
            "kind": "select",
            "timestamp": now,
            "selector": "select#country",
            "text": "ID",
            "assertion": {"label": "Indonesia", "value": "ID"},
        },
        {
            "kind": "upload",
            "timestamp": now,
            "selector": "input#avatar",
            "text": "avatar.png",
            "data": {"file_name": "avatar.png", "fixture_path": "fixtures/avatar.png"},
        },
        {
            "kind": "assert",
            "timestamp": now,
            "selector": ".toast-success",
            "text": "Profile updated",
            "assertion": {
                "type": "text",
                "expected": 'Alert shows "Profile updated"',
                "description": "Assert profile toast",
                "code": "() => true",
            },
        },
    ]

    fin_req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Smart Actions Flow",
        events=events,
    )
    sess, draft = await mgr.finalize(row.id, "ws_1", "usr_1", fin_req)
    assert sess.id == row.id
    # Steps: 0: nav, 1: select, 2: upload, 3: assert
    assert len(draft.steps) == 4
    # Select step
    assert draft.steps[1].action == "Select option 'Indonesia' in select#country"
    assert "browser_select_option" in draft.steps[1].code
    # Upload step
    assert draft.steps[2].action == "Upload file 'avatar.png' to input#avatar"
    assert "browser_upload_file" in draft.steps[2].code
    assert "fixtures/avatar.png" in draft.steps[2].code
    # Assert step
    assert draft.steps[3].action == "Assert profile toast"
    assert draft.steps[3].expected == 'Alert shows "Profile updated"'
    assert "browser_evaluate" in draft.steps[3].code


@pytest.mark.asyncio
async def test_recorder_filters_fakepath_typing_events() -> None:
    """Verifies that redundant fakepath typing events emitted by browser file inputs are filtered out."""
    fake_invoker = MagicMock()
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(fake_invoker, repo)  # type: ignore[arg-type]

    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://example.com",
    )
    row, _ = await mgr.start("ws_1", "usr_1", req)

    now = datetime.now(tz=UTC).isoformat()
    events = [
        # Redundant typing event with C:\fakepath
        {
            "kind": "type",
            "timestamp": now,
            "selector": "input#avatar",
            "text": "C:\\fakepath\\avatar.png",
        },
        # Legitimate upload event
        {
            "kind": "upload",
            "timestamp": now,
            "selector": "input#avatar",
            "text": "avatar.png",
            "data": {"file_name": "avatar.png", "fixture_path": "fixtures/avatar.png"},
        },
        # Trailing typing event from change/input on same input
        {
            "kind": "type",
            "timestamp": now,
            "selector": "input#avatar",
            "text": "avatar.png",
        },
    ]

    fin_req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Upload Flow",
        events=events,
    )
    _, draft = await mgr.finalize(row.id, "ws_1", "usr_1", fin_req)
    # Only nav step (0) and upload step (1) should remain — all fakepath/redundant typing dropped
    assert len(draft.steps) == 2
    assert draft.steps[1].action == "Upload file 'avatar.png' to input#avatar"
    assert "browser_upload_file" in draft.steps[1].code


@pytest.mark.asyncio
async def test_recorder_multi_file_upload_events_conversion() -> None:
    fake_invoker = MagicMock()
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(fake_invoker, repo)  # type: ignore[arg-type]

    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://example.com",
    )
    row, _ = await mgr.start("ws_1", "usr_1", req)

    now = datetime.now(tz=UTC).isoformat()
    events = [
        {
            "kind": "upload",
            "timestamp": now,
            "selector": "input#files",
            "text": "report.pdf, chart.png",
            "data": {
                "file_name": "report.pdf",
                "file_names": ["report.pdf", "chart.png"],
                "fixture_paths": ["fixtures/report.pdf", "fixtures/chart.png"],
            },
        },
    ]

    fin_req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Multi Upload Flow",
        events=events,
    )
    _, draft = await mgr.finalize(row.id, "ws_1", "usr_1", fin_req)
    assert len(draft.steps) == 2
    assert "Upload 2 files" in draft.steps[1].action
    assert "report.pdf" in draft.steps[1].action
    assert "chart.png" in draft.steps[1].action
    assert "browser_upload_file" in draft.steps[1].code
    assert "fixtures/report.pdf" in draft.steps[1].code
    assert "fixtures/chart.png" in draft.steps[1].code


def test_recorder_coalesces_navigate_immediately_after_click() -> None:
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(MagicMock(), repo)  # type: ignore[arg-type]

    now = datetime.now(tz=UTC)
    raw_events = [
        {"kind": "navigate", "url": "https://app.example.com/dashboard", "timestamp": now},
        {"kind": "click", "selector": "a[href='/settings']", "timestamp": now},
        # Redundant navigate step triggered by the anchor click
        {"kind": "navigate", "url": "https://app.example.com/settings", "timestamp": now},
        {"kind": "click", "selector": "button#save", "timestamp": now},
    ]

    req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Navigation Flow",
    )
    case_draft = mgr._convert_events_to_case(
        raw_events,
        start_url="https://app.example.com/dashboard",
        session_id="rec_sess_nav",
        request=req,
    )

    # The redundant navigate right after click should be coalesced away
    assert len(case_draft.steps) == 3
    assert "Navigate to https://app.example.com/dashboard" in case_draft.steps[0].action
    assert "Click a[href='/settings']" in case_draft.steps[1].action
    assert "Click button#save" in case_draft.steps[2].action


def test_recorder_handles_select_and_frame_selector() -> None:
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(MagicMock(), repo)  # type: ignore[arg-type]

    now = datetime.now(tz=UTC)
    raw_events = [
        {"kind": "navigate", "url": "https://app.example.com/frames", "timestamp": now},
        {
            "kind": "click",
            "selector": "button#submit",
            "frame_selector": "iframe#login-frame",
            "timestamp": now,
        },
        {
            "kind": "select",
            "selector": "select#country",
            "text": "ID",
            "frame_selector": "iframe#login-frame",
            "assertion": {"label": "Indonesia", "value": "ID", "values": ["ID"]},
            "data": {"values": ["ID"]},
            "timestamp": now,
        },
    ]

    req = RecorderFinalizeRequest(
        target_suite_id="ste_1",
        name="Iframe Flow",
    )
    case_draft = mgr._convert_events_to_case(
        raw_events,
        start_url="https://app.example.com/frames",
        session_id="rec_sess_iframe",
        request=req,
    )

    assert len(case_draft.steps) == 3
    assert case_draft.steps[1].data.get("frame_selector") == "iframe#login-frame"
    assert "in frame iframe#login-frame" in case_draft.steps[1].action

    step2_code = json.loads(case_draft.steps[2].code)
    assert step2_code["tool"] == "browser_select_option"
    assert step2_code["arguments"]["target"] == "select#country"
    assert step2_code["arguments"]["values"] == ["ID"]
    assert step2_code["arguments"]["frame_selector"] == "iframe#login-frame"
    assert "in frame iframe#login-frame" in case_draft.steps[2].action


def test_convert_events_drops_navigate_after_click() -> None:
    """Verify NAVIGATE event following a CLICK is dropped as redundant."""
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(MagicMock(), repo)  # type: ignore[arg-type]
    now = datetime.now(tz=UTC)
    raw_events = [
        {"kind": "navigate", "url": "https://example.com/login", "timestamp": now},
        {"kind": "click", "selector": "#login-btn", "timestamp": now},
        {"kind": "navigate", "url": "https://example.com/dashboard", "timestamp": now},
    ]
    request = RecorderFinalizeRequest(name="Login Flow")
    draft = mgr._convert_events_to_case(raw_events, "https://example.com/login", "rec_123", request)
    assert len(draft.steps) == 2
    assert "Navigate to https://example.com/login" in draft.steps[0].action
    assert "Click #login-btn" in draft.steps[1].action


def test_assert_step_with_frame_selector() -> None:
    """Verify ASSERT event with frame_selector produces frame-scoped action and arguments."""
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(MagicMock(), repo)  # type: ignore[arg-type]
    event = RecorderEvent(
        kind=RecorderEventKind.ASSERT,
        selector="#success-msg",
        text="Payment complete",
        frame_selector="iframe#checkout-frame",
        timestamp=datetime.now(tz=UTC),
        assertion={"expected": "Text matches", "type": "text"},
    )
    step = mgr._assert_step(event, order=1)
    assert "in frame iframe#checkout-frame" in step.action
    assert step.data["frame_selector"] == "iframe#checkout-frame"
    code_dict = json.loads(step.code)
    assert code_dict["arguments"]["frame_selector"] == "iframe#checkout-frame"
    assert code_dict["arguments"]["selector"] == "#success-msg"
    assert code_dict["arguments"]["text"] == "Payment complete"


@pytest.mark.asyncio
async def test_resume_reactivates_cancelled_session() -> None:
    """Verify that a cancelled session can be resumed and re-activated to active."""
    fake_invoker = MagicMock()
    fake_invoker.invoke = AsyncMock(return_value=MagicMock(success=True, output={}))
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(fake_invoker, repo)  # type: ignore[arg-type]
    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://app.example.com",
    )
    session, _ = await mgr.start("ws_1", "usr_1", req)
    await repo.update_status(session.id, "cancelled", workspace_id="ws_1")
    resumed, browser_url = await mgr.resume(session.id, workspace_id="ws_1")
    assert resumed.status == "active"
    assert "https%3A%2F%2Fapp.example.com" in (browser_url or "")


@pytest.mark.asyncio
async def test_resume_keeps_main_page_url_ignoring_subframe_events() -> None:
    """Verify that resume re-opens main page URL even if later events occurred in nested iframes."""
    fake_invoker = MagicMock()
    fake_invoker.invoke = AsyncMock(return_value=MagicMock(success=True, output={}))
    repo = _FakeRecorderRepo()
    mgr = RecorderSessionManager(fake_invoker, repo)  # type: ignore[arg-type]
    req = RecorderSessionStartRequest(
        project_id="prj_1",
        start_url="https://app.example.com/frames",
    )
    session, _ = await mgr.start("ws_1", "usr_1", req)

    # Simulate events: first in main page, then in nested iframe with subframe URL
    await repo.append_event(
        session.id,
        {"kind": "navigate", "url": "https://app.example.com/frames"},
        workspace_id="ws_1",
    )
    await repo.append_event(
        session.id,
        {
            "kind": "click",
            "url": "https://app.example.com/nested-frame-src",
            "selector": "button#child-btn",
            "frame_selector": "iframe#outer >>> iframe#inner",
        },
        workspace_id="ws_1",
    )
    await repo.append_event(
        session.id,
        {
            "kind": "assert",
            "url": "https://app.example.com/nested-frame-src",
            "selector": "span#status",
            "frame_selector": "iframe#outer >>> iframe#inner",
            "text": "Done",
        },
        workspace_id="ws_1",
    )

    resumed, browser_url = await mgr.resume(session.id, workspace_id="ws_1")
    assert resumed.status == "active"
    # Must resume at main page URL (/frames), NOT the subframe URL (/nested-frame-src)
    assert "nested-frame-src" not in (browser_url or "")
    assert "https%3A%2F%2Fapp.example.com%2Fframes" in (browser_url or "")

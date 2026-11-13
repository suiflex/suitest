from __future__ import annotations

from unittest.mock import MagicMock, patch

from suitest_lifecycle.interactive_browser import InteractiveSessionManager
from suitest_lifecycle.mcp_server import _BROWSER_CLOSE_SCHEMA


def test_close_session_with_auto_publish(tmp_path):
    manager = InteractiveSessionManager()
    session_id = "test_sess_publish"
    mock_sess = MagicMock()
    mock_sess.session_id = session_id
    mock_sess.created_at = 1700000000.0
    mock_sess.action_history = [
        MagicMock(
            to_json=lambda: {
                "order": 1,
                "action": "navigate",
                "target": "http://app.test",
                "value": "",
            }
        ),
        MagicMock(
            to_json=lambda: {
                "order": 2,
                "action": "click",
                "target": "#submit",
                "value": "",
            }
        ),
        MagicMock(
            to_json=lambda: {
                "order": 3,
                "action": "type",
                "target": "#username",
                "value": "admin",
            }
        ),
        MagicMock(
            to_json=lambda: {
                "order": 4,
                "action": "select",
                "target": "#role",
                "value": "qa",
            }
        ),
    ]
    manager._sessions[session_id] = mock_sess

    with patch("suitest_lifecycle.tools.create_test_case") as mock_create:
        mock_create.return_value = {
            "success": True,
            "summary": "created test case TC-8888",
            "data": {"public_id": "TC-8888", "id": "case_uuid"},
        }
        actions, case_file, meta = manager.close_session(
            session_id=session_id,
            auto_publish=True,
            case_name="E2E Auto Flow",
            output_dir=str(tmp_path),
        )

    assert len(actions) == 4
    assert case_file == ""
    assert meta.get("case_id") == "TC-8888"
    assert "/cases/TC-8888" in meta.get("dashboard_url", "")
    mock_create.assert_called_once()
    assert mock_create.call_args[1]["target_url"] == "http://app.test"
    steps = mock_create.call_args[1]["steps"]
    assert len(steps) == 4
    assert steps[0]["code"]["tool"] == "browser_navigate"
    assert steps[1]["code"]["tool"] == "browser_click"
    assert steps[2]["code"]["tool"] == "browser_type"
    assert steps[3]["code"]["tool"] == "browser_select_option"


def test_format_steps_uses_secret_reference_for_sensitive_inputs():
    actions = [
        {"order": 1, "action": "type", "target": "#user-email", "value": "test@example.com"},
        {"order": 2, "action": "type", "target": "input#pass", "value": "SuperSecretPass123!"},
        {"order": 3, "action": "type", "target": "[name='auth_token']", "value": "tok_xyz_secret"},
        {"order": 4, "action": "type", "target": "input#cvv", "value": "999"},
        {"order": 5, "action": "type", "target": "#pin-code", "value": "1234"},
    ]
    steps = InteractiveSessionManager._format_steps(actions)
    assert len(steps) == 5
    assert steps[0]["code"]["arguments"]["text"] == "test@example.com"
    assert steps[1]["code"]["arguments"]["text"] == "{{password}}"
    assert steps[2]["code"]["arguments"]["text"] == "{{secret}}"
    assert steps[3]["code"]["arguments"]["text"] == "{{secret}}"
    assert steps[4]["code"]["arguments"]["text"] == "{{secret}}"


def test_close_session_with_auto_publish_failure(tmp_path):
    from suitest_lifecycle.interactive_browser import _GLOBAL_MANAGER, suitest_browser_close

    manager = InteractiveSessionManager()
    session_id = "test_sess_publish_fail"
    mock_sess = MagicMock()
    mock_sess.session_id = session_id
    mock_sess.created_at = 1700000000.0
    mock_sess.action_history = [
        MagicMock(
            to_json=lambda: {
                "order": 1,
                "action": "navigate",
                "target": "http://app.test/login",
                "value": "",
            }
        ),
    ]
    manager._sessions[session_id] = mock_sess

    with patch("suitest_lifecycle.tools.create_test_case") as mock_create:
        mock_create.return_value = {
            "success": False,
            "summary": "TCM connection failed",
            "errors": ["network timeout"],
        }
        _actions, _case_file, meta = manager.close_session(
            session_id=session_id,
            auto_publish=True,
            case_name="Failed Publish Test",
            output_dir=str(tmp_path),
        )

    assert meta.get("auto_publish") is False
    assert "case_id" not in meta
    assert "dashboard_url" not in meta
    assert meta.get("publish_error") == "TCM connection failed"
    assert meta.get("errors") == ["network timeout"]

    # Test through suitest_browser_close tool envelope
    _GLOBAL_MANAGER._sessions[session_id] = mock_sess
    with patch("suitest_lifecycle.tools.create_test_case") as mock_create:
        mock_create.return_value = {
            "success": False,
            "summary": "TCM connection failed",
            "errors": ["network timeout"],
        }
        res = suitest_browser_close(session_id=session_id, auto_publish=True)

    assert res["success"] is False
    assert "auto-publish failed" in res["summary"]
    assert "case_id" not in res["data"]
    assert "dashboard_url" not in res["data"]


def test_browser_close_schema_declares_auto_publish():
    props = _BROWSER_CLOSE_SCHEMA.get("properties", {})
    assert "auto_publish" in props
    assert "case_name" in props


def test_close_non_existent_session_fails():
    from suitest_lifecycle.interactive_browser import suitest_browser_close

    res = suitest_browser_close(session_id="non_existent_session_xyz")
    assert res["success"] is False
    assert "not found or has expired" in res["summary"]

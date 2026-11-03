from __future__ import annotations

from unittest.mock import patch

from suitest_lifecycle.interactive_browser import suitest_browser_open
from suitest_lifecycle.mcp_server import _BROWSER_OPEN_SCHEMA


def test_browser_open_returns_clarification_when_credentials_required_and_missing():
    res = suitest_browser_open(require_auth=True, credentials=None)
    assert res["success"] is False
    assert res.get("status") == "NEEDS_CLARIFICATION"
    assert "credentials required" in res["summary"].lower()


def test_browser_open_succeeds_when_auth_not_required():
    with patch(
        "suitest_lifecycle.interactive_browser._GLOBAL_MANAGER.open_session",
        return_value="sess_mock123",
    ):
        res = suitest_browser_open(headless=True)
        assert res["success"] is True
        assert res["data"]["session_id"] == "sess_mock123"


def test_browser_open_schema_declares_auth_params():
    props = _BROWSER_OPEN_SCHEMA.get("properties", {})
    assert "require_auth" in props
    assert "credentials" in props

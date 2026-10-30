from __future__ import annotations

from unittest.mock import MagicMock

from suitest_lifecycle.tools import _resolve_suite_and_project


def test_resolve_suite_and_project_auto_creates_when_empty():
    mock_client = MagicMock()
    mock_client.resolve_project.return_value = {"id": "proj_123", "slug": "example-com"}
    mock_client.list_suites.return_value = []
    mock_client.create_suite.return_value = {"id": "suite_abc", "name": "General Discovered Suite"}

    p_id, s_id = _resolve_suite_and_project(
        mock_client,
        project_id="",
        suite_id="",
        target_url="http://example.com/login",
    )

    assert p_id == "proj_123"
    assert s_id == "suite_abc"
    mock_client.resolve_project.assert_called_once_with(
        project_slug="example-com",
        project_name="example.com",
    )
    mock_client.list_suites.assert_called_once_with(project_id="proj_123")
    mock_client.create_suite.assert_called_once_with(
        project_id="proj_123",
        name="General Discovered Suite",
    )


def test_resolve_suite_and_project_guards_against_empty_project_id():
    mock_client = MagicMock()
    mock_client.resolve_project.return_value = {}

    p_id, s_id = _resolve_suite_and_project(
        mock_client,
        project_id="",
        suite_id="",
        target_url="",
    )

    assert p_id == ""
    assert s_id == ""
    # Must NOT call list_suites with empty project_id (avoids 422 Unprocessable Entity)
    mock_client.list_suites.assert_not_called()


def test_create_test_case_with_auto_resolved_suite():
    from unittest.mock import patch

    from suitest_lifecycle.tools import create_test_case

    mock_client = MagicMock()
    mock_client.resolve_project.return_value = {"id": "proj_auto", "slug": "auto"}
    mock_client.list_suites.return_value = [{"id": "suite_auto_1"}]
    mock_client.create_case.return_value = {
        "id": "case_1",
        "public_id": "TC-9001",
        "name": "Auto Case",
    }

    with (
        patch.dict(
            "os.environ", {"SUITEST_API_URL": "http://mock:8000", "SUITEST_API_KEY": "sk_mock"}
        ),
        patch("suitest_lifecycle.http_client.SuitestClient") as mock_cls,
    ):
        mock_cls.return_value.__enter__.return_value = mock_client
        res = create_test_case(name="Auto Case", suite_id="", target_url="http://test.local")

    assert res["success"] is True
    assert "TC-9001" in res["summary"]
    mock_client.create_case.assert_called_once()
    assert mock_client.create_case.call_args[0][0]["suiteId"] == "suite_auto_1"


def test_create_case_schema_marks_suite_id_optional():
    from suitest_lifecycle.mcp_server import _CREATE_CASE_SCHEMA

    assert "suite_id" not in _CREATE_CASE_SCHEMA.get("required", [])
    assert "name" in _CREATE_CASE_SCHEMA.get("required", [])
    assert "target_url" in _CREATE_CASE_SCHEMA.get("properties", {})
    assert "project_id" in _CREATE_CASE_SCHEMA.get("properties", {})

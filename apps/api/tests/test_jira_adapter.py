"""Tests for :class:`JiraAdapter` (M1d-12).

Every test injects an ``AsyncMock`` for the :class:`JiraMcpClient` Protocol so
the adapter is exercised end-to-end without spawning the real ``jirac-mcp``
binary or hitting Jira. ``Integration`` rows are built directly (no DB) — the
``secrets_encrypted`` column type already decrypts on read, so tests can pass a
JSON string verbatim and the adapter's identity-crypto seam keeps the shape.

Coverage matrix (per ``docs/superpowers/plans/2026-05-30-plan-05b-m1d-manual-tcm-writes.md``
§Task M1d-12):

* ``test_connection`` happy path → ``ConnectionTestResult(ok=True, …)``.
* ``test_connection`` auth fail → ``ok=False`` with ``"JIRA_AUTH"`` prefix.
* ``create_external_issue`` → ``jira_issue_create`` with severity-mapped priority.
* ``update_external_issue`` → ``jira_issue_update`` + post-create view round-trip.
* ``transition_status`` → resolves transition id via list, then transitions.
* Status map default + workspace override.
* Severity → priority mapping for all four levels.
* :class:`McpError` 401 → :class:`AdapterAuthError`.
* :class:`McpError` 429 → :class:`AdapterRateLimitError`.
* :class:`McpToolTimeout` → :class:`AdapterTimeoutError`.
* Adapter passes the :class:`IssueTrackerAdapter` Protocol contract.
* :class:`AdapterAuthError` raised for missing required env fields.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from suitest_api.integrations.base import (
    AdapterAuthError,
    AdapterRateLimitError,
    AdapterRemoteError,
    AdapterTimeoutError,
    ConnectionTestResult,
    ExternalIssue,
    ExternalIssueInput,
    IssueTrackerAdapter,
)
from suitest_api.integrations.contract import run_adapter_contract
from suitest_api.integrations.jira_adapter import (
    JiraAdapter,
    _IdentityCrypto,
    _pick_transition_id,
)
from suitest_db.models.integration import Integration
from suitest_mcp.errors import McpError, McpToolFailed, McpToolTimeout
from suitest_shared.domain.enums import DefectStatus, IntegrationKind, Severity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _secrets_json(
    *,
    url: str = "https://acme.atlassian.net",
    email: str = "ops@acme.test",
    token: str = "tok-123",
    auth_type: str = "cloud_api_token",
    deployment: str = "cloud",
) -> str:
    return json.dumps(
        {
            "url": url,
            "email": email,
            "token": token,
            "auth_type": auth_type,
            "deployment": deployment,
        }
    )


def _integration(
    *,
    secrets: str | None = None,
    config: dict[str, Any] | None = None,
) -> Integration:
    """Build an Integration row in memory (no DB) — secrets pre-decrypted."""
    row = Integration(
        id="int_jira_1",
        workspace_id="ws_test",
        kind=IntegrationKind.JIRA,
        name="acme jira",
        config=config if config is not None else {"project_key": "ACME"},
        secrets_encrypted=secrets if secrets is not None else _secrets_json(),
        status="active",
    )
    return row


def _adapter(
    *,
    mcp: AsyncMock | None = None,
    integration: Integration | None = None,
) -> JiraAdapter:
    """Build a :class:`JiraAdapter` with a mock MCP client."""
    return JiraAdapter(
        integration=integration or _integration(),
        mcp_client=mcp or AsyncMock(),
        crypto=_IdentityCrypto(),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_init_decrypts_secrets_and_builds_env_overrides() -> None:
    adapter = _adapter()

    assert adapter._env_overrides == {
        "JIRA_URL": "https://acme.atlassian.net",
        "JIRA_EMAIL": "ops@acme.test",
        "JIRA_TOKEN": "tok-123",
        "JIRA_AUTH_TYPE": "cloud_api_token",
        "JIRA_DEPLOYMENT": "cloud",
    }
    assert adapter.kind is IntegrationKind.JIRA


def test_init_missing_secrets_raises_adapter_auth_error() -> None:
    row = _integration(secrets=None)
    # ``secrets_encrypted=None`` is what an Integration row looks like when the
    # user hasn't completed the connect dialog. The adapter must refuse to
    # construct rather than crashing at first invoke().
    row.secrets_encrypted = None

    with pytest.raises(AdapterAuthError, match="no secrets configured"):
        JiraAdapter(integration=row, mcp_client=AsyncMock(), crypto=_IdentityCrypto())


def test_init_missing_required_field_raises_adapter_auth_error() -> None:
    bad = json.dumps({"url": "https://x.example", "email": "ops@x.test"})  # no token
    with pytest.raises(AdapterAuthError, match="missing required field"):
        JiraAdapter(
            integration=_integration(secrets=bad),
            mcp_client=AsyncMock(),
            crypto=_IdentityCrypto(),
        )


def test_init_invalid_auth_type_raises_adapter_auth_error() -> None:
    bad = _secrets_json(auth_type="oauth_3lo")
    with pytest.raises(AdapterAuthError, match="auth_type"):
        JiraAdapter(
            integration=_integration(secrets=bad),
            mcp_client=AsyncMock(),
            crypto=_IdentityCrypto(),
        )


def test_init_garbage_secrets_json_raises_adapter_auth_error() -> None:
    with pytest.raises(AdapterAuthError, match="not valid JSON"):
        JiraAdapter(
            integration=_integration(secrets="not-json"),
            mcp_client=AsyncMock(),
            crypto=_IdentityCrypto(),
        )


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_connection_happy_path_invokes_myself_endpoint() -> None:
    mcp = AsyncMock()
    mcp.invoke.return_value = {"result": {"accountId": "u-7", "displayName": "Maya Q"}}
    adapter = _adapter(mcp=mcp)

    result = await adapter.test_connection()

    assert result == ConnectionTestResult(ok=True, account_id="u-7", display_name="Maya Q")
    mcp.invoke.assert_awaited_once()
    kwargs = mcp.invoke.await_args.kwargs
    assert kwargs["provider"] == "jirac-mcp"
    assert kwargs["tool"] == "jira_api_request"
    assert kwargs["arguments"] == {"method": "GET", "path": "/rest/api/3/myself"}
    # Env overrides must carry the per-call credentials.
    assert kwargs["env_overrides"]["JIRA_URL"] == "https://acme.atlassian.net"
    assert kwargs["env_overrides"]["JIRA_TOKEN"] == "tok-123"


@pytest.mark.asyncio
async def test_test_connection_auth_failure_returns_ok_false() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = McpError("HTTP 401 Unauthorized")
    adapter = _adapter(mcp=mcp)

    result = await adapter.test_connection()

    assert result.ok is False
    assert result.error is not None and result.error.startswith("JIRA_AUTH")
    assert result.account_id is None and result.display_name is None


@pytest.mark.asyncio
async def test_test_connection_remote_error_does_not_raise() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = McpError("500 Internal Server Error")
    adapter = _adapter(mcp=mcp)

    result = await adapter.test_connection()
    assert result.ok is False
    assert result.error is not None and result.error.startswith("JIRA_REMOTE")


# ---------------------------------------------------------------------------
# create_external_issue
# ---------------------------------------------------------------------------


def _input_body(severity: Severity = Severity.HIGH) -> ExternalIssueInput:
    return ExternalIssueInput(
        defect_id="defc_1",
        title="Crash on save",
        description="Stack trace included",
        severity=severity,
        labels=["regression", "auto"],
        run_id="run_1",
        test_case_public_id="TC-99",
    )


@pytest.mark.asyncio
async def test_create_external_issue_calls_jira_issue_create_with_priority() -> None:
    mcp = AsyncMock()
    mcp.invoke.return_value = {
        "result": {
            "id": "10001",
            "key": "ACME-42",
            "url": "https://acme.atlassian.net/browse/ACME-42",
            "fields": {"status": {"name": "To Do"}},
        }
    }
    adapter = _adapter(mcp=mcp)

    issue = await adapter.create_external_issue(_input_body(Severity.CRITICAL))

    assert issue.external_key == "ACME-42"
    assert issue.external_id == "10001"
    assert issue.external_url == "https://acme.atlassian.net/browse/ACME-42"
    assert issue.external_status == "To Do"
    kwargs = mcp.invoke.await_args.kwargs
    assert kwargs["tool"] == "jira_issue_create"
    args = kwargs["arguments"]
    assert args["project_key"] == "ACME"
    assert args["issue_type"] == "Bug"
    assert args["summary"] == "Crash on save"
    assert args["description"] == "Stack trace included"
    assert args["priority"] == "P1"  # CRITICAL → P1
    assert args["labels"] == ["regression", "auto"]


@pytest.mark.asyncio
async def test_create_external_issue_without_project_key_raises_remote_error() -> None:
    row = _integration(config={})  # no project_key configured
    adapter = JiraAdapter(integration=row, mcp_client=AsyncMock(), crypto=_IdentityCrypto())

    with pytest.raises(AdapterRemoteError, match="project_key"):
        await adapter.create_external_issue(_input_body())


@pytest.mark.asyncio
async def test_create_external_issue_falls_back_to_browse_url_when_omitted() -> None:
    mcp = AsyncMock()
    mcp.invoke.return_value = {
        "result": {"id": "1", "key": "ACME-1", "fields": {"status": "To Do"}}
    }
    adapter = _adapter(mcp=mcp)

    issue = await adapter.create_external_issue(_input_body())
    assert issue.external_url == "https://acme.atlassian.net/browse/ACME-1"


# ---------------------------------------------------------------------------
# update_external_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_external_issue_calls_update_then_view_round_trip() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = [
        {"result": {"key": "ACME-42"}},  # jira_issue_update
        {  # jira_issue_view
            "result": {
                "id": "10001",
                "key": "ACME-42",
                "fields": {"status": {"name": "In Progress"}},
            }
        },
    ]
    adapter = _adapter(mcp=mcp)

    issue = await adapter.update_external_issue("ACME-42", _input_body(Severity.MEDIUM))

    assert issue.external_key == "ACME-42"
    assert issue.external_status == "In Progress"
    assert mcp.invoke.await_count == 2
    update_call = mcp.invoke.await_args_list[0].kwargs
    view_call = mcp.invoke.await_args_list[1].kwargs
    assert update_call["tool"] == "jira_issue_update"
    assert update_call["arguments"]["key"] == "ACME-42"
    assert update_call["arguments"]["priority"] == "P3"  # MEDIUM → P3
    assert view_call["tool"] == "jira_issue_view"
    assert view_call["arguments"] == {"key": "ACME-42"}


# ---------------------------------------------------------------------------
# transition_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_status_lists_transitions_then_calls_transition_by_id() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = [
        {  # jira_issue_transitions_list
            "result": {
                "transitions": [
                    {"id": "11", "to": {"name": "In Progress"}},
                    {"id": "21", "to": {"name": "Done"}},
                ]
            }
        },
        {"result": {}},  # jira_issue_transition
    ]
    adapter = _adapter(mcp=mcp)

    await adapter.transition_status("ACME-42", DefectStatus.IN_PROGRESS)

    list_call = mcp.invoke.await_args_list[0].kwargs
    transition_call = mcp.invoke.await_args_list[1].kwargs
    assert list_call["tool"] == "jira_issue_transitions_list"
    assert list_call["arguments"] == {"key": "ACME-42"}
    assert transition_call["tool"] == "jira_issue_transition"
    assert transition_call["arguments"] == {"key": "ACME-42", "transition": "11"}


@pytest.mark.asyncio
async def test_transition_status_missing_transition_raises_remote_error() -> None:
    mcp = AsyncMock()
    mcp.invoke.return_value = {"result": {"transitions": []}}
    adapter = _adapter(mcp=mcp)

    with pytest.raises(AdapterRemoteError, match="no transition"):
        await adapter.transition_status("ACME-42", DefectStatus.IN_PROGRESS)


def test_pick_transition_id_case_insensitive() -> None:
    listing: dict[str, object] = {
        "result": {
            "transitions": [
                {"id": "11", "to": {"name": "in PROGRESS"}},
                {"id": "21", "to": {"name": "Done"}},
            ]
        }
    }
    assert _pick_transition_id(listing, "In Progress") == "11"
    assert _pick_transition_id(listing, "DONE") == "21"
    assert _pick_transition_id(listing, "Closed") is None


# ---------------------------------------------------------------------------
# Status map
# ---------------------------------------------------------------------------


def test_map_external_status_to_defect_status_uses_defaults() -> None:
    adapter = _adapter()
    assert adapter.map_external_status_to_defect_status("Done") is DefectStatus.RESOLVED
    assert adapter.map_external_status_to_defect_status("in progress") is DefectStatus.IN_PROGRESS
    assert adapter.map_external_status_to_defect_status("To Do") is DefectStatus.OPEN
    assert adapter.map_external_status_to_defect_status("Open") is DefectStatus.OPEN
    assert adapter.map_external_status_to_defect_status("Won't Do") is DefectStatus.WONT_FIX
    assert adapter.map_external_status_to_defect_status("Unknown") is None


def test_map_external_status_to_defect_status_respects_workspace_override() -> None:
    row = _integration(
        config={
            "project_key": "ACME",
            "status_map": {"RESOLVED": "Verified"},
        }
    )
    adapter = JiraAdapter(integration=row, mcp_client=AsyncMock(), crypto=_IdentityCrypto())

    # Workspace renamed "Resolved" → "Verified" in their workflow.
    assert adapter.map_external_status_to_defect_status("Verified") is DefectStatus.RESOLVED
    # Canonical default still recognised on the reverse direction via alias.
    assert adapter.map_external_status_to_defect_status("Done") is DefectStatus.RESOLVED


def test_status_map_ignores_unknown_defect_status_in_overrides() -> None:
    row = _integration(config={"project_key": "ACME", "status_map": {"NOT_A_STATUS": "Foo"}})
    # Constructor must not raise on bogus override keys — silently dropped.
    adapter = JiraAdapter(integration=row, mcp_client=AsyncMock(), crypto=_IdentityCrypto())
    assert adapter.map_external_status_to_defect_status("Foo") is None


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "severity,priority",
    [
        (Severity.LOW, "P4"),
        (Severity.MEDIUM, "P3"),
        (Severity.HIGH, "P2"),
        (Severity.CRITICAL, "P1"),
    ],
)
async def test_severity_maps_to_priority_field_python_side(
    severity: Severity, priority: str
) -> None:
    mcp = AsyncMock()
    mcp.invoke.return_value = {
        "result": {
            "id": "1",
            "key": "ACME-1",
            "fields": {"status": {"name": "To Do"}},
        }
    }
    adapter = _adapter(mcp=mcp)
    await adapter.create_external_issue(_input_body(severity))
    assert mcp.invoke.await_args.kwargs["arguments"]["priority"] == priority


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_401_translates_to_adapter_auth_error() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = McpToolFailed("HTTP 401 Unauthorized")
    adapter = _adapter(mcp=mcp)

    with pytest.raises(AdapterAuthError):
        await adapter.create_external_issue(_input_body())


@pytest.mark.asyncio
async def test_mcp_403_translates_to_adapter_auth_error() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = McpError("forbidden — admin scope required")
    adapter = _adapter(mcp=mcp)

    with pytest.raises(AdapterAuthError):
        await adapter.create_external_issue(_input_body())


@pytest.mark.asyncio
async def test_mcp_429_translates_to_adapter_rate_limit_error() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = McpError("HTTP 429 — Retry-After 30")
    adapter = _adapter(mcp=mcp)

    with pytest.raises(AdapterRateLimitError):
        await adapter.create_external_issue(_input_body())


@pytest.mark.asyncio
async def test_mcp_timeout_translates_to_adapter_timeout_error() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = McpToolTimeout("tool jira_issue_create timed out after 30s")
    adapter = _adapter(mcp=mcp)

    with pytest.raises(AdapterTimeoutError):
        await adapter.create_external_issue(_input_body())


@pytest.mark.asyncio
async def test_mcp_remote_failure_translates_to_adapter_remote_error() -> None:
    mcp = AsyncMock()
    mcp.invoke.side_effect = McpToolFailed("HTTP 502 Bad Gateway")
    adapter = _adapter(mcp=mcp)

    with pytest.raises(AdapterRemoteError):
        await adapter.create_external_issue(_input_body())


# ---------------------------------------------------------------------------
# Protocol contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_adapter_passes_issue_tracker_protocol_contract() -> None:
    """:class:`JiraAdapter` satisfies the :class:`IssueTrackerAdapter` Protocol."""
    mcp = AsyncMock()
    # The contract runs: test_connection → create → update → transition →
    # map_external_status. Each call must round-trip — wire the mock to the
    # full happy-path sequence.
    create_response: dict[str, object] = {
        "result": {
            "id": "10001",
            "key": "ACME-1",
            "url": "https://acme.atlassian.net/browse/ACME-1",
            "fields": {"status": {"name": "To Do"}},
        }
    }
    update_view_response: dict[str, object] = {
        "result": {
            "id": "10001",
            "key": "ACME-1",
            "fields": {"status": {"name": "In Progress"}},
        }
    }
    transitions_response: dict[str, object] = {
        "result": {
            "transitions": [
                {"id": "11", "to": {"name": "In Progress"}},
            ]
        }
    }

    async def fake_invoke(
        *, provider: str, tool: str, arguments: dict[str, object], env_overrides: dict[str, str]
    ) -> dict[str, object]:
        if tool == "jira_api_request":
            return {"result": {"accountId": "u-1", "displayName": "Bot"}}
        if tool == "jira_issue_create":
            return create_response
        if tool == "jira_issue_update":
            return {"result": {}}
        if tool == "jira_issue_view":
            return update_view_response
        if tool == "jira_issue_transitions_list":
            return transitions_response
        if tool == "jira_issue_transition":
            return {"result": {}}
        raise AssertionError(f"unexpected tool {tool}")

    mcp.invoke.side_effect = fake_invoke
    adapter = _adapter(mcp=mcp)

    assert isinstance(adapter, IssueTrackerAdapter)
    await run_adapter_contract(adapter)


# ---------------------------------------------------------------------------
# Lifespan registration (M1d-12: factory wired on app.state.adapter_factories)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_registers_jira_adapter_factory() -> None:
    from asgi_lifespan import LifespanManager
    from suitest_api.main import create_app

    app = create_app()
    async with LifespanManager(app):
        factories = app.state.adapter_factories
        assert IntegrationKind.JIRA in factories
        factory = factories[IntegrationKind.JIRA]
        # Smoke: factory is callable with (integration, mcp_client, crypto)
        # and produces a JiraAdapter instance.
        built = factory(
            integration=_integration(),
            mcp_client=AsyncMock(),
            crypto=_IdentityCrypto(),
        )
        assert isinstance(built, JiraAdapter)
        assert built.kind is IntegrationKind.JIRA


@pytest.mark.asyncio
async def test_jira_adapter_returns_external_issue_dto_type() -> None:
    """Defensive: the create path must return a Pydantic-validated DTO."""
    mcp = AsyncMock()
    mcp.invoke.return_value = {
        "result": {
            "id": "10001",
            "key": "ACME-9",
            "fields": {"status": {"name": "To Do"}},
        }
    }
    adapter = _adapter(mcp=mcp)
    issue = await adapter.create_external_issue(_input_body())
    assert isinstance(issue, ExternalIssue)
    assert issue.raw_payload["key"] == "ACME-9"

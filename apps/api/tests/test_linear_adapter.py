"""Tests for the :class:`LinearAdapter` GraphQL adapter (M1d-13).

Coverage:

* ``test_connection`` happy + 401 + timeout + 429
* ``create_external_issue`` issues the ``issueCreate`` mutation with the right
  variables and unwraps the returned ``ExternalIssue``.
* ``update_external_issue`` issues the ``issueUpdate`` mutation.
* ``transition_status`` resolves the workflow-state id via
  ``workflowStates`` (cached for the life of the adapter) then issues
  ``issueUpdate(id:, input: { stateId })``.
* :class:`Severity` → priority numeric map (CRITICAL=1 .. LOW=4).
* :class:`DefectStatus` ↔ Linear state name map (default + override).
* Authorization header is the raw PAT (no ``Bearer`` prefix).
* GraphQL ``errors`` field bubbles as :class:`AdapterRemoteError`.
* Adapter passes the :class:`IssueTrackerAdapterContract` for the full
  Protocol surface (the contract suite runs against a transport-mocked
  instance via respx — the real registry would hold a per-Integration
  factory, not a pre-built instance).
* Lifespan exposes a Linear adapter factory on
  ``app.state.adapter_factories[IntegrationKind.LINEAR]``.

The transport is mocked entirely with ``respx`` — no live Linear traffic, no
cassettes on disk. ``respx`` matches by URL + method, returns
``httpx.Response`` shapes; the adapter is constructed against a real
:class:`httpx.AsyncClient` so any wire-format drift surfaces immediately.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager
from integrations_contract import run_adapter_contract
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
from suitest_api.integrations.linear_adapter import (
    DEFAULT_STATUS_MAP,
    LINEAR_GRAPHQL_URL,
    SEVERITY_TO_PRIORITY,
    CryptoService,
    DefaultCryptoService,
    LinearAdapter,
)
from suitest_api.main import create_app
from suitest_shared.domain.enums import DefectStatus, IntegrationKind, Severity

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _make_integration(
    *,
    secret_payload: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> Any:
    """Build a duck-typed :class:`Integration` stand-in with config + secrets.

    A real ``Integration`` row is a SQLAlchemy declarative whose ``EncryptedBytes``
    column auto-decrypts on load. We use :class:`MagicMock` here so the adapter
    can be constructed without booting Postgres — the only attributes touched
    are ``config`` (dict) and ``secrets_encrypted`` (str). The mock returns
    those directly, matching the shape the column type exposes.
    """
    integration = MagicMock(name="Integration")
    integration.config = config if config is not None else {"team_id": "team-uuid-1"}
    if secret_payload is None:
        secret_payload = {"LINEAR_API_KEY": "lin_api_test_token"}
    integration.secrets_encrypted = json.dumps(secret_payload)
    return integration


class _StubCrypto:
    """Minimal :class:`CryptoService` that returns a hard-coded dict.

    Avoids the JSON parse path so tests can inject malformed plaintext or
    simulate decryption errors deterministically. The default impl
    (:class:`DefaultCryptoService`) IS covered by
    :func:`test_default_crypto_service_round_trips_json`.
    """

    def __init__(self, payload: dict[str, str]) -> None:
        self._payload = payload

    def decrypt(self, blob: str) -> dict[str, str]:
        return dict(self._payload)


def _build_adapter(
    *,
    client: httpx.AsyncClient,
    config: dict[str, Any] | None = None,
    secret: dict[str, str] | None = None,
    crypto: CryptoService | None = None,
) -> LinearAdapter:
    """One-liner adapter constructor used across the test matrix."""
    integration = _make_integration(secret_payload=secret, config=config)
    return LinearAdapter(integration=integration, http_client=client, crypto=crypto)


# ---------------------------------------------------------------------------
# DefaultCryptoService
# ---------------------------------------------------------------------------


def test_default_crypto_service_round_trips_json() -> None:
    payload = {"LINEAR_API_KEY": "lin_api_x"}
    blob = json.dumps(payload)
    assert DefaultCryptoService().decrypt(blob) == payload


def test_default_crypto_service_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        DefaultCryptoService().decrypt(json.dumps(["array", "payload"]))


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_runs_viewer_query_and_returns_ok() -> None:
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        with respx.mock(assert_all_called=True) as router:
            route = router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": {
                            "viewer": {
                                "id": "user-1",
                                "name": "Maya",
                                "email": "maya@example.test",
                            }
                        }
                    },
                )
            )
            result = await adapter.test_connection()

        # The mocked route fired exactly once and the body is the viewer query.
        sent_body = json.loads(route.calls.last.request.content)
        assert "viewer" in sent_body["query"]
        assert isinstance(result, ConnectionTestResult)
        assert result.ok is True
        assert result.account_id == "user-1"
        assert result.display_name == "Maya"


@pytest.mark.asyncio
async def test_connection_401_returns_ok_false_with_linear_auth_error() -> None:
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        with respx.mock(assert_all_called=True) as router:
            router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(401, json={"error": "unauthorized"})
            )
            result = await adapter.test_connection()

        assert result.ok is False
        assert result.error is not None
        assert result.error.startswith("LINEAR_AUTH")


@pytest.mark.asyncio
async def test_connection_429_returns_ok_false_with_rate_limit_error() -> None:
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        with respx.mock(assert_all_called=True) as router:
            router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(429, json={"error": "rate limit"})
            )
            result = await adapter.test_connection()

        assert result.ok is False
        assert result.error is not None
        assert result.error.startswith("LINEAR_RATE_LIMIT")


# ---------------------------------------------------------------------------
# Authorization header convention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorization_header_carries_raw_pat_no_bearer_prefix() -> None:
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client, secret={"LINEAR_API_KEY": "lin_api_raw_token"})
        with respx.mock(assert_all_called=True) as router:
            route = router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(200, json={"data": {"viewer": {"id": "u"}}})
            )
            await adapter.test_connection()

        # Linear PAT convention: raw token, no ``Bearer`` prefix.
        auth = route.calls.last.request.headers["authorization"]
        assert auth == "lin_api_raw_token"
        assert not auth.lower().startswith("bearer ")


@pytest.mark.asyncio
async def test_missing_secret_raises_adapter_auth_error_on_mutation() -> None:
    """``create_external_issue`` raises immediately when LINEAR_API_KEY is absent.

    ``test_connection`` deliberately catches and folds auth errors into an
    ``ok=False`` :class:`ConnectionTestResult` (UI inline error), so we cover
    the missing-secret branch via a mutating Protocol method that lets the
    exception propagate.
    """
    async with httpx.AsyncClient() as client:
        integration = _make_integration(secret_payload={})
        adapter = LinearAdapter(integration=integration, http_client=client)
        with pytest.raises(AdapterAuthError, match="LINEAR_API_KEY"):
            await adapter.create_external_issue(
                ExternalIssueInput(defect_id="d", title="t", description="", severity=Severity.LOW)
            )


@pytest.mark.asyncio
async def test_missing_secret_in_test_connection_returns_ok_false() -> None:
    """``test_connection`` swallows :class:`AdapterAuthError` into ``ok=False``."""
    async with httpx.AsyncClient() as client:
        integration = _make_integration(secret_payload={})
        adapter = LinearAdapter(integration=integration, http_client=client)
        result = await adapter.test_connection()
        assert result.ok is False
        assert result.error is not None
        assert result.error.startswith("LINEAR_AUTH")


# ---------------------------------------------------------------------------
# create_external_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_external_issue_runs_issueCreate_mutation() -> None:
    body = ExternalIssueInput(
        defect_id="defc_1",
        title="Login button is unresponsive",
        description="The button does not react to click.",
        severity=Severity.HIGH,
        labels=["regression", "ui"],
        run_id="run_99",
        test_case_public_id="TC-7",
    )
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        with respx.mock(assert_all_called=True) as router:
            route = router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": {
                            "issueCreate": {
                                "success": True,
                                "issue": {
                                    "id": "issue-uuid-42",
                                    "identifier": "ENG-42",
                                    "url": "https://linear.app/team/issue/ENG-42",
                                    "title": body.title,
                                    "state": {"id": "state-1", "name": "Backlog"},
                                },
                            }
                        }
                    },
                )
            )
            issue = await adapter.create_external_issue(body)

        sent = json.loads(route.calls.last.request.content)
        assert "issueCreate" in sent["query"]
        variables = sent["variables"]["input"]
        assert variables["teamId"] == "team-uuid-1"
        assert variables["title"] == body.title
        # Severity.HIGH → priority 2 (Linear: 1=Urgent..4=Low).
        assert variables["priority"] == 2
        # Description carries the labels + back-references appended after a
        # horizontal rule — keeps Linear's label UUID expectation from
        # breaking the mutation while still surfacing the Suitest metadata.
        assert "regression" in variables["description"]
        assert "TC-7" in variables["description"]
        assert "run_99" in variables["description"]
        assert "defc_1" in variables["description"]

        assert isinstance(issue, ExternalIssue)
        assert issue.external_id == "issue-uuid-42"
        assert issue.external_key == "ENG-42"
        assert issue.external_url == "https://linear.app/team/issue/ENG-42"
        assert issue.external_status == "Backlog"


@pytest.mark.asyncio
async def test_create_external_issue_graphql_errors_bubble_as_remote_error() -> None:
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        body = ExternalIssueInput(
            defect_id="defc_x",
            title="X",
            description="",
            severity=Severity.LOW,
        )
        with respx.mock(assert_all_called=True) as router:
            router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(
                    200, json={"errors": [{"message": "Argument 'input' invalid"}]}
                )
            )
            with pytest.raises(AdapterRemoteError, match="Linear GraphQL errors"):
                await adapter.create_external_issue(body)


# ---------------------------------------------------------------------------
# update_external_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_external_issue_runs_issueUpdate_mutation() -> None:
    body = ExternalIssueInput(
        defect_id="defc_1",
        title="Updated title",
        description="Reproduced on staging",
        severity=Severity.CRITICAL,
    )
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        with respx.mock(assert_all_called=True) as router:
            route = router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": {
                            "issueUpdate": {
                                "success": True,
                                "issue": {
                                    "id": "issue-uuid-42",
                                    "identifier": "ENG-42",
                                    "url": "https://linear.app/team/issue/ENG-42",
                                    "title": body.title,
                                    "state": {"id": "s2", "name": "In Progress"},
                                },
                            }
                        }
                    },
                )
            )
            updated = await adapter.update_external_issue("ENG-42", body)

        sent = json.loads(route.calls.last.request.content)
        assert "issueUpdate" in sent["query"]
        assert sent["variables"]["id"] == "ENG-42"
        # CRITICAL → priority 1.
        assert sent["variables"]["input"]["priority"] == 1

        assert updated.external_status == "In Progress"
        assert updated.external_key == "ENG-42"


# ---------------------------------------------------------------------------
# transition_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_status_resolves_state_id_then_issueUpdate() -> None:
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        states_response = httpx.Response(
            200,
            json={
                "data": {
                    "workflowStates": {
                        "nodes": [
                            {"id": "state-backlog", "name": "Backlog"},
                            {"id": "state-progress", "name": "In Progress"},
                            {"id": "state-done", "name": "Done"},
                            {"id": "state-canceled", "name": "Canceled"},
                        ]
                    }
                }
            },
        )
        update_response = httpx.Response(
            200,
            json={
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {"id": "issue-1", "state": {"id": "state-done", "name": "Done"}},
                    }
                }
            },
        )
        with respx.mock(assert_all_called=True) as router:
            route = router.post(LINEAR_GRAPHQL_URL).mock(
                side_effect=[states_response, update_response]
            )
            await adapter.transition_status("issue-1", DefectStatus.RESOLVED)

        # Two requests: workflowStates, then issueUpdate.
        assert route.call_count == 2
        first_body = json.loads(route.calls[0].request.content)
        assert "workflowStates" in first_body["query"]
        assert first_body["variables"]["teamId"] == "team-uuid-1"
        second_body = json.loads(route.calls[1].request.content)
        assert "issueUpdate" in second_body["query"]
        assert second_body["variables"]["stateId"] == "state-done"
        assert second_body["variables"]["id"] == "issue-1"


@pytest.mark.asyncio
async def test_transition_status_caches_workflow_states_across_calls() -> None:
    """Second transition reuses cached state list — only 1 ``workflowStates`` request."""
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        states_response = httpx.Response(
            200,
            json={
                "data": {
                    "workflowStates": {
                        "nodes": [
                            {"id": "state-backlog", "name": "Backlog"},
                            {"id": "state-done", "name": "Done"},
                            {"id": "state-canceled", "name": "Canceled"},
                        ]
                    }
                }
            },
        )
        update_response = httpx.Response(
            200,
            json={
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {"id": "i", "state": {"id": "x", "name": "Done"}},
                    }
                }
            },
        )
        with respx.mock(assert_all_called=True) as router:
            route = router.post(LINEAR_GRAPHQL_URL).mock(
                side_effect=[states_response, update_response, update_response]
            )
            await adapter.transition_status("i", DefectStatus.RESOLVED)
            await adapter.transition_status("i", DefectStatus.CLOSED)

        # 1 workflowStates + 2 issueUpdates == 3 calls total.
        assert route.call_count == 3
        first_body = json.loads(route.calls[0].request.content)
        assert "workflowStates" in first_body["query"]
        # Subsequent calls skip the states query.
        for i in (1, 2):
            body = json.loads(route.calls[i].request.content)
            assert "issueUpdate" in body["query"]


@pytest.mark.asyncio
async def test_transition_status_unmapped_status_raises_remote_error() -> None:
    """Override the map to drop WONT_FIX so transition raises clearly."""
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(
            client=client,
            config={
                "team_id": "team-uuid-1",
                "status_map": {
                    "OPEN": "Backlog",
                    "IN_PROGRESS": "In Progress",
                    "RESOLVED": "Done",
                    "CLOSED": "Done",
                    # WONT_FIX intentionally omitted so the merge replaces nothing
                    # — but the default still has it. Use an unmappable target by
                    # asking for a status whose external name doesn't exist on the
                    # team workflow.
                },
            },
        )
        # adapter._status_map has WONT_FIX → "Canceled". Mock a workflow without
        # Canceled state so the resolve step raises.
        states_response = httpx.Response(
            200,
            json={
                "data": {
                    "workflowStates": {
                        "nodes": [
                            {"id": "state-backlog", "name": "Backlog"},
                            {"id": "state-done", "name": "Done"},
                        ]
                    }
                }
            },
        )
        with respx.mock(assert_all_called=True) as router:
            router.post(LINEAR_GRAPHQL_URL).mock(side_effect=[states_response])
            with pytest.raises(AdapterRemoteError, match="workflow state named 'Canceled'"):
                await adapter.transition_status("issue-1", DefectStatus.WONT_FIX)


# ---------------------------------------------------------------------------
# map_external_status_to_defect_status
# ---------------------------------------------------------------------------


def test_map_external_status_default_map() -> None:
    integration = _make_integration()
    # http_client unused — the map call is in-memory.
    adapter = LinearAdapter(
        integration=integration,
        http_client=MagicMock(spec=httpx.AsyncClient),
    )
    # Per default map: CLOSED reverse-loses to RESOLVED because both forward to
    # "Done" — the reverse direction only stores one DefectStatus per external
    # name (the LAST one inserted at construction time wins). For Linear that's
    # CLOSED because dict iteration follows insertion order and CLOSED is
    # registered after RESOLVED in :data:`DEFAULT_STATUS_MAP`.
    assert adapter.map_external_status_to_defect_status("Done") is DefectStatus.CLOSED
    assert adapter.map_external_status_to_defect_status("In Progress") is DefectStatus.IN_PROGRESS
    assert adapter.map_external_status_to_defect_status("Backlog") is DefectStatus.OPEN
    assert adapter.map_external_status_to_defect_status("Canceled") is DefectStatus.WONT_FIX
    # Reverse aliases (Triage → OPEN) wired at init time.
    assert adapter.map_external_status_to_defect_status("Triage") is DefectStatus.OPEN
    # Unknown returns None — no exception.
    assert adapter.map_external_status_to_defect_status("Whatever") is None


def test_status_map_override_from_integration_config() -> None:
    integration = _make_integration(
        config={
            "team_id": "team-1",
            "status_map": {"OPEN": "Triage", "RESOLVED": "Shipped"},
        },
    )
    adapter = LinearAdapter(
        integration=integration,
        http_client=MagicMock(spec=httpx.AsyncClient),
    )
    # Override surfaces in BOTH forward + reverse directions.
    assert adapter.map_external_status_to_defect_status("Shipped") is DefectStatus.RESOLVED
    # Forward direction: the canonical RESOLVED → external name is the override.
    sm = adapter._status_map
    assert sm.defect_to_external(DefectStatus.RESOLVED) == "Shipped"
    assert sm.defect_to_external(DefectStatus.OPEN) == "Triage"
    # Non-overridden keys keep defaults.
    assert sm.defect_to_external(DefectStatus.WONT_FIX) == "Canceled"


# ---------------------------------------------------------------------------
# Severity ↔ priority
# ---------------------------------------------------------------------------


def test_severity_to_priority_table() -> None:
    assert SEVERITY_TO_PRIORITY[Severity.CRITICAL] == 1
    assert SEVERITY_TO_PRIORITY[Severity.HIGH] == 2
    assert SEVERITY_TO_PRIORITY[Severity.MEDIUM] == 3
    assert SEVERITY_TO_PRIORITY[Severity.LOW] == 4


# ---------------------------------------------------------------------------
# Timeout / rate-limit translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_translates_to_adapter_timeout_error() -> None:
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        with respx.mock(assert_all_called=True) as router:
            router.post(LINEAR_GRAPHQL_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
            with pytest.raises(AdapterTimeoutError):
                await adapter.create_external_issue(
                    ExternalIssueInput(
                        defect_id="d",
                        title="t",
                        description="",
                        severity=Severity.LOW,
                    )
                )


@pytest.mark.asyncio
async def test_429_translates_to_rate_limit_error_on_mutation() -> None:
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        with respx.mock(assert_all_called=True) as router:
            router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(429, json={"error": "throttled"})
            )
            with pytest.raises(AdapterRateLimitError):
                await adapter.create_external_issue(
                    ExternalIssueInput(
                        defect_id="d",
                        title="t",
                        description="",
                        severity=Severity.LOW,
                    )
                )


# ---------------------------------------------------------------------------
# team_id config requirement
# ---------------------------------------------------------------------------


def test_constructor_raises_when_team_id_missing() -> None:
    integration = _make_integration(config={})
    with pytest.raises(AdapterRemoteError, match="team_id"):
        LinearAdapter(
            integration=integration,
            http_client=MagicMock(spec=httpx.AsyncClient),
        )


# ---------------------------------------------------------------------------
# Protocol contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapter_satisfies_issue_tracker_protocol() -> None:
    """LinearAdapter satisfies the @runtime_checkable Protocol."""
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        assert isinstance(adapter, IssueTrackerAdapter)
        assert adapter.kind is IntegrationKind.LINEAR


@pytest.mark.asyncio
async def test_full_contract_suite_passes_with_mocked_transport() -> None:
    """Runs :func:`run_adapter_contract` with respx-mocked Linear responses.

    The contract calls every Protocol method in sequence; we stage a small
    response table so each one returns a sensible payload. Wire-shape drift in
    one method will surface as a contract assertion failure here.
    """
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client)
        with respx.mock(assert_all_called=False) as router:
            issue_payload = {
                "id": "issue-uuid-1",
                "identifier": "ENG-1",
                "url": "https://linear.app/team/issue/ENG-1",
                "title": "contract-test defect title",
                "state": {"id": "state-progress", "name": "In Progress"},
            }

            def _responder(request: httpx.Request) -> httpx.Response:
                body = json.loads(request.content)
                query = body.get("query", "")
                if "viewer" in query:
                    return httpx.Response(
                        200,
                        json={
                            "data": {"viewer": {"id": "u-1", "name": "Bot", "email": "b@x.test"}}
                        },
                    )
                if "issueCreate" in query:
                    return httpx.Response(
                        200,
                        json={"data": {"issueCreate": {"success": True, "issue": issue_payload}}},
                    )
                if "workflowStates" in query:
                    return httpx.Response(
                        200,
                        json={
                            "data": {
                                "workflowStates": {
                                    "nodes": [
                                        {"id": "state-progress", "name": "In Progress"},
                                        {"id": "state-done", "name": "Done"},
                                        {"id": "state-canceled", "name": "Canceled"},
                                        {"id": "state-backlog", "name": "Backlog"},
                                    ]
                                }
                            }
                        },
                    )
                if "issueUpdate" in query:
                    return httpx.Response(
                        200,
                        json={"data": {"issueUpdate": {"success": True, "issue": issue_payload}}},
                    )
                if "IssueFetch" in query or (
                    "issue(" in query and "issueCreate" not in query and "issueUpdate" not in query
                ):
                    return httpx.Response(
                        200,
                        json={"data": {"issue": issue_payload}},
                    )
                return httpx.Response(500, json={"errors": [{"message": "unhandled"}]})

            router.post(LINEAR_GRAPHQL_URL).mock(side_effect=_responder)
            await run_adapter_contract(adapter)


# ---------------------------------------------------------------------------
# Default map shape sanity
# ---------------------------------------------------------------------------


def test_default_status_map_contents() -> None:
    assert DEFAULT_STATUS_MAP[DefectStatus.OPEN] == "Backlog"
    assert DEFAULT_STATUS_MAP[DefectStatus.IN_PROGRESS] == "In Progress"
    assert DEFAULT_STATUS_MAP[DefectStatus.RESOLVED] == "Done"
    assert DEFAULT_STATUS_MAP[DefectStatus.CLOSED] == "Done"
    assert DEFAULT_STATUS_MAP[DefectStatus.WONT_FIX] == "Canceled"


# ---------------------------------------------------------------------------
# Lifespan factory registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_registers_linear_adapter_factory() -> None:
    """``app.state.adapter_factories[LINEAR]`` is callable and yields a LinearAdapter."""
    app = create_app()
    async with LifespanManager(app):
        factories = getattr(app.state, "adapter_factories", None)
        assert factories is not None
        factory = factories.get(IntegrationKind.LINEAR)
        assert callable(factory)
        async with httpx.AsyncClient() as client:
            integration = _make_integration()
            adapter = factory(integration=integration, http_client=client)
            assert isinstance(adapter, LinearAdapter)
            assert isinstance(adapter, IssueTrackerAdapter)


# ---------------------------------------------------------------------------
# Stub crypto end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_crypto_service_is_invoked_for_token_resolution() -> None:
    crypto = _StubCrypto({"LINEAR_API_KEY": "stub-token"})
    async with httpx.AsyncClient() as client:
        adapter = _build_adapter(client=client, crypto=crypto)
        with respx.mock(assert_all_called=True) as router:
            route = router.post(LINEAR_GRAPHQL_URL).mock(
                return_value=httpx.Response(200, json={"data": {"viewer": {"id": "u"}}})
            )
            await adapter.test_connection()
        assert route.calls.last.request.headers["authorization"] == "stub-token"

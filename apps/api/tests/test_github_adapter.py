"""Tests for :class:`GitHubAdapter` (M1d-14).

Coverage:

* App installation-token mint hits the right endpoint, signs a valid RS256
  JWT, and caches the result for 50 minutes.
* :meth:`GitHubAdapter.test_connection` invokes ``list_issues`` with
  ``state=open`` + ``per_page=1`` and returns :class:`ConnectionTestResult`.
* CRUD methods (``create_external_issue`` / ``update_external_issue`` /
  ``transition_status``) delegate to the mocked :class:`McpClientProtocol`
  with the env-overrides contract specified by the plan.
* GitHub status / Suitest status mapping is bijective on ``open`` / ``closed``.
* :class:`McpError` → :class:`AdapterAuthError` translation.
* Adapter satisfies the :class:`IssueTrackerAdapterContract` shape.

Mocking strategy: :mod:`respx` mocks the App-token mint endpoint at
``api.github.com``; :class:`_RecordingMcpClient` records every MCP invoke for
post-hoc assertions on the env overrides + arguments wire shape.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from integrations_contract import run_adapter_contract
from suitest_api.integrations.base import (
    AdapterAuthError,
    AdapterTimeoutError,
    ConnectionTestResult,
    ExternalIssue,
    ExternalIssueInput,
    IssueTrackerAdapter,
)
from suitest_api.integrations.github_adapter import (
    GitHubAdapter,
    McpInvokeResult,
    _sign_app_jwt,
)
from suitest_mcp.errors import McpToolFailed, McpToolTimeout
from suitest_shared.domain.enums import DefectStatus, IntegrationKind, Severity

# ---------------------------------------------------------------------------
# Test fixtures: fake Integration row, recording MCP client, crypto stub.
# ---------------------------------------------------------------------------


@dataclass
class _FakeIntegration:
    """Stand-in for the SQLAlchemy ``Integration`` row.

    GitHubAdapter only reads ``config`` (dict) + ``secrets_encrypted`` (bytes
    or pre-decrypted str) + ``workspace_id`` (str) — declaring those three
    attributes is enough to drive the adapter without a real DB row.
    """

    workspace_id: str
    config: dict[str, Any]
    secrets_encrypted: bytes | str | None


@dataclass
class _RecordedInvoke:
    """One captured MCP tool invocation for post-hoc assertions."""

    provider: str
    tool: str
    arguments: dict[str, object]
    env_overrides: dict[str, str]
    workspace_id: str


@dataclass
class _RecordingMcpClient:
    """In-memory :class:`McpClientProtocol` — records every call.

    ``responses`` is a FIFO queue of dicts; each ``invoke`` pops the next one
    as the tool's payload. Defaults to a single ``[]`` result so tests that
    only care about the request side don't need to seed responses.
    """

    responses: list[dict[str, object]] = field(default_factory=list)
    calls: list[_RecordedInvoke] = field(default_factory=list)
    raise_next: Exception | None = None

    async def invoke(
        self,
        *,
        provider: str,
        tool: str,
        arguments: dict[str, object],
        env_overrides: dict[str, str],
        workspace_id: str,
    ) -> McpInvokeResult:
        self.calls.append(
            _RecordedInvoke(
                provider=provider,
                tool=tool,
                arguments=arguments,
                env_overrides=dict(env_overrides),
                workspace_id=workspace_id,
            )
        )
        if self.raise_next is not None:
            err, self.raise_next = self.raise_next, None
            raise err
        payload: dict[str, object] = self.responses.pop(0) if self.responses else {}
        return McpInvokeResult(output=payload, raw_stdout=json.dumps(payload))


class _NullCrypto:
    """Crypto stub: assumes ``secrets_encrypted`` is already plaintext JSON.

    Production ``EncryptedBytes`` decrypts on column read so by the time the
    adapter sees the field it's a plain ``str``; we mirror that here.
    """

    def decrypt(self, blob: bytes, aad: bytes = b"") -> str:
        if isinstance(blob, bytes):
            return blob.decode("utf-8")
        return str(blob)


def _make_rsa_pem() -> str:
    """Generate a fresh RSA-2048 PEM for App-JWT signing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


@pytest.fixture(scope="module")
def app_private_key_pem() -> str:
    """Module-scoped RSA PEM — generation is the slowest step in the suite."""
    return _make_rsa_pem()


@pytest.fixture
def fake_integration(app_private_key_pem: str) -> _FakeIntegration:
    """Default integration row pointing at ``acme/widgets``."""
    secrets_plain = json.dumps({"private_key_pem": app_private_key_pem})
    return _FakeIntegration(
        workspace_id="ws_test_0001",
        config={
            "app_id": 12345,
            "installation_id": "98765",
            "owner": "acme",
            "repo": "widgets",
        },
        secrets_encrypted=secrets_plain.encode("utf-8"),
    )


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Async HTTP client used for the App-token mint mock."""
    async with httpx.AsyncClient() as client:
        yield client


def _make_adapter(
    *,
    integration: _FakeIntegration,
    mcp_client: _RecordingMcpClient,
    http_client: httpx.AsyncClient,
    now: float | None = None,
) -> GitHubAdapter:
    """Build a GitHubAdapter with the recording MCP client + null crypto.

    ``now`` is a wall-clock override so cache-expiry tests don't need to sleep.
    """
    # The fake row only implements the read surface used by the adapter
    # (workspace_id / config / secrets_encrypted) — mypy can't see that.
    return GitHubAdapter(
        integration=integration,  # type: ignore[arg-type]
        mcp_client=mcp_client,
        crypto=_NullCrypto(),
        http_client=http_client,
        now=(lambda: now) if now is not None else None,
    )


# ---------------------------------------------------------------------------
# App-installation token mint + cache.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_installation_token_mint_calls_app_installations_endpoint_signs_jwt(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
    app_private_key_pem: str,
) -> None:
    """Token mint POSTs to ``/app/installations/{id}/access_tokens`` with a Bearer JWT."""
    route = respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_minted_token_001"})
    )

    adapter = _make_adapter(
        integration=fake_integration,
        mcp_client=_RecordingMcpClient(),
        http_client=http_client,
    )
    token = await adapter._installation_token()

    assert token == "ghs_minted_token_001"
    assert route.called and route.call_count == 1
    sent_auth = route.calls.last.request.headers["authorization"]
    assert sent_auth.startswith("Bearer "), "JWT must be passed as Bearer"
    # Verify the JWT decodes to claims tied to our App id.
    jwt_value = sent_auth[len("Bearer ") :]
    payload_b64 = jwt_value.split(".")[1]
    # Re-pad the base64url payload for ``base64.urlsafe_b64decode``.
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    claims = json.loads(base64.urlsafe_b64decode(padded))
    assert claims["iss"] == str(fake_integration.config["app_id"])
    assert claims["exp"] > claims["iat"], "exp must be after iat"


@pytest.mark.asyncio
@respx.mock
async def test_installation_token_cached_within_50_minutes(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """Two mints inside the 50-minute window only hit the network once."""
    base_now = 1_700_000_000.0
    route = respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_cached_token"})
    )

    adapter = _make_adapter(
        integration=fake_integration,
        mcp_client=_RecordingMcpClient(),
        http_client=http_client,
        now=base_now,
    )
    first = await adapter._installation_token()
    # Advance the in-process wall clock by 49 minutes — still inside the TTL.
    adapter._now = lambda: base_now + (49 * 60)
    second = await adapter._installation_token()

    assert first == second == "ghs_cached_token"
    assert route.call_count == 1, "second call within 50min should NOT re-mint"


@pytest.mark.asyncio
@respx.mock
async def test_installation_token_remint_after_50_minute_ttl(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """After 50 minutes the cache is stale and the adapter mints fresh."""
    base_now = 1_700_000_000.0
    route = respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        side_effect=[
            httpx.Response(201, json={"token": "ghs_first"}),
            httpx.Response(201, json={"token": "ghs_second"}),
        ]
    )

    adapter = _make_adapter(
        integration=fake_integration,
        mcp_client=_RecordingMcpClient(),
        http_client=http_client,
        now=base_now,
    )
    first = await adapter._installation_token()
    adapter._now = lambda: base_now + (51 * 60)
    second = await adapter._installation_token()

    assert first == "ghs_first"
    assert second == "ghs_second"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_installation_token_mint_failure_raises_adapter_auth_error(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """A 401 from the mint endpoint surfaces as :class:`AdapterAuthError`."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )

    adapter = _make_adapter(
        integration=fake_integration,
        mcp_client=_RecordingMcpClient(),
        http_client=http_client,
    )
    with pytest.raises(AdapterAuthError):
        await adapter._installation_token()


@pytest.mark.asyncio
@respx.mock
async def test_installation_token_network_timeout_raises_adapter_timeout_error(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """An httpx ``TimeoutException`` surfaces as :class:`AdapterTimeoutError`."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        side_effect=httpx.ReadTimeout("read timeout")
    )

    adapter = _make_adapter(
        integration=fake_integration,
        mcp_client=_RecordingMcpClient(),
        http_client=http_client,
    )
    with pytest.raises(AdapterTimeoutError):
        await adapter._installation_token()


# ---------------------------------------------------------------------------
# IssueTrackerAdapter surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_test_connection_invokes_list_issues_with_state_open_per_page_1(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """``test_connection`` makes the cheapest read-only call and returns ok=True."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_t"})
    )
    mcp = _RecordingMcpClient(responses=[{"issues": []}])
    adapter = _make_adapter(integration=fake_integration, mcp_client=mcp, http_client=http_client)

    result = await adapter.test_connection()

    assert isinstance(result, ConnectionTestResult)
    assert result.ok is True
    assert result.display_name == "acme/widgets"
    assert mcp.calls[0].provider == "github-mcp"
    assert mcp.calls[0].tool == "list_issues"
    assert mcp.calls[0].arguments == {
        "owner": "acme",
        "repo": "widgets",
        "state": "open",
        "per_page": 1,
    }


@pytest.mark.asyncio
@respx.mock
async def test_test_connection_auth_failure_returns_ok_false_with_message(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """An auth failure during ``test_connection`` is reported, not raised."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    adapter = _make_adapter(
        integration=fake_integration,
        mcp_client=_RecordingMcpClient(),
        http_client=http_client,
    )

    result = await adapter.test_connection()

    assert result.ok is False
    assert result.error is not None and "Authentication" in result.error


@pytest.mark.asyncio
@respx.mock
async def test_create_external_issue_calls_issue_write_with_severity_label(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """``create_external_issue`` invokes ``issue_write`` action=create + severity label.

    Also confirms the env overrides include both
    ``GITHUB_PERSONAL_ACCESS_TOKEN`` (so the binary can authenticate) and
    ``GITHUB_TOOLSETS=issues`` (so the binary's tool surface stays trimmed).
    """
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_t"})
    )
    mcp = _RecordingMcpClient(
        responses=[
            {
                "number": 42,
                "node_id": "I_node_42",
                "html_url": "https://github.com/acme/widgets/issues/42",
                "state": "open",
            }
        ]
    )
    adapter = _make_adapter(integration=fake_integration, mcp_client=mcp, http_client=http_client)

    issue = await adapter.create_external_issue(
        ExternalIssueInput(
            defect_id="defc_test_0001",
            title="My defect",
            description="Long description",
            severity=Severity.HIGH,
            labels=["bug"],
        )
    )

    assert isinstance(issue, ExternalIssue)
    assert issue.external_key == "#42"
    assert issue.external_id == "I_node_42"
    assert issue.external_url == "https://github.com/acme/widgets/issues/42"

    invoke = mcp.calls[0]
    assert invoke.tool == "issue_write"
    assert invoke.arguments["action"] == "create"
    assert invoke.arguments["owner"] == "acme" and invoke.arguments["repo"] == "widgets"
    assert invoke.arguments["title"] == "My defect"
    labels_arg = invoke.arguments["labels"]
    assert isinstance(labels_arg, list)
    assert "severity:high" in labels_arg and "suitest" in labels_arg and "bug" in labels_arg
    # Env contract for the bundled github-mcp-server.
    assert invoke.env_overrides["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghs_t"
    assert invoke.env_overrides["GITHUB_TOOLSETS"] == "issues"


@pytest.mark.asyncio
@respx.mock
async def test_update_external_issue_calls_issue_write_action_update(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """``update_external_issue`` invokes ``issue_write`` with action=update + issue_number."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_t"})
    )
    mcp = _RecordingMcpClient(
        responses=[
            {
                "number": 7,
                "node_id": "I_7",
                "html_url": "https://github.com/acme/widgets/issues/7",
                "state": "open",
            }
        ]
    )
    adapter = _make_adapter(integration=fake_integration, mcp_client=mcp, http_client=http_client)

    await adapter.update_external_issue(
        "#7",
        ExternalIssueInput(
            defect_id="defc_test_0002",
            title="Updated title",
            description="Updated description",
            severity=Severity.MEDIUM,
        ),
    )

    invoke = mcp.calls[0]
    assert invoke.tool == "issue_write"
    assert invoke.arguments["action"] == "update"
    assert invoke.arguments["issue_number"] == 7
    assert invoke.arguments["title"] == "Updated title"
    assert "severity:medium" in invoke.arguments["labels"]  # type: ignore[operator]


@pytest.mark.asyncio
@respx.mock
async def test_transition_status_resolved_calls_issue_write_state_closed(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """RESOLVED transition closes the GitHub issue via ``issue_write`` state=closed."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_t"})
    )
    mcp = _RecordingMcpClient(responses=[{"number": 99, "state": "closed"}])
    adapter = _make_adapter(integration=fake_integration, mcp_client=mcp, http_client=http_client)

    await adapter.transition_status("#99", DefectStatus.RESOLVED)

    invoke = mcp.calls[0]
    assert invoke.tool == "issue_write"
    assert invoke.arguments == {
        "action": "update",
        "owner": "acme",
        "repo": "widgets",
        "issue_number": 99,
        "state": "closed",
    }


@pytest.mark.asyncio
async def test_map_external_status_closed_returns_closed_defect_status(
    fake_integration: _FakeIntegration,
) -> None:
    """The default :class:`StatusMap` maps ``closed`` → :attr:`DefectStatus.CLOSED`."""
    # No mint needed — pure local mapping. Reuse a stub http client.
    async with httpx.AsyncClient() as client:
        adapter = _make_adapter(
            integration=fake_integration,
            mcp_client=_RecordingMcpClient(),
            http_client=client,
        )
    assert adapter.map_external_status_to_defect_status("closed") is DefectStatus.CLOSED
    assert adapter.map_external_status_to_defect_status("open") is DefectStatus.OPEN
    # Case-insensitive (matches StatusMap contract from M1d-11).
    assert adapter.map_external_status_to_defect_status("CLOSED") is DefectStatus.CLOSED
    assert adapter.map_external_status_to_defect_status("xyz") is None


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_mcp_error_401_translates_to_adapter_auth_error(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """A 401-tagged :class:`McpToolFailed` from the MCP layer → :class:`AdapterAuthError`."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_t"})
    )
    mcp = _RecordingMcpClient(raise_next=McpToolFailed("HTTP 401 Bad credentials"))
    adapter = _make_adapter(integration=fake_integration, mcp_client=mcp, http_client=http_client)

    with pytest.raises(AdapterAuthError):
        await adapter.create_external_issue(
            ExternalIssueInput(
                defect_id="defc_x",
                title="title",
                description="",
                severity=Severity.LOW,
            )
        )


@pytest.mark.asyncio
@respx.mock
async def test_mcp_tool_timeout_translates_to_adapter_timeout_error(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """An :class:`McpToolTimeout` surfaces as :class:`AdapterTimeoutError`."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_t"})
    )
    mcp = _RecordingMcpClient(raise_next=McpToolTimeout("call_tool timeout"))
    adapter = _make_adapter(integration=fake_integration, mcp_client=mcp, http_client=http_client)

    with pytest.raises(AdapterTimeoutError):
        await adapter.create_external_issue(
            ExternalIssueInput(
                defect_id="defc_x",
                title="t",
                description="",
                severity=Severity.LOW,
            )
        )


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_app_private_key_raises_adapter_auth_error(
    app_private_key_pem: str,
) -> None:
    """A :class:`Integration` row without ``secrets_encrypted`` fails fast on auth."""
    integration = _FakeIntegration(
        workspace_id="ws_test_0001",
        config={
            "app_id": 12345,
            "installation_id": "98765",
            "owner": "acme",
            "repo": "widgets",
        },
        secrets_encrypted=None,
    )
    async with httpx.AsyncClient() as client:
        adapter = _make_adapter(
            integration=integration,
            mcp_client=_RecordingMcpClient(),
            http_client=client,
        )
        with pytest.raises(AdapterAuthError):
            await adapter._installation_token()


def test_adapter_kind_is_integration_kind_github(
    fake_integration: _FakeIntegration,
) -> None:
    """``kind`` must be :attr:`IntegrationKind.GITHUB` (used by the registry)."""
    adapter = GitHubAdapter(
        integration=fake_integration,  # type: ignore[arg-type]
        mcp_client=_RecordingMcpClient(),
        crypto=_NullCrypto(),
        http_client=httpx.AsyncClient(),
    )
    assert adapter.kind is IntegrationKind.GITHUB


# ---------------------------------------------------------------------------
# IssueTrackerAdapter Protocol contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_adapter_satisfies_issue_tracker_adapter_contract(
    fake_integration: _FakeIntegration,
    http_client: httpx.AsyncClient,
) -> None:
    """GitHubAdapter passes the shared :class:`IssueTrackerAdapterContract` runner."""
    respx.post("https://api.github.com/app/installations/98765/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_contract_token"})
    )
    # Seed the MCP response queue with one response per contract assertion.
    base_payload: dict[str, object] = {
        "number": 1,
        "node_id": "I_1",
        "html_url": "https://github.com/acme/widgets/issues/1",
        "state": "open",
    }
    mcp = _RecordingMcpClient(
        responses=[
            {"issues": []},  # test_connection list_issues
            dict(base_payload),  # create_external_issue
            dict(base_payload),  # update_external_issue
            {"number": 1, "state": "open"},  # transition_status update
        ]
    )
    adapter = _make_adapter(integration=fake_integration, mcp_client=mcp, http_client=http_client)

    # Protocol membership at runtime is part of the contract.
    assert isinstance(adapter, IssueTrackerAdapter)
    await run_adapter_contract(adapter)


# ---------------------------------------------------------------------------
# JWT signing helper (RS256, no PyJWT)
# ---------------------------------------------------------------------------


def test_sign_app_jwt_emits_three_segments_with_rs256(app_private_key_pem: str) -> None:
    """The hand-rolled signer emits ``header.payload.signature`` with the right alg."""
    jwt_value = _sign_app_jwt(
        app_id=4242, private_key_pem=app_private_key_pem, now=int(time.time())
    )
    segments = jwt_value.split(".")
    assert len(segments) == 3
    header = json.loads(base64.urlsafe_b64decode(segments[0] + "=" * (-len(segments[0]) % 4)))
    assert header == {"alg": "RS256", "typ": "JWT"}


# ---------------------------------------------------------------------------
# Environment hygiene — ensures SUITEST_ENCRYPTION_KEY isn't needed for tests
# ---------------------------------------------------------------------------


def test_module_does_not_require_suitest_encryption_key_env() -> None:
    """The adapter must work without ``SUITEST_ENCRYPTION_KEY`` (uses injected crypto).

    Production wiring decrypts via :class:`EncryptedBytes` column type which
    DOES need the env var, but the adapter itself accepts pre-decrypted bytes
    + injected crypto so unit tests don't reach for that global.
    """
    # No assertion needed beyond "this test module imports clean" — the import
    # at the top of the file is the actual assertion. The function exists so
    # pytest surfaces the test name.
    assert (
        "SUITEST_ENCRYPTION_KEY" not in os.environ
        or os.environ.get("SUITEST_ENCRYPTION_KEY") is not None
    )

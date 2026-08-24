"""Credential-resolution tests — the one place that knows what a stored config means."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from suitest_core.llm_credentials import (
    CHATGPT_API_BASE,
    CHATGPT_PROVIDER,
    GOOGLE_VERTEX_PROVIDER,
    CredentialError,
    resolve_credential,
    vertex_openai_base_url,
)
from suitest_core.oauth import StoredOAuthTokens


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _access_token(*, expires_in: timedelta) -> str:
    """A JWT whose ``exp`` sits ``expires_in`` from now."""
    exp = int((datetime.now(tz=UTC) + expires_in).timestamp())

    def seg(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{seg(b'{}')}.{seg(json.dumps({'exp': exp}).encode())}.sig"


def _unused(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no HTTP call expected, got {request.url}")


@pytest.mark.asyncio
async def test_api_key_config_resolves_to_itself() -> None:
    """The pasted-key path must be untouched by the OAuth machinery."""
    async with _client(_unused) as client:
        credential, persist = await resolve_credential(
            client,
            provider="anthropic",
            api_key="sk-ant-1",
            base_url=None,
            oauth_tokens_json=None,
        )

    assert credential.provider == "anthropic"
    assert credential.api_key == "sk-ant-1"
    assert credential.base_url is None
    assert credential.extra_headers == {}
    assert persist is None


@pytest.mark.asyncio
async def test_a_local_provider_keeps_its_base_url() -> None:
    """A LOCAL config's own endpoint is passed through verbatim."""
    async with _client(_unused) as client:
        credential, _ = await resolve_credential(
            client,
            provider="ollama",
            api_key=None,
            base_url="http://localhost:11434",
            oauth_tokens_json=None,
        )
    assert credential.base_url == "http://localhost:11434"


@pytest.mark.asyncio
async def test_a_valid_oauth_credential_needs_no_round_trip() -> None:
    """A token with time left resolves offline: bearer, backend URL, account header."""
    stored = StoredOAuthTokens(
        access_token=_access_token(expires_in=timedelta(hours=1)),
        refresh_token="rt",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        account_id="acc_1",
    )

    async with _client(_unused) as client:
        credential, persist = await resolve_credential(
            client,
            provider=CHATGPT_PROVIDER,
            api_key=None,
            base_url=None,
            oauth_tokens_json=stored.model_dump_json(),
        )

    assert credential.api_key == stored.access_token
    assert credential.base_url == CHATGPT_API_BASE
    assert credential.extra_headers == {"chatgpt-account-id": "acc_1"}
    assert persist is None


@pytest.mark.asyncio
async def test_an_expiring_credential_is_refreshed_and_handed_back_to_persist() -> None:
    """Refresh happens on the read path, and the caller is told to store the result."""
    fresh_access = _access_token(expires_in=timedelta(hours=1))
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        # A refresh response commonly omits the id token.
        return httpx.Response(200, json={"access_token": fresh_access, "refresh_token": "rt2"})

    stored = StoredOAuthTokens(
        access_token="stale",
        refresh_token="rt1",
        id_token="it1",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=2),
        account_id="acc_1",
        email="dev@example.com",
    )

    async with _client(handler) as client:
        credential, persist = await resolve_credential(
            client,
            provider=CHATGPT_PROVIDER,
            api_key=None,
            base_url=None,
            oauth_tokens_json=stored.model_dump_json(),
        )

    assert calls[0]["grant_type"] == "refresh_token"
    assert calls[0]["refresh_token"] == "rt1"
    assert credential.api_key == fresh_access
    assert persist is not None

    merged = StoredOAuthTokens.model_validate_json(persist)
    assert merged.refresh_token == "rt2"
    # Fields the response did not carry survive the merge.
    assert merged.id_token == "it1"
    assert merged.account_id == "acc_1"
    assert merged.email == "dev@example.com"


@pytest.mark.asyncio
async def test_an_unrefreshable_credential_asks_for_a_new_sign_in() -> None:
    """No refresh token and an expired access token is a dead credential."""
    stored = StoredOAuthTokens(
        access_token="stale",
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )

    async with _client(_unused) as client:
        with pytest.raises(CredentialError) as exc:
            await resolve_credential(
                client,
                provider=CHATGPT_PROVIDER,
                api_key=None,
                base_url=None,
                oauth_tokens_json=stored.model_dump_json(),
            )
    assert exc.value.code == "REFRESH_IMPOSSIBLE"


@pytest.mark.asyncio
async def test_refreshing_without_a_client_is_reported_not_guessed() -> None:
    """A caller with no HTTP client must not silently send a stale token."""
    stored = StoredOAuthTokens(access_token="stale", refresh_token="rt")

    with pytest.raises(CredentialError) as exc:
        await resolve_credential(
            None,
            provider=CHATGPT_PROVIDER,
            api_key=None,
            base_url=None,
            oauth_tokens_json=stored.model_dump_json(),
        )
    assert exc.value.code == "REFRESH_UNAVAILABLE"


@pytest.mark.asyncio
async def test_a_google_config_gets_no_chatgpt_endpoint_or_header() -> None:
    """The bug the per-provider dispatch exists to prevent."""
    stored = StoredOAuthTokens(
        access_token="ya29.live",
        refresh_token="1//r",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        account_id="acc_should_not_leak",
    )
    base = vertex_openai_base_url(project="proj", location="us-central1")

    async with _client(_unused) as client:
        credential, persist = await resolve_credential(
            client,
            provider=GOOGLE_VERTEX_PROVIDER,
            api_key=None,
            base_url=base,
            oauth_tokens_json=stored.model_dump_json(),
        )

    assert credential.base_url == base
    assert CHATGPT_API_BASE not in (credential.base_url or "")
    # No account header: Google identifies the caller from the bearer alone.
    assert credential.extra_headers == {}
    assert credential.api_key == "ya29.live"
    assert persist is None


@pytest.mark.asyncio
async def test_google_refresh_sends_the_client_secret_and_keeps_the_refresh_token() -> None:
    """Google does not reissue the refresh token, so the stored one must survive."""
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"access_token": "ya29.new", "expires_in": 3599})

    stale = StoredOAuthTokens(
        access_token="ya29.old",
        refresh_token="1//keep-me",
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
    )

    async with _client(handler) as client:
        credential, persist = await resolve_credential(
            client,
            provider=GOOGLE_VERTEX_PROVIDER,
            api_key=None,
            base_url="https://us-central1-aiplatform.googleapis.com/v1/x/openapi",
            oauth_tokens_json=stale.model_dump_json(),
            client_id="cid",
            client_secret="csec",
        )

    assert seen["client_secret"] == ["csec"]
    assert credential.api_key == "ya29.new"
    assert persist is not None
    assert StoredOAuthTokens.model_validate_json(persist).refresh_token == "1//keep-me"


@pytest.mark.asyncio
async def test_tokens_on_a_provider_with_no_oauth_backend_are_refused() -> None:
    """Better a loud misconfiguration than a silent call to the wrong endpoint."""
    stored = StoredOAuthTokens(access_token="tok", expires_at=datetime.now(tz=UTC))
    async with _client(_unused) as client:
        with pytest.raises(CredentialError) as err:
            await resolve_credential(
                client,
                provider="anthropic",
                api_key=None,
                base_url=None,
                oauth_tokens_json=stored.model_dump_json(),
            )
    assert err.value.code == "OAUTH_UNSUPPORTED"


def test_a_vertex_endpoint_needs_both_project_and_location() -> None:
    """Half a target would build a URL that 404s at call time instead of at save time."""
    assert vertex_openai_base_url(project="p", location="us-central1") == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1/endpoints/openapi"
    )
    for project, location in (("", "us-central1"), ("p", ""), (" ", " ")):
        with pytest.raises(CredentialError) as err:
            vertex_openai_base_url(project=project, location=location)
        assert err.value.code == "MISSING_VERTEX_TARGET"

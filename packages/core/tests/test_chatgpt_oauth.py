"""Sign in with ChatGPT protocol helper tests.

Every request shape here mirrors the Codex CLI implementation the flow is copied
from, so these assertions are the contract: if the auth service ever moves an
endpoint or swaps a body encoding, these fail rather than a live login silently
breaking. All traffic goes through ``httpx.MockTransport`` — no network.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from suitest_core.chatgpt_oauth import (
    DEFAULT_CLIENT_ID,
    ISSUER,
    ChatGptOAuthError,
    DeviceCode,
    OAuthTokens,
    build_authorize_url,
    callback_redirect_uri,
    device_poll_once,
    device_start,
    exchange_code,
    exchange_for_api_key,
    generate_pkce,
    jwt_claims,
    needs_refresh,
    refresh_tokens,
)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwt(payload: dict[str, object]) -> str:
    """Craft an unsigned JWT — the helpers read claims without verifying."""
    return f"{_b64url(b'{}')}.{_b64url(json.dumps(payload).encode())}.sig"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- PKCE + URL building ----------------------------------------------------


def test_pkce_challenge_is_s256_of_verifier() -> None:
    """The challenge must be the unpadded base64url SHA-256 of the verifier."""
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert "=" not in verifier and "=" not in challenge
    assert challenge == _b64url(hashlib.sha256(verifier.encode()).digest())
    # Fresh randomness per call, or two concurrent logins would collide.
    assert generate_pkce()[0] != verifier


def test_authorize_url_carries_the_expected_query() -> None:
    """Scope and the S256 method are what the client is registered for."""
    url = build_authorize_url(
        redirect_uri="http://localhost:1455/auth/callback",
        code_challenge="chal",
        state="st",
    )
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{ISSUER}/oauth/authorize"
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert query == {
        "response_type": "code",
        "client_id": DEFAULT_CLIENT_ID,
        "redirect_uri": "http://localhost:1455/auth/callback",
        "scope": ("openid profile email offline_access api.connectors.read api.connectors.invoke"),
        "code_challenge": "chal",
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "state": "st",
    }


def test_callback_port_must_be_allow_listed() -> None:
    """Only 1455/1457 exist in the client's redirect-URI allow-list."""
    assert callback_redirect_uri(1455) == "http://localhost:1455/auth/callback"
    assert callback_redirect_uri(1457) == "http://localhost:1457/auth/callback"
    with pytest.raises(ChatGptOAuthError) as exc:
        callback_redirect_uri(8000)
    assert exc.value.code == "PORT_NOT_ALLOWED"


# --- token endpoint ---------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_posts_a_form() -> None:
    """The authorization-code grant is form-encoded, and carries the verifier."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        return httpx.Response(
            200, json={"access_token": "at", "id_token": "it", "refresh_token": "rt"}
        )

    async with _client(handler) as client:
        tokens = await exchange_code(
            client,
            code="the-code",
            redirect_uri="http://localhost:1455/auth/callback",
            code_verifier="ver",
        )

    assert seen["url"] == f"{ISSUER}/oauth/token"
    assert seen["content_type"] == "application/x-www-form-urlencoded"
    assert seen["body"] == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": "http://localhost:1455/auth/callback",
        "client_id": DEFAULT_CLIENT_ID,
        "code_verifier": "ver",
    }
    assert (tokens.access_token, tokens.id_token, tokens.refresh_token) == ("at", "it", "rt")


@pytest.mark.asyncio
async def test_refresh_posts_json_and_tolerates_a_partial_response() -> None:
    """Refresh takes JSON (not a form) and may omit id/refresh tokens."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["content_type"] = request.headers["content-type"]
        return httpx.Response(200, json={"access_token": "fresh"})

    async with _client(handler) as client:
        tokens = await refresh_tokens(client, refresh_token="rt")

    assert seen["content_type"] == "application/json"
    assert seen["body"] == {
        "client_id": DEFAULT_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": "rt",
    }
    assert tokens.access_token == "fresh"
    assert tokens.refresh_token is None


@pytest.mark.asyncio
async def test_api_key_exchange_uses_the_token_exchange_grant() -> None:
    """The id token is traded for a real API key via RFC 8693 token exchange."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return httpx.Response(200, json={"access_token": "sk-live"})

    async with _client(handler) as client:
        key = await exchange_for_api_key(client, id_token="it")

    assert key == "sk-live"
    assert seen["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert seen["requested_token"] == "openai-api-key"
    assert seen["subject_token"] == "it"
    assert seen["subject_token_type"] == "urn:ietf:params:oauth:token-type:id_token"


@pytest.mark.asyncio
async def test_token_endpoint_failures_raise_with_a_code() -> None:
    """A rejected exchange surfaces as a typed error, not a bare HTTP status."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    async with _client(handler) as client:
        with pytest.raises(ChatGptOAuthError) as exc:
            await exchange_code(client, code="c", redirect_uri="r", code_verifier="v")
    assert exc.value.code == "CODE_EXCHANGE_FAILED"


@pytest.mark.asyncio
async def test_missing_access_token_is_an_error() -> None:
    """A 200 with no access token is a failure, not an empty success."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id_token": "it"})

    async with _client(handler) as client:
        with pytest.raises(ChatGptOAuthError):
            await refresh_tokens(client, refresh_token="rt")


# --- device code flow -------------------------------------------------------


@pytest.mark.asyncio
async def test_device_start_parses_the_string_interval_and_code_alias() -> None:
    """``interval`` arrives as a string and ``user_code`` has a legacy spelling."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"device_auth_id": "dev1", "usercode": "ABCD-EFGH", "interval": "7"}
        )

    async with _client(handler) as client:
        device = await device_start(client)

    assert seen["url"] == f"{ISSUER}/api/accounts/deviceauth/usercode"
    assert seen["body"] == {"client_id": DEFAULT_CLIENT_ID}
    assert (device.device_auth_id, device.user_code, device.interval_s) == ("dev1", "ABCD-EFGH", 7)
    assert device.verification_url == f"{ISSUER}/codex/device"


@pytest.mark.asyncio
async def test_device_start_defaults_a_missing_interval() -> None:
    """No interval must not mean a zero-second poll loop."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"device_auth_id": "d", "user_code": "C"})

    async with _client(handler) as client:
        assert (await device_start(client)).interval_s == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_status", [403, 404])
async def test_device_poll_returns_none_while_pending(pending_status: int) -> None:
    """The auth service reports a not-yet-approved code as 403 or 404."""
    device = DeviceCode(device_auth_id="d", user_code="C", interval_s=5)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(pending_status)

    async with _client(handler) as client:
        assert await device_poll_once(client, device=device) is None


@pytest.mark.asyncio
async def test_device_poll_returns_the_service_generated_pkce_pair() -> None:
    """This transport gets its verifier from the service, not from us."""
    device = DeviceCode(device_auth_id="d", user_code="C", interval_s=5)
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "authorization_code": "code1",
                "code_verifier": "ver1",
                "code_challenge": "chal1",
            },
        )

    async with _client(handler) as client:
        result = await device_poll_once(client, device=device)

    assert seen["url"] == f"{ISSUER}/api/accounts/deviceauth/token"
    assert seen["body"] == {"device_auth_id": "d", "user_code": "C"}
    assert result == ("code1", "ver1")


@pytest.mark.asyncio
async def test_device_poll_raises_on_a_hard_failure() -> None:
    """A 500 is not a pending code — stop polling and report it."""
    device = DeviceCode(device_auth_id="d", user_code="C", interval_s=5)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with _client(handler) as client:
        with pytest.raises(ChatGptOAuthError) as exc:
            await device_poll_once(client, device=device)
    assert exc.value.code == "DEVICE_POLL_FAILED"


# --- claims -----------------------------------------------------------------


def test_tokens_expose_expiry_account_and_email_from_claims() -> None:
    """Expiry comes from the access token, identity from the id token."""
    exp = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    tokens = OAuthTokens(
        access_token=_jwt({"exp": int(exp.timestamp())}),
        id_token=_jwt(
            {
                "email": "dev@example.com",
                "https://api.openai.com/auth": {"chatgpt_account_id": "acc_123"},
            }
        ),
    )
    assert tokens.expires_at == exp
    assert tokens.account_id == "acc_123"
    assert tokens.email == "dev@example.com"


def test_claims_of_unparseable_tokens_degrade_to_empty() -> None:
    """A malformed token yields no claims rather than blowing up a request."""
    assert jwt_claims("not-a-jwt") == {}
    assert jwt_claims("a.!!!.c") == {}
    opaque = OAuthTokens(access_token="opaque", id_token="opaque")
    assert opaque.expires_at is None
    assert opaque.account_id is None
    assert opaque.email is None


def test_needs_refresh_uses_a_five_minute_window() -> None:
    """Refresh ahead of expiry, and always when the expiry is unknown."""
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert needs_refresh(None, now=now) is True
    assert needs_refresh(now + timedelta(minutes=4), now=now) is True
    assert needs_refresh(now + timedelta(minutes=6), now=now) is False

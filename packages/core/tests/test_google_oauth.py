"""Tests for the Google installed-app OAuth protocol helpers."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from suitest_core.google_oauth import (
    GoogleOAuthError,
    build_authorize_url,
    exchange_code,
    loopback_redirect_uri,
    parse_callback_url,
    refresh_tokens,
)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_loopback_uri_accepts_any_port_and_uses_the_literal_ip() -> None:
    """A Desktop-app client registers no ports, so an ephemeral one is fine."""
    assert loopback_redirect_uri(1) == "http://127.0.0.1:1"
    assert loopback_redirect_uri(54321) == "http://127.0.0.1:54321"
    with pytest.raises(GoogleOAuthError) as err:
        loopback_redirect_uri(70000)
    assert err.value.code == "BAD_PORT"


def test_authorize_url_forces_a_refresh_token() -> None:
    """Without offline access and a forced prompt, a repeat sign-in gets no refresh token."""
    url = build_authorize_url(
        client_id="cid",
        redirect_uri="http://127.0.0.1:9004",
        code_challenge="chal",
        state="st",
    )
    query = parse_qs(urlparse(url).query)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["chal"]
    assert query["state"] == ["st"]
    assert "cloud-platform" in query["scope"][0]


def test_pasted_callback_url_yields_the_code() -> None:
    """The fallback for a deployment the browser cannot reach on loopback."""
    url = "http://127.0.0.1:9004/?state=st&code=4/abc&scope=openid"
    assert parse_callback_url(url, expected_state="st") == "4/abc"


def test_pasted_callback_url_rejects_a_foreign_or_refused_sign_in() -> None:
    """State guards against CSRF; Google reports refusal in the query, not the status."""
    with pytest.raises(GoogleOAuthError) as mismatch:
        parse_callback_url("http://127.0.0.1:9004/?state=other&code=4/abc", expected_state="st")
    assert mismatch.value.code == "STATE_MISMATCH"

    with pytest.raises(GoogleOAuthError) as denied:
        parse_callback_url(
            "http://127.0.0.1:9004/?state=st&error=access_denied", expected_state="st"
        )
    assert denied.value.code == "CONSENT_DENIED"

    with pytest.raises(GoogleOAuthError) as empty:
        parse_callback_url("http://127.0.0.1:9004/?state=st", expected_state="st")
    assert empty.value.code == "NO_CODE"


@pytest.mark.asyncio
async def test_code_exchange_posts_a_form_and_reads_expires_in() -> None:
    """Google's access token is opaque; the lifetime only arrives as a duration."""
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(parse_qs(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.opaque",
                "refresh_token": "1//refresh",
                "expires_in": 3599,
            },
        )

    async with _client(handler) as client:
        tokens = await exchange_code(
            client,
            client_id="cid",
            client_secret="csec",
            code="4/abc",
            redirect_uri="http://127.0.0.1:9004",
            code_verifier="verifier",
        )

    assert seen["grant_type"] == ["authorization_code"]
    assert seen["code_verifier"] == ["verifier"]
    assert seen["client_secret"] == ["csec"]
    assert tokens.access_token == "ya29.opaque"
    assert tokens.expires_in == 3599
    assert tokens.expires_at is not None


@pytest.mark.asyncio
async def test_refresh_omits_the_secret_when_there_is_none() -> None:
    """A client registered without a secret must not send an empty one."""
    seen: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(parse_qs(request.content.decode()))
        return httpx.Response(200, json={"access_token": "ya29.new", "expires_in": 3599})

    async with _client(handler) as client:
        tokens = await refresh_tokens(client, client_id="cid", refresh_token="1//refresh")

    assert "client_secret" not in seen
    assert seen["grant_type"] == ["refresh_token"]
    # Google does not reissue the refresh token; the caller keeps its own.
    assert tokens.refresh_token is None
    assert tokens.access_token == "ya29.new"


@pytest.mark.asyncio
async def test_a_rejected_refresh_raises() -> None:
    """A revoked grant must surface as a re-authentication, not a silent pass."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    async with _client(handler) as client:
        with pytest.raises(GoogleOAuthError) as err:
            await refresh_tokens(client, client_id="cid", refresh_token="stale")
    assert err.value.code == "REFRESH_FAILED"

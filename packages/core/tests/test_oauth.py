"""Tests for the OAuth primitives every provider shares."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

from suitest_core.oauth import OAuthTokens, generate_pkce, jwt_claims, needs_refresh


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwt(payload: dict[str, object]) -> str:
    """Craft an unsigned JWT — the helpers read claims without verifying."""
    return f"{_b64url(b'{}')}.{_b64url(json.dumps(payload).encode())}.sig"


def test_pkce_challenge_is_s256_of_verifier() -> None:
    """The challenge must be the unpadded base64url SHA-256 of the verifier."""
    verifier, challenge = generate_pkce()
    assert 43 <= len(verifier) <= 128
    assert "=" not in verifier and "=" not in challenge
    assert challenge == _b64url(hashlib.sha256(verifier.encode()).digest())
    # Fresh randomness per call, or two concurrent logins would collide.
    assert generate_pkce()[0] != verifier


def test_claims_of_unparseable_tokens_degrade_to_empty() -> None:
    """A malformed token yields no claims rather than blowing up a request."""
    assert jwt_claims("not-a-jwt") == {}
    assert jwt_claims("a.!!!.c") == {}


def test_needs_refresh_uses_a_five_minute_window() -> None:
    """Refresh ahead of expiry, and always when the expiry is unknown."""
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    assert needs_refresh(None, now=now) is True
    assert needs_refresh(now + timedelta(minutes=4), now=now) is True
    assert needs_refresh(now + timedelta(minutes=6), now=now) is False


def test_expiry_comes_from_the_jwt_exp_claim() -> None:
    """An access token that is a JWT carries its own expiry."""
    exp = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    tokens = OAuthTokens(access_token=_jwt({"exp": int(exp.timestamp())}))
    assert tokens.expires_at == exp


def test_expiry_falls_back_to_expires_in_for_an_opaque_token() -> None:
    """Google's access token is opaque, so its lifetime only arrives as a duration.

    Counted from when the response was parsed, not from when the property is
    read — otherwise every read would push the deadline further out and the
    token would never be considered due for refresh.
    """
    received = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    tokens = OAuthTokens(access_token="ya29.opaque", expires_in=3600, received_at=received)
    assert tokens.expires_at == received + timedelta(seconds=3600)
    # Stable across reads.
    assert tokens.expires_at == tokens.expires_at


def test_an_opaque_token_without_a_lifetime_has_no_expiry() -> None:
    """No ``exp`` claim and no ``expires_in`` means "refresh it", not "never expires"."""
    tokens = OAuthTokens(access_token="opaque", id_token="opaque")
    assert tokens.expires_at is None
    assert needs_refresh(tokens.expires_at) is True
    # The base class knows no account header; only a provider flavour does.
    assert tokens.account_id is None
    assert tokens.email is None


def test_email_comes_from_the_id_token() -> None:
    """The signed-in address is shown back to the admin as a hint."""
    assert OAuthTokens(access_token="o", id_token=_jwt({"email": "dev@example.com"})).email == (
        "dev@example.com"
    )

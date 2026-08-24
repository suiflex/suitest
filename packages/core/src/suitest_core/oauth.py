"""OAuth primitives shared by every provider Suitest can sign in to.

These started out inside ``chatgpt_oauth`` because ChatGPT was the only provider
that had them. They are not ChatGPT-specific: PKCE, JWT claim reading, the
refresh window and the persisted token shape are the same wherever the tokens
came from, and a second provider copying them would be the wrong kind of
duplication.

What stays in a provider's own module is what actually differs: its endpoints,
its client id, its error type, and any claim only it knows how to read.

Expiry is the one subtlety. An OpenAI access token is a JWT carrying ``exp``, so
its expiry is readable from the token itself. A Google access token is opaque
(``ya29.…``) and the expiry only ever arrives as ``expires_in`` alongside it —
which is why :class:`OAuthTokens` snapshots ``received_at`` at parse time rather
than computing a deadline lazily on each read, where every access would push it
further out.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import BaseModel, Field

#: Refresh this far ahead of expiry, matching Codex's window.
REFRESH_WINDOW: Final = timedelta(minutes=5)


class OAuthError(Exception):
    """A step of an OAuth flow failed. ``code`` is the API-facing error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def jwt_claims(token: str) -> dict[str, object]:
    """Base64url-decode a JWT payload without verifying its signature.

    The token always arrives over TLS straight from the token endpoint, so there
    is nothing a local signature check would add — Codex reads claims the same
    way. Returns ``{}`` for anything unparseable, which covers an opaque
    (non-JWT) access token as well.
    """
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload))
    except (binascii.Error, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def needs_refresh(expires_at: datetime | None, *, now: datetime | None = None) -> bool:
    """True when a token is missing an expiry or expires inside the window."""
    if expires_at is None:
        return True
    return expires_at - (now or datetime.now(tz=UTC)) <= REFRESH_WINDOW


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for the S256 method."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class OAuthTokens(BaseModel):
    """Tokens returned by one call to a token endpoint.

    A refresh response may omit fields, so only ``access_token`` is required;
    the caller merges what came back onto what it already stored.
    """

    access_token: str
    id_token: str | None = None
    refresh_token: str | None = None
    #: Lifetime in seconds, for providers whose access token is not a JWT.
    expires_in: int | None = None
    #: When this response was parsed — the baseline ``expires_in`` counts from.
    received_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def expires_at(self) -> datetime | None:
        """Expiry from the access token's ``exp`` claim, else from ``expires_in``."""
        exp = jwt_claims(self.access_token).get("exp")
        if isinstance(exp, int | float) and not isinstance(exp, bool):
            return datetime.fromtimestamp(float(exp), tz=UTC)
        if self.expires_in is not None:
            return self.received_at + timedelta(seconds=self.expires_in)
        return None

    @property
    def account_id(self) -> str | None:
        """Account identifier a backend sends as a header, if it wants one.

        Overridden by the providers that do; ``None`` means the backend
        identifies the account from the bearer token alone.
        """
        return None

    @property
    def email(self) -> str | None:
        """Signed-in account email, shown back to the user as a hint."""
        if self.id_token is None:
            return None
        value = jwt_claims(self.id_token).get("email")
        return value if isinstance(value, str) else None


class StoredOAuthTokens(BaseModel):
    """The token set as persisted (``llm_configs.oauth_tokens_encrypted``).

    Distinct from :class:`OAuthTokens`, which is what a single token-endpoint
    response carries: this is the merged, durable view plus the claims already
    extracted from it, so reading a credential never re-parses a JWT.
    """

    access_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    expires_at: datetime | None = None
    #: Account header value, for backends that need one (e.g. ChatGPT).
    account_id: str | None = None
    #: Signed-in account, shown back to the admin as a hint.
    email: str | None = None

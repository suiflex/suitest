"""Sign in with ChatGPT — OAuth protocol helpers for the OpenAI auth service.

Suitest lets a workspace authenticate its OpenAI LLM config by signing in to
ChatGPT instead of pasting an API key. The flow is not part of the public OpenAI
platform API: it is specified only by the open-source Codex CLI
(``openai/codex``, ``codex-rs/login/src/*``), and every endpoint, body shape and
status code below mirrors that implementation.

Two login transports:

* **device code** — ``device_start`` then poll ``device_poll_once``. No local
  listener and no redirect URI, so it works on localhost and behind a domain
  alike. The auth service generates the PKCE pair, so the caller does not.
* **browser callback** — ``generate_pkce`` + ``build_authorize_url``, with the
  redirect landing on ``http://localhost:<port>/auth/callback``. The port must
  be one of :data:`CALLBACK_PORTS`: the client's redirect-URI allow-list holds
  no other entry, so a normal application callback route cannot be used.

Both end at ``exchange_code``. The resulting credential can be spent two ways:
``exchange_for_api_key`` trades the id token for a real OpenAI API key (billed at
API rates), or the access token is used as a bearer against the ChatGPT backend
(drawing on the user's subscription) — see ``account_id`` on
:class:`OAuthTokens` for the header that pairs with it.

The default client id is Codex's own. It is overridable by the caller so an
operator holding a client of their own can swap it.

This module is pure protocol: no database, no FastAPI, and the caller owns the
``httpx.AsyncClient`` (and therefore timeouts, proxies and test transports).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from urllib.parse import urlencode

from pydantic import BaseModel

if TYPE_CHECKING:
    import httpx

ISSUER: Final = "https://auth.openai.com"
#: Codex CLI's public client id (``codex-rs/login/src/auth/manager.rs``).
DEFAULT_CLIENT_ID: Final = "app_EMoamEEZ73f0CkXaXp7hrann"
#: The only ports in the client's redirect-URI allow-list, primary first.
CALLBACK_PORTS: Final = (1455, 1457)
#: Page where the user enters the device code.
DEVICE_VERIFICATION_URL: Final = f"{ISSUER}/codex/device"

_SCOPE: Final = "openid profile email offline_access api.connectors.read api.connectors.invoke"
_ID_TOKEN_TYPE: Final = "urn:ietf:params:oauth:token-type:id_token"
_TOKEN_EXCHANGE_GRANT: Final = "urn:ietf:params:oauth:grant-type:token-exchange"
_AUTH_CLAIM: Final = "https://api.openai.com/auth"
#: Refresh this far ahead of expiry, matching Codex's window.
REFRESH_WINDOW: Final = timedelta(minutes=5)
#: A device code is valid for 15 minutes.
DEVICE_CODE_TTL: Final = timedelta(minutes=15)

_FORM: Final = {"Content-Type": "application/x-www-form-urlencoded"}
_JSON: Final = {"Content-Type": "application/json"}
# The auth service answers a not-yet-approved device code with 403/404.
_DEVICE_PENDING: Final = frozenset({403, 404})


class ChatGptOAuthError(Exception):
    """A step of the OAuth flow failed. ``code`` is the API-facing error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OAuthTokens(BaseModel):
    """Tokens returned by ``/oauth/token``.

    A refresh response may omit fields, so only ``access_token`` is required;
    the caller merges what came back onto what it already stored.
    """

    access_token: str
    id_token: str | None = None
    refresh_token: str | None = None

    @property
    def expires_at(self) -> datetime | None:
        """Expiry from the access token's ``exp`` claim, or ``None`` if absent."""
        exp = jwt_claims(self.access_token).get("exp")
        if not isinstance(exp, int | float) or isinstance(exp, bool):
            return None
        return datetime.fromtimestamp(float(exp), tz=UTC)

    @property
    def account_id(self) -> str | None:
        """``chatgpt_account_id`` — the ``chatgpt-account-id`` request header."""
        if self.id_token is None:
            return None
        auth = jwt_claims(self.id_token).get(_AUTH_CLAIM)
        if not isinstance(auth, dict):
            return None
        value = auth.get("chatgpt_account_id")
        return value if isinstance(value, str) else None

    @property
    def email(self) -> str | None:
        """Signed-in account email, shown back to the user as a hint."""
        if self.id_token is None:
            return None
        value = jwt_claims(self.id_token).get("email")
        return value if isinstance(value, str) else None


class DeviceCode(BaseModel):
    """A pending device authorization the user has to approve in a browser."""

    device_auth_id: str
    user_code: str
    interval_s: int
    verification_url: str = DEVICE_VERIFICATION_URL


def jwt_claims(token: str) -> dict[str, object]:
    """Base64url-decode a JWT payload without verifying its signature.

    The token always arrives over TLS straight from the token endpoint, so there
    is nothing a local signature check would add — Codex reads claims the same
    way. Returns ``{}`` for anything unparseable.
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


def callback_redirect_uri(port: int) -> str:
    """Redirect URI for the browser flow. Rejects a non-allow-listed port."""
    if port not in CALLBACK_PORTS:
        raise ChatGptOAuthError(
            "PORT_NOT_ALLOWED",
            f"redirect port {port} is not in the client's allow-list {CALLBACK_PORTS}",
        )
    return f"http://localhost:{port}/auth/callback"


def build_authorize_url(
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    issuer: str = ISSUER,
) -> str:
    """Build the ``/oauth/authorize`` URL the user's browser has to open."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": _SCOPE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "state": state,
        }
    )
    return f"{issuer.rstrip('/')}/oauth/authorize?{query}"


async def exchange_code(
    client: httpx.AsyncClient,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    issuer: str = ISSUER,
) -> OAuthTokens:
    """Trade an authorization code for tokens (both transports end here)."""
    response = await client.post(
        f"{issuer.rstrip('/')}/oauth/token",
        headers=_FORM,
        content=urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            }
        ),
    )
    return _tokens_or_raise(response, "CODE_EXCHANGE_FAILED")


async def refresh_tokens(
    client: httpx.AsyncClient,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    refresh_token: str,
    issuer: str = ISSUER,
) -> OAuthTokens:
    """Refresh an expiring access token. This endpoint takes JSON, not a form."""
    response = await client.post(
        f"{issuer.rstrip('/')}/oauth/token",
        headers=_JSON,
        json={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    return _tokens_or_raise(response, "REFRESH_FAILED")


async def exchange_for_api_key(
    client: httpx.AsyncClient,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    id_token: str,
    issuer: str = ISSUER,
) -> str:
    """Trade the id token for a real OpenAI API key (billed at API rates)."""
    response = await client.post(
        f"{issuer.rstrip('/')}/oauth/token",
        headers=_FORM,
        content=urlencode(
            {
                "grant_type": _TOKEN_EXCHANGE_GRANT,
                "client_id": client_id,
                "requested_token": "openai-api-key",
                "subject_token": id_token,
                "subject_token_type": _ID_TOKEN_TYPE,
            }
        ),
    )
    if response.status_code >= 400:
        raise ChatGptOAuthError(
            "API_KEY_EXCHANGE_FAILED",
            f"api key exchange failed with status {response.status_code}",
        )
    key = _body(response).get("access_token")
    if not isinstance(key, str) or not key:
        raise ChatGptOAuthError("API_KEY_EXCHANGE_FAILED", "response carried no api key")
    return key


async def device_start(
    client: httpx.AsyncClient,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    issuer: str = ISSUER,
) -> DeviceCode:
    """Request a device code the user approves at :data:`DEVICE_VERIFICATION_URL`."""
    response = await client.post(
        f"{issuer.rstrip('/')}/api/accounts/deviceauth/usercode",
        headers=_JSON,
        json={"client_id": client_id},
    )
    if response.status_code >= 400:
        raise ChatGptOAuthError(
            "DEVICE_START_FAILED",
            f"device code request failed with status {response.status_code}",
        )
    body = _body(response)
    device_auth_id = body.get("device_auth_id")
    # The service has spelled this key both ways.
    user_code = body.get("user_code") or body.get("usercode")
    if not isinstance(device_auth_id, str) or not isinstance(user_code, str):
        raise ChatGptOAuthError("DEVICE_START_FAILED", "response carried no device code")
    return DeviceCode(
        device_auth_id=device_auth_id,
        user_code=user_code,
        # Arrives as a string; fall back to a polite default when absent.
        interval_s=_as_int(body.get("interval"), default=5),
    )


async def device_poll_once(
    client: httpx.AsyncClient,
    *,
    device: DeviceCode,
    issuer: str = ISSUER,
) -> tuple[str, str] | None:
    """Poll once for approval.

    Returns ``(authorization_code, code_verifier)`` once the user has approved —
    the auth service generates the PKCE pair for this transport — or ``None``
    while the code is still pending. Raises on a hard failure.
    """
    response = await client.post(
        f"{issuer.rstrip('/')}/api/accounts/deviceauth/token",
        headers=_JSON,
        json={"device_auth_id": device.device_auth_id, "user_code": device.user_code},
    )
    if response.status_code in _DEVICE_PENDING:
        return None
    if response.status_code >= 400:
        raise ChatGptOAuthError(
            "DEVICE_POLL_FAILED",
            f"device auth failed with status {response.status_code}",
        )
    body = _body(response)
    code = body.get("authorization_code")
    verifier = body.get("code_verifier")
    if not isinstance(code, str) or not isinstance(verifier, str):
        raise ChatGptOAuthError("DEVICE_POLL_FAILED", "approval carried no authorization code")
    return code, verifier


def device_redirect_uri(issuer: str = ISSUER) -> str:
    """Redirect URI the device-code authorization code was issued against."""
    return f"{issuer.rstrip('/')}/deviceauth/callback"


def _body(response: httpx.Response) -> dict[str, object]:
    try:
        parsed = response.json()
    except ValueError as exc:
        raise ChatGptOAuthError("BAD_RESPONSE", "auth service returned non-JSON") from exc
    return parsed if isinstance(parsed, dict) else {}


def _tokens_or_raise(response: httpx.Response, code: str) -> OAuthTokens:
    if response.status_code >= 400:
        raise ChatGptOAuthError(code, f"auth service returned status {response.status_code}")
    body = _body(response)
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise ChatGptOAuthError(code, "response carried no access token")
    id_token = body.get("id_token")
    refresh = body.get("refresh_token")
    return OAuthTokens(
        access_token=access,
        id_token=id_token if isinstance(id_token, str) else None,
        refresh_token=refresh if isinstance(refresh, str) else None,
    )


def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default

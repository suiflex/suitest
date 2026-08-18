"""Resolve a stored LLM config into the arguments an LLM call needs.

A workspace credential is no longer just a key: a Sign in with ChatGPT config
carries an OAuth token set that expires, and calling the ChatGPT backend needs an
account header the key path knows nothing about. Every caller used to read
``api_key_encrypted`` and dig ``base_url`` out of ``config_json`` itself, which is
fine while there is one credential shape and wrong the moment there are two.

This module is that one place. It stays pure — plain values in, plain values out,
no database — so both the API and the runner can use it without either importing
the other. Refreshing needs the network, so the caller passes the HTTP client and
persists the returned token blob when one comes back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from suitest_core.chatgpt_oauth import (
    DEFAULT_CLIENT_ID,
    StoredOAuthTokens,
    needs_refresh,
    refresh_tokens,
)

if TYPE_CHECKING:
    import httpx

#: Provider key for a config authenticated by Sign in with ChatGPT.
CHATGPT_PROVIDER: Final = "chatgpt"
# The ChatGPT-plan endpoint Codex talks to. Unlike api.openai.com this is not a
# documented API surface; it is where a subscription credential is accepted.
CHATGPT_API_BASE: Final = "https://chatgpt.com/backend-api/codex"
_ACCOUNT_HEADER: Final = "chatgpt-account-id"


class ResolvedCredential(BaseModel):
    """Everything a provider needs, whichever way the workspace authenticated."""

    model_config = ConfigDict(frozen=True)

    provider: str
    api_key: str | None
    base_url: str | None
    extra_headers: dict[str, str] = {}


class CredentialError(Exception):
    """The stored credential cannot be used and re-authentication is required."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def resolve_credential(
    client: httpx.AsyncClient | None,
    *,
    provider: str,
    api_key: str | None,
    base_url: str | None,
    oauth_tokens_json: str | None,
    client_id: str = DEFAULT_CLIENT_ID,
) -> tuple[ResolvedCredential, str | None]:
    """Return the call arguments, plus a token blob to persist (or ``None``).

    A pasted-key config resolves to itself. An OAuth config resolves to its
    access token as the bearer, the ChatGPT backend as the base URL, and the
    account header — refreshing first when the token is at or near expiry, which
    is why ``client`` is required for that path.
    """
    if oauth_tokens_json is None:
        return (
            ResolvedCredential(provider=provider, api_key=api_key, base_url=base_url),
            None,
        )

    stored = StoredOAuthTokens.model_validate_json(oauth_tokens_json)
    persist: str | None = None

    if needs_refresh(stored.expires_at):
        if stored.refresh_token is None:
            raise CredentialError(
                "REFRESH_IMPOSSIBLE",
                "the stored ChatGPT credential has no refresh token; sign in again",
            )
        if client is None:
            raise CredentialError(
                "REFRESH_UNAVAILABLE",
                "the ChatGPT credential needs refreshing but no HTTP client was supplied",
            )
        stored = await refresh_stored(client, stored, client_id=client_id)
        persist = stored.model_dump_json()

    headers = {_ACCOUNT_HEADER: stored.account_id} if stored.account_id else {}
    return (
        ResolvedCredential(
            provider=provider,
            api_key=stored.access_token,
            base_url=base_url or CHATGPT_API_BASE,
            extra_headers=headers,
        ),
        persist,
    )


async def refresh_stored(
    client: httpx.AsyncClient,
    stored: StoredOAuthTokens,
    *,
    client_id: str = DEFAULT_CLIENT_ID,
) -> StoredOAuthTokens:
    """Refresh a token set, keeping whatever the response did not replace."""
    if stored.refresh_token is None:
        raise CredentialError(
            "REFRESH_IMPOSSIBLE", "the stored credential has no refresh token; sign in again"
        )
    fresh = await refresh_tokens(client, client_id=client_id, refresh_token=stored.refresh_token)
    return StoredOAuthTokens(
        access_token=fresh.access_token,
        refresh_token=fresh.refresh_token or stored.refresh_token,
        id_token=fresh.id_token or stored.id_token,
        expires_at=fresh.expires_at,
        account_id=fresh.account_id or stored.account_id,
        email=fresh.email or stored.email,
    )

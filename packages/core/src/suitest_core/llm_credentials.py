"""Resolve a stored LLM config into the arguments an LLM call needs.

A workspace credential is no longer just a key: an OAuth config carries a token
set that expires, and calling the backend behind it needs a base URL — and
sometimes a header — that the key path knows nothing about. Every caller used to
read ``api_key_encrypted`` and dig ``base_url`` out of ``config_json`` itself,
which is fine while there is one credential shape and wrong the moment there are
two.

This module is that one place. It stays pure — plain values in, plain values out,
no database — so both the API and the runner can use it without either importing
the other. Refreshing needs the network, so the caller passes the HTTP client and
persists the returned token blob when one comes back.

Each OAuth-authenticated provider contributes one :class:`OAuthBackend` entry to
:data:`OAUTH_BACKENDS`. Dispatch is by provider key rather than by "does this row
carry tokens", because the second OAuth provider would otherwise be handed the
first one's base URL and header.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol

from pydantic import BaseModel, ConfigDict

from suitest_core.chatgpt_oauth import DEFAULT_CLIENT_ID
from suitest_core.chatgpt_oauth import refresh_tokens as _refresh_chatgpt
from suitest_core.code_assist import CODE_ASSIST_VARIANTS
from suitest_core.google_oauth import DEFAULT_CLIENT_ID as _GOOGLE_CLIENT_ID
from suitest_core.google_oauth import refresh_tokens as _refresh_google
from suitest_core.oauth import OAuthTokens, StoredOAuthTokens, needs_refresh

if TYPE_CHECKING:
    import httpx

#: Provider key for a config authenticated by Sign in with ChatGPT.
CHATGPT_PROVIDER: Final = "chatgpt"
# The ChatGPT-plan endpoint Codex talks to. Unlike api.openai.com this is not a
# documented API surface; it is where a subscription credential is accepted.
CHATGPT_API_BASE: Final = "https://chatgpt.com/backend-api/codex"
_ACCOUNT_HEADER: Final = "chatgpt-account-id"

#: Provider key for Vertex AI reached as the signed-in Google user.
GOOGLE_VERTEX_PROVIDER: Final = "google-vertex"


class RefreshFn(Protocol):
    """Exchange a refresh token for a fresh token set at one auth service."""

    async def __call__(
        self,
        client: httpx.AsyncClient,
        *,
        client_id: str,
        client_secret: str | None = None,
        refresh_token: str,
    ) -> OAuthTokens:
        """Return the refreshed tokens, raising the backend's own error type."""
        ...


@dataclass(frozen=True)
class OAuthBackend:
    """What differs between one OAuth-authenticated provider and the next.

    ``api_base`` is the default only: a config that stores its own ``base_url``
    keeps it, which is how a provider whose endpoint depends on the account
    (a GCP project, say) supplies one per workspace.
    """

    api_base: str | None
    refresh: RefreshFn
    default_client_id: str
    #: Header carrying ``StoredOAuthTokens.account_id``, when the backend wants one.
    account_header: str | None = None
    #: ``User-Agent`` this backend identifies its client with, when it cares.
    user_agent: str | None = None
    #: Fields sent in the request envelope beside the payload.
    envelope_extra: dict[str, str] = field(default_factory=dict)
    #: True when the envelope must name the project stored on the config.
    envelope_needs_project: bool = False


#: Provider key → its OAuth backend. A provider absent here is API-key only.
OAUTH_BACKENDS: Final[dict[str, OAuthBackend]] = {
    CHATGPT_PROVIDER: OAuthBackend(
        api_base=CHATGPT_API_BASE,
        refresh=_refresh_chatgpt,
        default_client_id=DEFAULT_CLIENT_ID,
        account_header=_ACCOUNT_HEADER,
    ),
    GOOGLE_VERTEX_PROVIDER: OAuthBackend(
        # Vertex's endpoint names the caller's project and region, so the URL is
        # per-workspace and stored on the config rather than fixed here.
        api_base=None,
        refresh=_refresh_google,
        default_client_id=_GOOGLE_CLIENT_ID,
    ),
    # Code Assist products are derived rather than repeated: the variant table
    # in ``code_assist`` is already the one place that knows how they differ.
    **{
        key: OAuthBackend(
            api_base=spec.api_endpoint,
            refresh=_refresh_google,
            default_client_id=spec.client_id,
            user_agent=spec.user_agent,
            envelope_extra=dict(spec.envelope_extra),
            envelope_needs_project=True,
        )
        for key, spec in CODE_ASSIST_VARIANTS.items()
    },
}


def vertex_openai_base_url(*, project: str, location: str) -> str:
    """Vertex's OpenAI-compatible endpoint for one project and region.

    Vertex speaks the OpenAI chat-completions protocol at this path, which is
    what lets a Google-authenticated config reuse the OpenAI shim instead of
    needing a provider implementation of its own.
    """
    if not project.strip() or not location.strip():
        raise CredentialError(
            "MISSING_VERTEX_TARGET", "a Vertex endpoint needs both a project and a location"
        )
    host = f"https://{location}-aiplatform.googleapis.com"
    return f"{host}/v1/projects/{project}/locations/{location}/endpoints/openapi"


class ResolvedCredential(BaseModel):
    """Everything a provider needs, whichever way the workspace authenticated."""

    model_config = ConfigDict(frozen=True)

    provider: str
    api_key: str | None
    base_url: str | None
    extra_headers: dict[str, str] = {}
    #: Fields the backend wants in the request body outside the payload itself —
    #: Code Assist wraps a Gemini request in an envelope naming the project. Empty
    #: for every provider that just posts its payload.
    extra_body: dict[str, object] = {}


class CredentialError(Exception):
    """The stored credential cannot be used and re-authentication is required."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def oauth_backend(provider: str) -> OAuthBackend:
    """Return the OAuth backend for ``provider``, or raise if it has none."""
    backend = OAUTH_BACKENDS.get(provider.strip().lower())
    if backend is None:
        raise CredentialError(
            "OAUTH_UNSUPPORTED",
            f"provider {provider!r} has no OAuth backend but the stored config carries tokens",
        )
    return backend


async def resolve_credential(
    client: httpx.AsyncClient | None,
    *,
    provider: str,
    api_key: str | None,
    base_url: str | None,
    oauth_tokens_json: str | None,
    config: dict[str, object] | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> tuple[ResolvedCredential, str | None]:
    """Return the call arguments, plus a token blob to persist (or ``None``).

    A pasted-key config resolves to itself. An OAuth config resolves to its
    access token as the bearer, its backend's endpoint as the base URL, and the
    backend's account header — refreshing first when the token is at or near
    expiry, which is why ``client`` is required for that path.

    ``client_id`` overrides the backend default, for an operator running a
    client registration of their own.
    """
    if oauth_tokens_json is None:
        return (
            ResolvedCredential(provider=provider, api_key=api_key, base_url=base_url),
            None,
        )

    backend = oauth_backend(provider)
    stored = StoredOAuthTokens.model_validate_json(oauth_tokens_json)
    persist: str | None = None

    if needs_refresh(stored.expires_at):
        if stored.refresh_token is None:
            raise CredentialError(
                "REFRESH_IMPOSSIBLE",
                "the stored credential has no refresh token; sign in again",
            )
        if client is None:
            raise CredentialError(
                "REFRESH_UNAVAILABLE",
                "the credential needs refreshing but no HTTP client was supplied",
            )
        stored = await refresh_stored(
            client,
            stored,
            client_id=client_id,
            client_secret=client_secret,
            backend=backend,
        )
        persist = stored.model_dump_json()

    headers: dict[str, str] = {}
    if backend.account_header and stored.account_id:
        headers[backend.account_header] = stored.account_id
    if backend.user_agent:
        headers["User-Agent"] = backend.user_agent

    extra_body: dict[str, object] = dict(backend.envelope_extra)
    if backend.envelope_needs_project:
        project = (config or {}).get("project")
        if not isinstance(project, str) or not project:
            raise CredentialError(
                "MISSING_PROJECT",
                f"provider {provider!r} needs the project its sign-in discovered; sign in again",
            )
        extra_body["project"] = project

    return (
        ResolvedCredential(
            provider=provider,
            api_key=stored.access_token,
            base_url=base_url or backend.api_base,
            extra_headers=headers,
            extra_body=extra_body,
        ),
        persist,
    )


async def refresh_stored(
    client: httpx.AsyncClient,
    stored: StoredOAuthTokens,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    backend: OAuthBackend | None = None,
) -> StoredOAuthTokens:
    """Refresh a token set, keeping whatever the response did not replace."""
    if stored.refresh_token is None:
        raise CredentialError(
            "REFRESH_IMPOSSIBLE", "the stored credential has no refresh token; sign in again"
        )
    backend = backend or OAUTH_BACKENDS[CHATGPT_PROVIDER]
    fresh = await backend.refresh(
        client,
        client_id=client_id or backend.default_client_id,
        client_secret=client_secret,
        refresh_token=stored.refresh_token,
    )
    return StoredOAuthTokens(
        access_token=fresh.access_token,
        refresh_token=fresh.refresh_token or stored.refresh_token,
        id_token=fresh.id_token or stored.id_token,
        expires_at=fresh.expires_at,
        account_id=fresh.account_id or stored.account_id,
        email=fresh.email or stored.email,
    )

"""Sign in with Google — login orchestration for the workspace LLM config.

The same three-step dance as :mod:`suitest_api.services.chatgpt_oauth_service`
— ``start`` hands the browser something to open, ``poll`` waits for approval,
``finish`` stores the result — over a different set of transports, because
Google's flow has no device code.

* ``browser`` — the loopback redirect, on whatever ephemeral port is free. Only
  usable when the person clicking is on the same machine as the API process.
* ``paste`` — the fallback for every other deployment. The browser is sent to
  the same loopback URL, nothing answers it, and the user copies the address bar
  back into Suitest. Google's device flow cannot stand in here: it is allowed
  only for the openid/email/profile, Drive and YouTube scopes, and this sign-in
  needs ``cloud-platform``.

``auto`` picks ``browser`` for a localhost request and ``paste`` otherwise.

A finished sign-in is stored against ``google-vertex``: the tokens authenticate
the caller, and the project and region they name become the endpoint. The
protocol itself lives in :mod:`suitest_core.google_oauth`; this module only
holds the state machine, the persistence and the audit trail.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import httpx
import structlog
from suitest_core.code_assist import (
    CODE_ASSIST_PROVIDER,
    fetch_available_models,
    resolve_account,
    variant,
)
from suitest_core.google_oauth import (
    CLOUD_PLATFORM_SCOPES,
    GoogleOAuthError,
    GoogleProject,
    build_authorize_url,
    exchange_code,
    list_projects,
    loopback_redirect_uri,
    parse_callback_url,
)
from suitest_core.llm_credentials import GOOGLE_VERTEX_PROVIDER, vertex_openai_base_url
from suitest_core.oauth import OAuthTokens, StoredOAuthTokens, generate_pkce
from suitest_db.models.llm_config import AUTH_METHOD_OAUTH

from suitest_api.services.llm_config_service import LLMConfigService
from suitest_api.services.oauth_flows import (
    FLOWS,
    OAuthLoginError,
    PendingFlow,
    bind_loopback_listener,
    drop,
    prune,
    read_callback,
)
from suitest_api.settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.llm_config import LLMConfig

    from suitest_api.deps.scope import TenantContext

log = structlog.get_logger(__name__)

LoginMode = Literal["auto", "browser", "paste"]
#: What a finished Google sign-in is spent on. Both reach Gemini; they differ in
#: who pays and what the user has to supply.
GoogleBackend = Literal["code_assist", "vertex"]

_HTTP_TIMEOUT = 30.0
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})
#: Google redirects to the loopback root, not to a path of our choosing.
_CALLBACK_PATH = "/"


class GoogleLoginError(OAuthLoginError):
    """A login step failed. ``code`` is the API-facing error code."""


@dataclass
class _PendingFlow(PendingFlow):
    """A Google login. ``paste`` mode opens no listener, so it has no port."""

    mode: Literal["browser", "paste"] = "browser"
    #: Which Code Assist product this sign-in was started for, if any. Read back
    #: at ``finish``: the service is rebuilt per request and would not remember.
    variant_key: str | None = None


class GoogleOAuthService:
    """Workspace-scoped Sign in with Google flows."""

    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        variant_key: str | None = None,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._variant_key = variant_key
        if variant_key is None:
            # The deployment's own Google client, used for Vertex and for Code
            # Assist alike — same scopes, so one consent covers both.
            settings = get_settings()
            self._client_id = settings.llm_google_oauth_client_id
            self._client_secret = settings.llm_google_oauth_client_secret or None
            self._scopes: tuple[str, ...] = CLOUD_PLATFORM_SCOPES
        else:
            # Antigravity registers its own client and asks for two scopes the
            # Gemini CLI does not, so it cannot ride on the sign-in above.
            spec = variant(variant_key)
            settings = get_settings()
            # Antigravity ships no client of its own; the operator brings one.
            self._client_id = spec.client_id or settings.llm_antigravity_oauth_client_id
            self._client_secret = (
                spec.client_secret or settings.llm_antigravity_oauth_client_secret or None
            )
            self._scopes = spec.scopes
        # Only the tests pass a transport; production talks to the real issuer.
        self._transport = transport

    # --- start ---------------------------------------------------------------

    async def start(self, *, mode: LoginMode, request_host: str) -> dict[str, object]:
        """Begin a login and return what the UI has to show the user."""
        prune()
        if not self._client_id:
            raise GoogleLoginError(
                "OAUTH_CLIENT_UNSET",
                "no Google OAuth client is configured for this deployment",
            )
        resolved = self._resolve_mode(mode, request_host)
        flow_id = secrets.token_urlsafe(16)
        flow = _PendingFlow(
            workspace_id=self._ctx.workspace_id,
            started_at=datetime.now(tz=UTC),
            mode=resolved,
            variant_key=self._variant_key,
        )

        verifier, challenge = generate_pkce()
        flow.state = secrets.token_urlsafe(16)
        flow.code_verifier = verifier
        if resolved == "browser":
            port = await self._listen_for_callback(flow)
        else:
            # Nothing will answer this, but the redirect URI still has to match
            # the one the code was issued against, so it is fixed and reused.
            port = _PASTE_PORT
        flow.redirect_uri = loopback_redirect_uri(port)
        flow.authorize_url = build_authorize_url(
            client_id=self._client_id,
            redirect_uri=flow.redirect_uri,
            code_challenge=challenge,
            state=flow.state,
            scopes=self._scopes,
        )

        FLOWS[flow_id] = flow
        return self._describe(flow_id, flow)

    def _resolve_mode(self, mode: LoginMode, request_host: str) -> Literal["browser", "paste"]:
        """``auto`` needs the redirect to land on the caller's own machine."""
        if mode != "auto":
            return mode
        host = request_host.split(":", 1)[0].strip().lower()
        return "browser" if host in _LOCAL_HOSTS else "paste"

    async def _listen_for_callback(self, flow: _PendingFlow) -> int:
        """Bind an ephemeral loopback port and stash the code the browser brings.

        Unlike ChatGPT there is no port allow-list to satisfy: a Desktop-app
        client accepts any port on 127.0.0.1, so nothing here can be "in use".
        """

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                response = await read_callback(
                    reader, flow, callback_path=_CALLBACK_PATH, event="google_oauth"
                )
                writer.write(response)
                await writer.drain()
            except Exception:  # pragma: no cover - a dead socket must not kill the flow
                log.warning("google_oauth.callback_handler_failed", exc_info=True)
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

        server, port = await bind_loopback_listener(handle)
        flow.closers.append(server)
        return port

    # --- poll ----------------------------------------------------------------

    async def poll(self, flow_id: str) -> dict[str, object]:
        """Advance the flow one step and report where it stands."""
        flow = self._flow(flow_id)
        if flow.error:
            # The listener has nothing left to catch — free the port now rather
            # than at the sweep, or the next sign-in leaks a socket.
            flow.shutdown()
            return {"status": "error", "message": flow.error}
        if flow.tokens is not None:
            return self._ready(flow)
        if flow.callback_code is None:
            return {"status": "pending"}

        try:
            await self._exchange(flow, flow.callback_code)
        except GoogleOAuthError as exc:
            flow.error = exc.message
            flow.shutdown()
            return {"status": "error", "code": exc.code, "message": exc.message}

        flow.shutdown()
        return self._ready(flow)

    async def submit_callback_url(self, flow_id: str, *, url: str) -> dict[str, object]:
        """Accept the URL the user pasted and exchange the code it carries."""
        flow = self._flow(flow_id)
        if flow.state is None:  # pragma: no cover - set for every flow
            raise GoogleLoginError("UNKNOWN_FLOW", "the sign-in carries no state")
        try:
            code = parse_callback_url(url, expected_state=flow.state)
            await self._exchange(flow, code)
        except GoogleOAuthError as exc:
            flow.error = exc.message
            raise GoogleLoginError(exc.code, exc.message) from exc
        return self._ready(flow)

    async def _exchange(self, flow: _PendingFlow, code: str) -> None:
        if flow.code_verifier is None or flow.redirect_uri is None:  # pragma: no cover
            raise GoogleLoginError("UNKNOWN_FLOW", "the sign-in is missing its PKCE state")
        async with self._http() as client:
            flow.tokens = await exchange_code(
                client,
                client_id=self._client_id,
                client_secret=self._client_secret,
                code=code,
                redirect_uri=flow.redirect_uri,
                code_verifier=flow.code_verifier,
            )

    async def projects(self, flow_id: str) -> list[GoogleProject]:
        """The GCP projects the approved sign-in can see.

        Read mid-flow, from the token the flow is holding: nothing is persisted
        until ``finish``, and the project is one of the things ``finish`` needs.
        """
        flow = self._flow(flow_id)
        if flow.tokens is None:
            raise GoogleLoginError("NOT_APPROVED", "the sign-in has not been approved yet")
        async with self._http() as client:
            return await list_projects(client, access_token=flow.tokens.access_token)

    async def models(self, flow_id: str) -> list[str]:
        """The models the approved account may call, for the model picker.

        Only meaningful for a Code Assist backend; Vertex publishes its catalog
        elsewhere. An unreadable list comes back empty and the UI asks instead.
        """
        tokens = self._approved(flow_id)
        spec = variant(self._flow(flow_id).variant_key or CODE_ASSIST_PROVIDER)
        async with self._http() as client:
            return await fetch_available_models(client, access_token=tokens.access_token, spec=spec)

    # --- finish --------------------------------------------------------------

    async def finish(
        self,
        flow_id: str,
        *,
        model: str,
        backend: GoogleBackend = "vertex",
        variant_key: str | None = None,
        project: str = "",
        location: str = "",
    ) -> LLMConfig:
        """Persist the approved session as the workspace's active LLM config.

        ``code_assist`` asks the user for nothing: the project is discovered
        from the account. ``vertex`` needs the project and region the caller
        collected, because its endpoint is built from them.
        """
        tokens = self._approved(flow_id)

        if backend == "code_assist":
            spec = variant(variant_key or self._flow(flow_id).variant_key or CODE_ASSIST_PROVIDER)
            async with self._http() as client:
                account = await resolve_account(client, access_token=tokens.access_token, spec=spec)
            provider = spec.provider
            config: dict[str, object] = {"project": account.project_id, "tier": account.tier_id}
        else:
            provider = GOOGLE_VERTEX_PROVIDER
            config = {
                "base_url": vertex_openai_base_url(project=project, location=location),
                "gcp_project": project,
                "gcp_location": location,
            }

        service = LLMConfigService(self._session, self._ctx)
        row = await service.set_config(
            provider=provider,
            model=model,
            api_key=None,
            config=config,
            auth_method=AUTH_METHOD_OAUTH,
            oauth_tokens=StoredOAuthTokens(
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                id_token=tokens.id_token,
                expires_at=tokens.expires_at,
                email=tokens.email,
            ),
            audit_action="llm_config.oauth_login",
        )
        self.cancel(flow_id)
        return row

    def _approved(self, flow_id: str) -> OAuthTokens:
        """The token set of an approved flow, or a named refusal."""
        flow = self._flow(flow_id)
        tokens = flow.tokens
        if tokens is None:
            raise GoogleLoginError("NOT_APPROVED", "the sign-in has not been approved yet")
        if tokens.refresh_token is None:
            # Without one the credential dies in an hour with no way back, which
            # would surface as a broken workspace rather than a failed sign-in.
            raise GoogleLoginError(
                "NO_REFRESH_TOKEN",
                "Google returned no refresh token; revoke Suitest's access and sign in again",
            )
        return tokens

    def cancel(self, flow_id: str) -> None:
        """Drop a flow and release its listener. Unknown ids are a no-op."""
        drop(flow_id)

    # --- helpers -------------------------------------------------------------

    def _flow(self, flow_id: str) -> _PendingFlow:
        prune()
        flow = FLOWS.get(flow_id)
        # The store is shared with every other provider's logins, so the type
        # check is what keeps another provider's flow id from landing here.
        if not isinstance(flow, _PendingFlow) or flow.workspace_id != self._ctx.workspace_id:
            raise GoogleLoginError("UNKNOWN_FLOW", "no such sign-in, or it has expired")
        return flow

    def _describe(self, flow_id: str, flow: _PendingFlow) -> dict[str, object]:
        return {
            "flow_id": flow_id,
            "mode": flow.mode,
            "authorize_url": flow.authorize_url,
            "interval_s": 2,
        }

    def _ready(self, flow: _PendingFlow) -> dict[str, object]:
        tokens = flow.tokens
        return {
            "status": "ready",
            "email": tokens.email if tokens else None,
            "has_refresh_token": bool(tokens and tokens.refresh_token),
        }

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=_HTTP_TIMEOUT, transport=self._transport)


#: Fixed redirect port for the paste flow. Nothing binds it — it only has to be
#: the same value at authorize and exchange time.
_PASTE_PORT = 8765

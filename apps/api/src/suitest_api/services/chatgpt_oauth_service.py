"""Sign in with ChatGPT — login orchestration for the workspace LLM config.

Drives the three-step UI dance the protocol needs: ``start`` hands the browser
something to open, ``poll`` waits for the user to approve, and ``finish`` turns
the approved session into a stored :class:`LLMConfig`.

Two transports, picked by ``mode``:

* ``device`` — the user opens a page and types a short code. No listener, no
  redirect URI, so it works whether Suitest runs on a laptop or behind a domain.
* ``browser`` — the classic redirect, which needs a socket on port 1455/1457
  because the OAuth client allow-lists no other redirect URI. Only usable when
  the person clicking is on the same machine as the API process.

``auto`` picks ``browser`` for a localhost request and ``device`` otherwise.

Two ways to spend the approved session, chosen at ``finish``:

* ``api_key`` — trade the id token for a real OpenAI API key and store it like
  any pasted key. Billed at API rates, and needs nothing from the provider layer.
* ``subscription`` — keep the tokens and call the ChatGPT backend, which draws on
  the user's ChatGPT plan.

The protocol itself lives in :mod:`suitest_core.chatgpt_oauth`; this module only
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
from suitest_core.chatgpt_oauth import (
    CALLBACK_PORTS,
    ChatGptOAuthError,
    DeviceCode,
    build_authorize_url,
    callback_redirect_uri,
    device_poll_once,
    device_redirect_uri,
    device_start,
    exchange_code,
    exchange_for_api_key,
)
from suitest_core.llm_credentials import CHATGPT_PROVIDER, refresh_stored
from suitest_core.oauth import OAuthTokens, StoredOAuthTokens, generate_pkce, needs_refresh
from suitest_db.models.llm_config import AUTH_METHOD_API_KEY, AUTH_METHOD_OAUTH
from suitest_db.repositories.llm_configs import LLMConfigRepo, LLMConfigUpdate

from suitest_api.services.llm_config_service import LLMConfigService
from suitest_api.services.oauth_flows import (
    FLOWS as _FLOWS,
)
from suitest_api.services.oauth_flows import (
    OAuthLoginError,
    PendingFlow,
    bind_loopback_listener,
    read_callback,
)
from suitest_api.services.oauth_flows import (
    drop as _drop,
)
from suitest_api.services.oauth_flows import (
    prune as _prune,
)
from suitest_api.settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.llm_config import LLMConfig

    from suitest_api.deps.scope import TenantContext

log = structlog.get_logger(__name__)

LoginMode = Literal["auto", "device", "browser"]
CredentialMode = Literal["api_key", "subscription"]
FlowStatus = Literal["pending", "ready", "error"]

_HTTP_TIMEOUT = 30.0
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})
#: The one path on the callback port that decides a flow's outcome.
_CALLBACK_PATH = "/auth/callback"


class ChatGptLoginError(OAuthLoginError):
    """A login step failed. ``code`` is the API-facing error code."""


@dataclass
class _PendingFlow(PendingFlow):
    """A ChatGPT login — the device transport carries a code the browser one has not."""

    mode: Literal["device", "browser"] = "browser"
    device: DeviceCode | None = None


class ChatGptOAuthService:
    """Workspace-scoped Sign in with ChatGPT flows."""

    def __init__(
        self,
        session: AsyncSession,
        ctx: TenantContext,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._llm = LLMConfigRepo(session)
        self._client_id = get_settings().chatgpt_oauth_client_id
        # Only the tests pass a transport; production talks to the real issuer.
        self._transport = transport

    # --- start ---------------------------------------------------------------

    async def start(self, *, mode: LoginMode, request_host: str) -> dict[str, object]:
        """Begin a login and return what the UI has to show the user."""
        _prune()
        resolved = self._resolve_mode(mode, request_host)
        flow_id = secrets.token_urlsafe(16)
        flow = _PendingFlow(
            workspace_id=self._ctx.workspace_id,
            mode=resolved,
            started_at=datetime.now(tz=UTC),
        )

        if resolved == "device":
            async with self._http() as client:
                flow.device = await device_start(client, client_id=self._client_id)
        else:
            await self._start_browser(flow, flow_id)

        _FLOWS[flow_id] = flow
        return self._describe(flow_id, flow)

    def _resolve_mode(self, mode: LoginMode, request_host: str) -> Literal["device", "browser"]:
        """``auto`` needs the redirect to land on the caller's own machine."""
        if mode != "auto":
            return mode
        host = request_host.split(":", 1)[0].strip().lower()
        return "browser" if host in _LOCAL_HOSTS else "device"

    async def _start_browser(self, flow: _PendingFlow, flow_id: str) -> None:
        """Open the callback listener and build the authorize URL."""
        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(16)
        port = await self._listen_for_callback(flow, flow_id)
        flow.state = state
        flow.code_verifier = verifier
        flow.redirect_uri = callback_redirect_uri(port)
        flow.authorize_url = build_authorize_url(
            client_id=self._client_id,
            redirect_uri=flow.redirect_uri,
            code_challenge=challenge,
            state=state,
        )

    async def _listen_for_callback(self, flow: _PendingFlow, flow_id: str) -> int:
        """Bind the OAuth redirect port and stash the code the browser brings.

        The port cannot be chosen freely: the client's redirect-URI allow-list
        holds only :data:`CALLBACK_PORTS`, so a route on the API's own port is
        not an option and this short-lived socket is.
        """

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                response = await read_callback(
                    reader, flow, callback_path=_CALLBACK_PATH, event="chatgpt_oauth"
                )
                writer.write(response)
                await writer.drain()
            except Exception:  # pragma: no cover - a dead socket must not kill the flow
                log.warning("chatgpt_oauth.callback_handler_failed", exc_info=True)
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

        try:
            server, port = await bind_loopback_listener(handle, ports=CALLBACK_PORTS)
        except OAuthLoginError as exc:
            raise ChatGptLoginError(
                exc.code,
                f"ports {CALLBACK_PORTS} are all in use; sign in with a device code instead",
            ) from exc
        flow.closers.append(server)
        return port

    # --- poll ----------------------------------------------------------------

    async def poll(self, flow_id: str) -> dict[str, object]:
        """Advance the flow one step and report where it stands."""
        flow = self._flow(flow_id)
        if flow.error:
            # The listener has nothing left to catch — free the port now rather
            # than at the 15-minute sweep, or the next sign-in cannot bind it.
            flow.shutdown()
            return {"status": "error", "message": flow.error}
        if flow.tokens is not None:
            return self._ready(flow)

        try:
            if flow.mode == "device":
                await self._poll_device(flow)
            else:
                await self._poll_browser(flow)
        except ChatGptOAuthError as exc:
            flow.error = exc.message
            flow.shutdown()
            return {"status": "error", "code": exc.code, "message": exc.message}

        if flow.tokens is None:
            return {"status": "pending"}
        flow.shutdown()
        return self._ready(flow)

    async def _poll_device(self, flow: _PendingFlow) -> None:
        if flow.device is None:  # pragma: no cover - set for every device flow
            raise ChatGptLoginError("UNKNOWN_FLOW", "the sign-in carries no device code")
        async with self._http() as client:
            approved = await device_poll_once(client, device=flow.device)
            if approved is None:
                return
            code, verifier = approved
            flow.tokens = await exchange_code(
                client,
                client_id=self._client_id,
                code=code,
                redirect_uri=device_redirect_uri(),
                code_verifier=verifier,
            )

    async def _poll_browser(self, flow: _PendingFlow) -> None:
        if flow.callback_code is None or flow.code_verifier is None or flow.redirect_uri is None:
            return
        async with self._http() as client:
            flow.tokens = await exchange_code(
                client,
                client_id=self._client_id,
                code=flow.callback_code,
                redirect_uri=flow.redirect_uri,
                code_verifier=flow.code_verifier,
            )

    # --- finish --------------------------------------------------------------

    async def finish(
        self, flow_id: str, *, credential_mode: CredentialMode, model: str
    ) -> LLMConfig:
        """Persist the approved session as the workspace's active LLM config."""
        flow = self._flow(flow_id)
        tokens = flow.tokens
        if tokens is None:
            raise ChatGptLoginError("NOT_APPROVED", "the sign-in has not been approved yet")

        service = LLMConfigService(self._session, self._ctx)
        if credential_mode == "api_key":
            if tokens.id_token is None:
                raise ChatGptLoginError(
                    "NO_ID_TOKEN", "the sign-in returned no id token to exchange for an api key"
                )
            async with self._http() as client:
                api_key = await exchange_for_api_key(
                    client, client_id=self._client_id, id_token=tokens.id_token
                )
            row = await service.set_config(
                provider="openai",
                model=model,
                api_key=api_key,
                config={},
                auth_method=AUTH_METHOD_API_KEY,
                audit_action="llm_config.oauth_login",
            )
        else:
            row = await service.set_config(
                provider=CHATGPT_PROVIDER,
                model=model,
                api_key=None,
                config={},
                auth_method=AUTH_METHOD_OAUTH,
                oauth_tokens=_stored(tokens),
                audit_action="llm_config.oauth_login",
            )

        self.cancel(flow_id)
        return row

    def cancel(self, flow_id: str) -> None:
        """Drop a flow and release its listener. Unknown ids are a no-op."""
        _drop(flow_id)

    # --- token upkeep --------------------------------------------------------

    async def ensure_fresh(self, config: LLMConfig) -> StoredOAuthTokens | None:
        """Refresh a subscription credential that is at or near expiry.

        Returns the usable token set, or ``None`` for an API-key config. Called
        on the read path rather than from a background job: a workspace whose
        tokens nobody uses has nothing worth refreshing.
        """
        stored = config.oauth_tokens
        if stored is None:
            return None
        if not needs_refresh(stored.expires_at):
            return stored

        async with self._http() as client:
            merged = await refresh_stored(client, stored, client_id=self._client_id)
        await self._llm.update(
            config.id, LLMConfigUpdate(oauth_tokens_encrypted=merged.model_dump_json())
        )
        await self._session.commit()
        return merged

    # --- helpers -------------------------------------------------------------

    def _flow(self, flow_id: str) -> _PendingFlow:
        _prune()
        flow = _FLOWS.get(flow_id)
        # The store is shared with every other provider's logins, so the type
        # check is what keeps another provider's flow id from landing here.
        if not isinstance(flow, _PendingFlow) or flow.workspace_id != self._ctx.workspace_id:
            raise ChatGptLoginError("UNKNOWN_FLOW", "no such sign-in, or it has expired")
        return flow

    def _describe(self, flow_id: str, flow: _PendingFlow) -> dict[str, object]:
        described: dict[str, object] = {"flow_id": flow_id, "mode": flow.mode}
        if flow.device is not None:
            described["verification_url"] = flow.device.verification_url
            described["user_code"] = flow.device.user_code
            described["interval_s"] = flow.device.interval_s
        if flow.authorize_url is not None:
            described["authorize_url"] = flow.authorize_url
            described["interval_s"] = 2
        return described

    def _ready(self, flow: _PendingFlow) -> dict[str, object]:
        tokens = flow.tokens
        account = tokens.email if tokens is not None else None
        return {"status": "ready", "account": account}

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=_HTTP_TIMEOUT, transport=self._transport)


def _stored(tokens: OAuthTokens) -> StoredOAuthTokens:
    return StoredOAuthTokens(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        id_token=tokens.id_token,
        expires_at=tokens.expires_at,
        account_id=tokens.account_id,
        email=tokens.email,
    )

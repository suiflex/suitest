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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlsplit

import httpx
from suitest_core.chatgpt_oauth import (
    CALLBACK_PORTS,
    DEVICE_CODE_TTL,
    ChatGptOAuthError,
    DeviceCode,
    OAuthTokens,
    build_authorize_url,
    callback_redirect_uri,
    device_poll_once,
    device_redirect_uri,
    device_start,
    exchange_code,
    exchange_for_api_key,
    generate_pkce,
    needs_refresh,
    refresh_tokens,
)
from suitest_db.models.llm_config import (
    AUTH_METHOD_API_KEY,
    AUTH_METHOD_OAUTH,
    StoredOAuthTokens,
)
from suitest_db.repositories.llm_configs import LLMConfigRepo, LLMConfigUpdate

from suitest_api.services.llm_config_service import CHATGPT_PROVIDER, LLMConfigService
from suitest_api.settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.llm_config import LLMConfig

    from suitest_api.deps.scope import TenantContext

LoginMode = Literal["auto", "device", "browser"]
CredentialMode = Literal["api_key", "subscription"]
FlowStatus = Literal["pending", "ready", "error"]

_HTTP_TIMEOUT = 30.0
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


class ChatGptLoginError(Exception):
    """A login step failed. ``code`` is the API-facing error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _PendingFlow:
    """One in-flight login. Discarded once finished or expired."""

    workspace_id: str
    mode: Literal["device", "browser"]
    started_at: datetime
    device: DeviceCode | None = None
    state: str | None = None
    code_verifier: str | None = None
    redirect_uri: str | None = None
    authorize_url: str | None = None
    #: Filled by the callback listener (browser) once the redirect lands.
    callback_code: str | None = None
    #: Set once the code has been exchanged; ``finish`` consumes it.
    tokens: OAuthTokens | None = None
    error: str | None = None
    #: Callback listener to shut down when the flow ends (browser mode only).
    closers: list[asyncio.AbstractServer] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        return datetime.now(tz=UTC) - self.started_at > DEVICE_CODE_TTL

    async def close(self) -> None:
        """Tear down a callback listener, if this flow opened one."""
        for server in self.closers:
            server.close()
            with contextlib.suppress(Exception):
                await server.wait_closed()
        self.closers.clear()


# ponytail: module-level store with a TTL sweep. Move to Redis the day the API
# runs more than one worker — a flow started on worker A is invisible to B.
_FLOWS: dict[str, _PendingFlow] = {}


def _prune() -> None:
    for flow_id, flow in list(_FLOWS.items()):
        if flow.expired:
            _FLOWS.pop(flow_id, None)


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

        async def handle(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:  # pragma: no cover - exercised by the live flow
            try:
                request_line = (await reader.readline()).decode("latin-1")
                target = request_line.split(" ")[1] if " " in request_line else ""
                params = parse_qs(urlsplit(target).query)
                code = (params.get("code") or [""])[0]
                state = (params.get("state") or [""])[0]
                if code and state == flow.state:
                    flow.callback_code = code
                else:
                    flow.error = "callback carried no code, or the state did not match"
                writer.write(_CALLBACK_PAGE)
                await writer.drain()
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

        last_error: OSError | None = None
        for port in CALLBACK_PORTS:
            try:
                server = await asyncio.start_server(handle, host="127.0.0.1", port=port)
            except OSError as exc:
                last_error = exc
                continue
            flow.closers.append(server)
            return port
        _FLOWS.pop(flow_id, None)
        raise ChatGptLoginError(
            "CALLBACK_PORT_BUSY",
            f"ports {CALLBACK_PORTS} are all in use; sign in with a device code instead"
            f" ({last_error})",
        )

    # --- poll ----------------------------------------------------------------

    async def poll(self, flow_id: str) -> dict[str, object]:
        """Advance the flow one step and report where it stands."""
        flow = self._flow(flow_id)
        if flow.error:
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
            await flow.close()
            return {"status": "error", "code": exc.code, "message": exc.message}

        if flow.tokens is None:
            return {"status": "pending"}
        await flow.close()
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

        await self.cancel(flow_id)
        return row

    async def cancel(self, flow_id: str) -> None:
        """Drop a flow and release its listener. Unknown ids are a no-op."""
        flow = _FLOWS.pop(flow_id, None)
        if flow is not None:
            await flow.close()

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
        if stored.refresh_token is None:
            raise ChatGptLoginError(
                "REFRESH_IMPOSSIBLE", "the stored credential has no refresh token; sign in again"
            )

        async with self._http() as client:
            fresh = await refresh_tokens(
                client, client_id=self._client_id, refresh_token=stored.refresh_token
            )
        # A refresh response may omit fields; keep what it did not replace.
        merged = StoredOAuthTokens(
            access_token=fresh.access_token,
            refresh_token=fresh.refresh_token or stored.refresh_token,
            id_token=fresh.id_token or stored.id_token,
            expires_at=fresh.expires_at,
            account_id=fresh.account_id or stored.account_id,
            email=fresh.email or stored.email,
        )
        await self._llm.update(
            config.id, LLMConfigUpdate(oauth_tokens_encrypted=merged.model_dump_json())
        )
        await self._session.commit()
        return merged

    # --- helpers -------------------------------------------------------------

    def _flow(self, flow_id: str) -> _PendingFlow:
        _prune()
        flow = _FLOWS.get(flow_id)
        if flow is None or flow.workspace_id != self._ctx.workspace_id:
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


_CALLBACK_PAGE = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"Connection: close\r\n\r\n"
    b"<!doctype html><title>Suitest</title>"
    b"<body style='font:14px system-ui;padding:3rem'>"
    b"<p>Signed in. You can close this tab and return to Suitest.</p>"
)

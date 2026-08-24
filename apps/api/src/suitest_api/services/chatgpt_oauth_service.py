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
import structlog
from suitest_core.chatgpt_oauth import (
    CALLBACK_PORTS,
    DEVICE_CODE_TTL,
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

    def shutdown(self) -> None:
        """Release the callback port, if this flow opened one.

        Synchronous on purpose: ``Server.close()`` already releases the listening
        socket, and every path that ends a flow — including the TTL sweep — has
        to be able to call this. An awaited teardown is what let ports 1455/1457
        stay bound after a failed sign-in, blocking every later one.
        """
        for server in self.closers:
            with contextlib.suppress(Exception):
                server.close()
        self.closers.clear()


# ponytail: module-level store with a TTL sweep. Move to Redis the day the API
# runs more than one worker — a flow started on worker A is invisible to B.
_FLOWS: dict[str, _PendingFlow] = {}


def _drop(flow_id: str) -> None:
    """Forget a flow and release whatever it was holding."""
    flow = _FLOWS.pop(flow_id, None)
    if flow is not None:
        flow.shutdown()


def _prune() -> None:
    for flow_id, flow in list(_FLOWS.items()):
        if flow.expired:
            _drop(flow_id)


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
                response = await self._handle_callback(flow, reader)
                writer.write(response)
                await writer.drain()
            except Exception:  # pragma: no cover - a dead socket must not kill the flow
                log.warning("chatgpt_oauth.callback_handler_failed", exc_info=True)
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
        raise ChatGptLoginError(
            "CALLBACK_PORT_BUSY",
            f"ports {CALLBACK_PORTS} are all in use; sign in with a device code instead"
            f" ({last_error})",
        )

    async def _handle_callback(self, flow: _PendingFlow, reader: asyncio.StreamReader) -> bytes:
        """Interpret one request on the callback port; return the reply to send.

        A browser opens more than one connection to an origin it is visiting —
        speculative preconnects that send nothing, and a ``/favicon.ico`` fetch
        once the reply renders. Only the redirect itself may decide the flow's
        outcome; anything else is answered and ignored, or the sign-in would fail
        milliseconds after it succeeded.
        """
        request_line = (await reader.readline()).decode("latin-1", errors="replace")
        parts = request_line.split(" ")
        if len(parts) < 2:
            # A preconnect that never sent a request line. Nothing to answer.
            return b""

        target = urlsplit(parts[1])
        params = parse_qs(target.query)
        if target.path != _CALLBACK_PATH:
            log.debug("chatgpt_oauth.callback_ignored", path=target.path)
            return _NOT_FOUND_PAGE

        # The redirect is single-use: once it has landed, a repeat (reload, or a
        # second tab) must not overwrite what the first one captured.
        if flow.callback_code is not None or flow.tokens is not None:
            return _SUCCESS_PAGE

        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]
        if not code:
            provider_error = (params.get("error") or [""])[0]
            flow.error = provider_error or "the sign-in was cancelled or returned no code"
            log.info("chatgpt_oauth.callback_without_code", provider_error=provider_error)
            return _FAILURE_PAGE
        if state != flow.state:
            flow.error = "the sign-in could not be matched to this request (state mismatch)"
            log.warning("chatgpt_oauth.callback_state_mismatch")
            return _FAILURE_PAGE

        flow.callback_code = code
        return _SUCCESS_PAGE

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


def _page(status: str, body: str) -> bytes:
    """One-shot HTTP response. The inline icon stops the browser asking for one."""
    html = (
        "<!doctype html><title>Suitest</title>"
        "<link rel='icon' href='data:,'>"
        "<body style='font:14px system-ui;padding:3rem'>"
        f"<p>{body}</p>"
    )
    return (
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(html.encode())}\r\n"
        "Connection: close\r\n\r\n"
        f"{html}"
    ).encode()


_SUCCESS_PAGE = _page("200 OK", "Signed in. You can close this tab and return to Suitest.")
_FAILURE_PAGE = _page("400 Bad Request", "Sign-in failed. Return to Suitest for the details.")
_NOT_FOUND_PAGE = _page("404 Not Found", "Nothing here.")

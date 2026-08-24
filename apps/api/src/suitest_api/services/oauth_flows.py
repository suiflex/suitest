"""In-flight OAuth login state, shared by every provider Suitest signs in to.

The parts of a browser-redirect login that do not depend on which provider is
at the other end: the pending-flow store and its TTL sweep, binding the loopback
listener, and reading the one request on it that decides the outcome.

That last part looks trivial and is not. A browser opens more than one
connection to an origin it is visiting — speculative preconnects that send
nothing, and a ``/favicon.ico`` fetch once the reply renders — and the redirect
must be single-use so a reload cannot overwrite what the first one captured.
Getting it wrong fails a sign-in milliseconds after it succeeded. It is worth
having once rather than once per provider.

What stays in a provider's own service is its state machine: which transports it
offers, how it polls, and what ``finish`` stores.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final
from urllib.parse import parse_qs, urlsplit

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from suitest_core.oauth import OAuthTokens

log = structlog.get_logger(__name__)

#: How long an unfinished login is kept before the sweep discards it.
FLOW_TTL: Final = timedelta(minutes=15)


class OAuthLoginError(Exception):
    """A login step failed. ``code`` is the API-facing error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PendingFlow:
    """One in-flight login. Discarded once finished or expired.

    Providers subclass this to add whatever their own transport needs.
    """

    workspace_id: str
    started_at: datetime
    state: str | None = None
    code_verifier: str | None = None
    redirect_uri: str | None = None
    authorize_url: str | None = None
    #: Filled by the callback listener once the redirect lands.
    callback_code: str | None = None
    #: Set once the code has been exchanged; ``finish`` consumes it.
    tokens: OAuthTokens | None = None
    error: str | None = None
    #: Callback listener to shut down when the flow ends.
    closers: list[asyncio.AbstractServer] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        return datetime.now(tz=UTC) - self.started_at > FLOW_TTL

    def shutdown(self) -> None:
        """Release the callback port, if this flow opened one.

        Synchronous on purpose: ``Server.close()`` already releases the listening
        socket, and every path that ends a flow — including the TTL sweep — has
        to be able to call this. An awaited teardown is what let the callback
        ports stay bound after a failed sign-in, blocking every later one.
        """
        for server in self.closers:
            with contextlib.suppress(Exception):
                server.close()
        self.closers.clear()


# ponytail: module-level store with a TTL sweep. Move to Redis the day the API
# runs more than one worker — a flow started on worker A is invisible to B.
FLOWS: dict[str, PendingFlow] = {}


def drop(flow_id: str) -> None:
    """Forget a flow and release whatever it was holding."""
    flow = FLOWS.pop(flow_id, None)
    if flow is not None:
        flow.shutdown()


def prune() -> None:
    """Discard every flow the user never came back to."""
    for flow_id, flow in list(FLOWS.items()):
        if flow.expired:
            drop(flow_id)


async def bind_loopback_listener(
    handle: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
    *,
    ports: tuple[int, ...] | None = None,
) -> tuple[asyncio.AbstractServer, int]:
    """Bind the OAuth redirect listener on loopback and return it with its port.

    ``ports`` is the client's redirect-URI allow-list, tried in order. Pass
    ``None`` when the provider accepts any loopback port and an ephemeral one
    will do — which is the case for a Google Desktop-app client, and not for
    ChatGPT.
    """
    if ports is None:
        server = await asyncio.start_server(handle, host="127.0.0.1", port=0)
        return server, server.sockets[0].getsockname()[1]

    last_error: OSError | None = None
    for port in ports:
        try:
            server = await asyncio.start_server(handle, host="127.0.0.1", port=port)
        except OSError as exc:
            last_error = exc
            continue
        return server, port
    raise OAuthLoginError(
        "CALLBACK_PORT_BUSY",
        f"ports {ports} are all in use; sign in another way ({last_error})",
    )


async def read_callback(
    reader: asyncio.StreamReader,
    flow: PendingFlow,
    *,
    callback_path: str,
    event: str,
) -> bytes:
    """Interpret one request on the callback port; return the reply to send.

    Only a request to ``callback_path`` may decide the flow's outcome; a
    preconnect or a favicon fetch is answered and ignored. ``event`` prefixes the
    log keys so a provider's sign-ins stay greppable.
    """
    request_line = (await reader.readline()).decode("latin-1", errors="replace")
    parts = request_line.split(" ")
    if len(parts) < 2:
        # A preconnect that never sent a request line. Nothing to answer.
        return b""

    target = urlsplit(parts[1])
    params = parse_qs(target.query)
    if target.path != callback_path:
        log.debug(f"{event}.callback_ignored", path=target.path)
        return NOT_FOUND_PAGE

    # The redirect is single-use: once it has landed, a repeat (reload, or a
    # second tab) must not overwrite what the first one captured.
    if flow.callback_code is not None or flow.tokens is not None:
        return SUCCESS_PAGE

    code = (params.get("code") or [""])[0]
    state = (params.get("state") or [""])[0]
    if not code:
        provider_error = (params.get("error") or [""])[0]
        flow.error = provider_error or "the sign-in was cancelled or returned no code"
        log.info(f"{event}.callback_without_code", provider_error=provider_error)
        return FAILURE_PAGE
    if state != flow.state:
        flow.error = "the sign-in could not be matched to this request (state mismatch)"
        log.warning(f"{event}.callback_state_mismatch")
        return FAILURE_PAGE

    flow.callback_code = code
    return SUCCESS_PAGE


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


SUCCESS_PAGE: Final = _page("200 OK", "Signed in. You can close this tab and return to Suitest.")
FAILURE_PAGE: Final = _page("400 Bad Request", "Sign-in failed. Return to Suitest for the details.")
NOT_FOUND_PAGE: Final = _page("404 Not Found", "Nothing here.")

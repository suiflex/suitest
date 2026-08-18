"""Sign in with ChatGPT flow-state tests.

``start`` and ``poll`` never touch the database, so these run without Postgres:
the session is a stand-in and every auth-service call goes through a mock
transport. Persistence (``finish``, ``ensure_fresh``) is covered by the
DB-backed suite in ``test_llm_config.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services import chatgpt_oauth_service as svc
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_CTX = TenantContext(workspace_id="ws_1", user_id="user_1", role=Role.OWNER)
_OTHER_CTX = TenantContext(workspace_id="ws_2", user_id="user_2", role=Role.OWNER)


@pytest.fixture(autouse=True)
def _clear_flows() -> None:
    """Flows live in a module-level store; keep tests from seeing each other's."""
    svc._FLOWS.clear()


def _service(handler: Callable[[httpx.Request], httpx.Response]) -> svc.ChatGptOAuthService:
    # start/poll never reach the session, so a placeholder is enough here.
    session = cast("AsyncSession", object())
    return svc.ChatGptOAuthService(session, _CTX, transport=httpx.MockTransport(handler))


def _device_started(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"device_auth_id": "dev1", "user_code": "ABCD-EFGH", "interval": "5"}
    )


@pytest.mark.asyncio
async def test_device_start_returns_a_code_for_the_user_to_type() -> None:
    """A remote deployment gets the device flow: a URL plus a short code."""
    service = _service(_device_started)

    started = await service.start(mode="device", request_host="suitest.example.com")

    assert started["mode"] == "device"
    assert started["user_code"] == "ABCD-EFGH"
    assert started["verification_url"] == "https://auth.openai.com/codex/device"
    assert started["interval_s"] == 5
    assert isinstance(started["flow_id"], str)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", "browser"),
        ("127.0.0.1", "browser"),
        ("suitest.example.com", "device"),
        ("192.168.1.20", "device"),
    ],
)
async def test_auto_picks_the_transport_the_host_can_actually_complete(
    host: str, expected: str
) -> None:
    """The browser redirect only lands if the clicker is on the API's machine."""
    service = _service(_device_started)
    started = await service.start(mode="auto", request_host=host)
    assert started["mode"] == expected


@pytest.mark.asyncio
async def test_browser_start_binds_the_allow_listed_port() -> None:
    """The authorize URL must point at a port the OAuth client accepts."""
    service = _service(_device_started)

    started = await service.start(mode="browser", request_host="localhost")

    authorize_url = started["authorize_url"]
    assert isinstance(authorize_url, str)
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A145" in authorize_url
    assert "code_challenge_method=S256" in authorize_url
    service.cancel(cast("str", started["flow_id"]))


@pytest.mark.asyncio
async def test_poll_reports_pending_until_the_user_approves() -> None:
    """A 403 from the device endpoint means "not yet", not a failure."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if path.endswith("/deviceauth/usercode"):
            return _device_started(request)
        if path.endswith("/deviceauth/token"):
            return httpx.Response(403)
        raise AssertionError(f"unexpected call to {path}")

    service = _service(handler)
    started = await service.start(mode="device", request_host="remote.example.com")

    status = await service.poll(cast("str", started["flow_id"]))

    assert status == {"status": "pending"}
    assert calls[-1].endswith("/deviceauth/token")


@pytest.mark.asyncio
async def test_poll_exchanges_the_code_once_approved() -> None:
    """Approval yields a service-generated verifier, which we spend immediately."""
    exchanged: dict[str, str] = {}
    id_token = _jwt_with_email("dev@example.com")

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/deviceauth/usercode"):
            return _device_started(request)
        if path.endswith("/deviceauth/token"):
            return httpx.Response(
                200,
                json={
                    "authorization_code": "code1",
                    "code_verifier": "ver1",
                    "code_challenge": "chal1",
                },
            )
        if path == "/oauth/token":
            body = request.content.decode()
            exchanged["body"] = body
            return httpx.Response(
                200, json={"access_token": "at", "id_token": id_token, "refresh_token": "rt"}
            )
        raise AssertionError(f"unexpected call to {path}")

    service = _service(handler)
    started = await service.start(mode="device", request_host="remote.example.com")

    status = await service.poll(cast("str", started["flow_id"]))

    assert status == {"status": "ready", "account": "dev@example.com"}
    # The device transport's code was issued against the service's own callback.
    assert "code_verifier=ver1" in exchanged["body"]
    assert "deviceauth%2Fcallback" in exchanged["body"]


@pytest.mark.asyncio
async def test_poll_is_idempotent_once_ready() -> None:
    """A second poll must not re-spend a one-time authorization code."""
    token_calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/deviceauth/usercode"):
            return _device_started(request)
        if path.endswith("/deviceauth/token"):
            return httpx.Response(
                200,
                json={"authorization_code": "c", "code_verifier": "v", "code_challenge": "h"},
            )
        token_calls.append(1)
        return httpx.Response(200, json={"access_token": "at", "id_token": "it"})

    service = _service(handler)
    started = await service.start(mode="device", request_host="remote.example.com")
    flow_id = cast("str", started["flow_id"])

    assert (await service.poll(flow_id))["status"] == "ready"
    assert (await service.poll(flow_id))["status"] == "ready"
    assert len(token_calls) == 1


@pytest.mark.asyncio
async def test_poll_surfaces_a_hard_failure_with_its_code() -> None:
    """A 500 stops the flow instead of polling forever."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/deviceauth/usercode"):
            return _device_started(request)
        return httpx.Response(500)

    service = _service(handler)
    started = await service.start(mode="device", request_host="remote.example.com")

    status = await service.poll(cast("str", started["flow_id"]))

    assert status["status"] == "error"
    assert status["code"] == "DEVICE_POLL_FAILED"


@pytest.mark.asyncio
async def test_another_workspace_cannot_poll_someone_elses_flow() -> None:
    """Flow ids are workspace-scoped, not just unguessable."""
    service = _service(_device_started)
    started = await service.start(mode="device", request_host="remote.example.com")

    session = cast("AsyncSession", object())
    intruder = svc.ChatGptOAuthService(
        session, _OTHER_CTX, transport=httpx.MockTransport(_device_started)
    )
    with pytest.raises(svc.ChatGptLoginError) as exc:
        await intruder.poll(cast("str", started["flow_id"]))
    assert exc.value.code == "UNKNOWN_FLOW"


@pytest.mark.asyncio
async def test_an_expired_flow_is_forgotten() -> None:
    """Device codes die after 15 minutes; the stored flow must not outlive them."""
    service = _service(_device_started)
    started = await service.start(mode="device", request_host="remote.example.com")
    flow_id = cast("str", started["flow_id"])
    svc._FLOWS[flow_id].started_at = datetime.now(tz=UTC) - timedelta(minutes=16)

    with pytest.raises(svc.ChatGptLoginError) as exc:
        await service.poll(flow_id)
    assert exc.value.code == "UNKNOWN_FLOW"
    assert flow_id not in svc._FLOWS


# --- browser callback listener ----------------------------------------------
#
# These drive the real socket, because the bug they cover only exists there: a
# browser opens more connections to the callback origin than the redirect itself.


async def _request(port: int, target: str) -> bytes:
    """Send one raw HTTP request line to the callback listener."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {target} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    await writer.drain()
    body = await reader.read()
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return body


async def _preconnect(port: int) -> None:
    """Open and close a connection without sending anything, as browsers do."""
    _, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()


async def _browser_flow() -> tuple[svc.ChatGptOAuthService, str, str, int]:
    """Start a browser-mode flow; return (service, flow_id, state, port).

    The ports are not ours to choose — the OAuth client allow-lists 1455/1457 —
    so a Suitest (or Codex) sign-in running on this machine owns them. Skip
    rather than report a failure that says nothing about the code.
    """
    service = _service(_device_started)
    try:
        started = await service.start(mode="browser", request_host="localhost")
    except svc.ChatGptLoginError as exc:
        if exc.code == "CALLBACK_PORT_BUSY":
            pytest.skip(f"callback ports in use by another process: {exc.message}")
        raise
    flow_id = cast("str", started["flow_id"])
    url = urlparse(cast("str", started["authorize_url"]))
    query = parse_qs(url.query)
    state = query["state"][0]
    port = int(urlparse(query["redirect_uri"][0]).port or 0)
    return service, flow_id, state, port


@pytest.mark.asyncio
async def test_the_redirect_is_captured() -> None:
    """The happy path: the callback's code is what the exchange will spend."""
    service, flow_id, state, port = await _browser_flow()
    try:
        body = await _request(port, f"/auth/callback?code=abc&state={state}")
        assert b"200 OK" in body
        assert svc._FLOWS[flow_id].callback_code == "abc"
    finally:
        service.cancel(flow_id)


@pytest.mark.asyncio
async def test_a_browsers_extra_requests_do_not_undo_a_successful_sign_in() -> None:
    """A preconnect and a favicon fetch must not turn a captured code into an error.

    This is the regression: any second request used to overwrite the outcome, so
    a sign-in failed milliseconds after it had actually worked.
    """
    service, flow_id, state, port = await _browser_flow()
    try:
        await _preconnect(port)
        await _request(port, f"/auth/callback?code=abc&state={state}")
        await _request(port, "/favicon.ico")
        await _preconnect(port)

        flow = svc._FLOWS[flow_id]
        assert flow.callback_code == "abc"
        assert flow.error is None
    finally:
        service.cancel(flow_id)


@pytest.mark.asyncio
async def test_a_repeated_redirect_does_not_replace_the_captured_code() -> None:
    """Reloading the callback tab must not swap in a second, already-spent code."""
    service, flow_id, state, port = await _browser_flow()
    try:
        await _request(port, f"/auth/callback?code=first&state={state}")
        await _request(port, f"/auth/callback?code=second&state={state}")
        assert svc._FLOWS[flow_id].callback_code == "first"
    finally:
        service.cancel(flow_id)


@pytest.mark.asyncio
async def test_a_mismatched_state_is_refused_and_says_so() -> None:
    """A callback we did not start fails the flow, and the tab is told."""
    service, flow_id, _state, port = await _browser_flow()
    try:
        body = await _request(port, "/auth/callback?code=abc&state=not-ours")
        assert b"400 Bad Request" in body
        assert b"Signed in" not in body
        flow = svc._FLOWS[flow_id]
        assert flow.callback_code is None
        assert "state mismatch" in (flow.error or "")
    finally:
        service.cancel(flow_id)


@pytest.mark.asyncio
async def test_a_denied_sign_in_reports_the_providers_reason() -> None:
    """`?error=access_denied` is a real outcome, not a malformed callback."""
    service, flow_id, state, port = await _browser_flow()
    try:
        await _request(port, f"/auth/callback?error=access_denied&state={state}")
        assert svc._FLOWS[flow_id].error == "access_denied"
    finally:
        service.cancel(flow_id)


@pytest.mark.asyncio
async def test_the_callback_port_is_released_when_a_flow_ends() -> None:
    """A failed sign-in must not keep 1455 bound — the next one has to bind it."""
    service, flow_id, _state, port = await _browser_flow()
    await _request(port, "/auth/callback?code=abc&state=wrong")

    status = await service.poll(flow_id)
    assert status["status"] == "error"

    # Binding again is the only proof that matters.
    server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=port)
    server.close()
    service.cancel(flow_id)


@pytest.mark.asyncio
async def test_an_expired_browser_flow_releases_its_port() -> None:
    """The TTL sweep used to drop the flow but leak the socket behind it."""
    service, flow_id, _state, port = await _browser_flow()
    svc._FLOWS[flow_id].started_at = datetime.now(tz=UTC) - timedelta(minutes=16)

    with pytest.raises(svc.ChatGptLoginError):
        await service.poll(flow_id)

    server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=port)
    server.close()


@pytest.mark.asyncio
async def test_finish_before_approval_is_rejected() -> None:
    """Nothing is persisted until the user has actually signed in."""
    service = _service(_device_started)
    started = await service.start(mode="device", request_host="remote.example.com")

    with pytest.raises(svc.ChatGptLoginError) as exc:
        await service.finish(
            cast("str", started["flow_id"]), credential_mode="api_key", model="gpt-4o"
        )
    assert exc.value.code == "NOT_APPROVED"


def _jwt_with_email(email: str) -> str:
    import base64
    import json

    def seg(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{seg(b'{}')}.{seg(json.dumps({'email': email}).encode())}.sig"

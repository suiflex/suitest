"""Sign in with ChatGPT flow-state tests.

``start`` and ``poll`` never touch the database, so these run without Postgres:
the session is a stand-in and every auth-service call goes through a mock
transport. Persistence (``finish``, ``ensure_fresh``) is covered by the
DB-backed suite in ``test_llm_config.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

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
    await service.cancel(cast("str", started["flow_id"]))


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

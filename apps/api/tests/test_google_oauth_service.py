"""Sign in with Google flow-state tests.

``start``, ``poll`` and ``submit_callback_url`` never touch the database, so
these run without Postgres: the session is a stand-in and every token-endpoint
call goes through a mock transport. Persistence (``finish``) is covered by the
DB-backed suite.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services import google_oauth_service as svc
from suitest_api.services import oauth_flows
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_CTX = TenantContext(workspace_id="ws_1", user_id="user_1", role=Role.OWNER)
_OTHER_CTX = TenantContext(workspace_id="ws_2", user_id="user_2", role=Role.OWNER)


@pytest.fixture(autouse=True)
def _clear_flows() -> Iterator[None]:
    """Isolate the shared flow store and release the sockets behind it."""
    _shutdown_all()
    yield
    _shutdown_all()


def _shutdown_all() -> None:
    for flow in list(oauth_flows.FLOWS.values()):
        flow.shutdown()
    oauth_flows.FLOWS.clear()


def _tokens(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"access_token": "ya29.live", "refresh_token": "1//r", "expires_in": 3599},
    )


def _unused(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no HTTP call expected, got {request.url}")


def _service(
    handler: Callable[[httpx.Request], httpx.Response] = _unused,
    *,
    ctx: TenantContext = _CTX,
) -> svc.GoogleOAuthService:
    session = cast("AsyncSession", object())
    return svc.GoogleOAuthService(session, ctx, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_a_localhost_request_gets_a_loopback_listener() -> None:
    """Browser mode binds an ephemeral port and points the redirect at it."""
    started = await _service().start(mode="auto", request_host="localhost:4000")

    assert started["mode"] == "browser"
    flow = oauth_flows.FLOWS[cast("str", started["flow_id"])]
    port = int(urlparse(cast("str", flow.redirect_uri)).port or 0)
    assert port > 0
    # The port is really bound: nothing else may take it while the flow lives.
    with pytest.raises(OSError):
        server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=port)
        server.close()


@pytest.mark.asyncio
async def test_a_remote_request_falls_back_to_paste_and_opens_no_socket() -> None:
    """Google has no device flow for cloud-platform, so paste is the only fallback."""
    started = await _service().start(mode="auto", request_host="suitest.example.com")

    assert started["mode"] == "paste"
    flow = oauth_flows.FLOWS[cast("str", started["flow_id"])]
    assert flow.closers == []


@pytest.mark.asyncio
async def test_the_authorize_url_carries_pkce_and_forces_offline_consent() -> None:
    """Without these Google issues no refresh token to a returning user."""
    started = await _service().start(mode="paste", request_host="suitest.example.com")
    query = parse_qs(urlparse(cast("str", started["authorize_url"])).query)

    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["code_challenge_method"] == ["S256"]
    flow = oauth_flows.FLOWS[cast("str", started["flow_id"])]
    assert query["state"] == [flow.state]
    assert flow.code_verifier is not None


@pytest.mark.asyncio
async def test_a_pasted_url_is_exchanged_for_tokens() -> None:
    """The whole point of paste mode: no listener, still a working sign-in."""
    service = _service(_tokens)
    started = await service.start(mode="paste", request_host="suitest.example.com")
    flow_id = cast("str", started["flow_id"])
    state = oauth_flows.FLOWS[flow_id].state

    ready = await service.submit_callback_url(
        flow_id, url=f"http://127.0.0.1:8765/?state={state}&code=4/abc"
    )

    assert ready["status"] == "ready"
    assert ready["has_refresh_token"] is True


@pytest.mark.asyncio
async def test_a_pasted_url_from_another_sign_in_is_refused() -> None:
    """State is the CSRF guard, and paste mode is where a wrong URL is easiest."""
    service = _service()
    started = await service.start(mode="paste", request_host="suitest.example.com")

    with pytest.raises(svc.GoogleLoginError) as err:
        await service.submit_callback_url(
            cast("str", started["flow_id"]),
            url="http://127.0.0.1:8765/?state=someone-else&code=4/abc",
        )
    assert err.value.code == "STATE_MISMATCH"


@pytest.mark.asyncio
async def test_polling_a_browser_flow_reports_pending_until_the_redirect_lands() -> None:
    """Nothing to exchange yet must not look like a failure."""
    service = _service(_tokens)
    started = await service.start(mode="browser", request_host="localhost:4000")
    flow_id = cast("str", started["flow_id"])

    assert (await service.poll(flow_id))["status"] == "pending"

    # Simulate the browser redirect landing on the listener.
    oauth_flows.FLOWS[flow_id].callback_code = "4/abc"
    ready = await service.poll(flow_id)

    assert ready["status"] == "ready"
    # The listener is released as soon as it has nothing left to catch.
    assert oauth_flows.FLOWS[flow_id].closers == []


@pytest.mark.asyncio
async def test_another_workspaces_flow_id_does_not_resolve() -> None:
    """The flow store is process-wide; the workspace check is what scopes it."""
    started = await _service().start(mode="paste", request_host="suitest.example.com")

    with pytest.raises(svc.GoogleLoginError) as err:
        await _service(ctx=_OTHER_CTX).poll(cast("str", started["flow_id"]))
    assert err.value.code == "UNKNOWN_FLOW"


@pytest.mark.asyncio
async def test_a_chatgpt_flow_id_does_not_resolve_here() -> None:
    """One store, two providers — a flow must only be driven by its own service."""
    from suitest_api.services import chatgpt_oauth_service as chatgpt_svc

    oauth_flows.FLOWS["borrowed"] = chatgpt_svc._PendingFlow(
        workspace_id="ws_1", started_at=datetime.now(tz=UTC)
    )

    with pytest.raises(svc.GoogleLoginError) as err:
        await _service().poll("borrowed")
    assert err.value.code == "UNKNOWN_FLOW"


@pytest.mark.asyncio
async def test_a_cancelled_flow_releases_its_port() -> None:
    """A listener outliving its flow would leak a socket per abandoned sign-in."""
    service = _service()
    started = await service.start(mode="browser", request_host="localhost:4000")
    flow_id = cast("str", started["flow_id"])
    port = int(urlparse(cast("str", oauth_flows.FLOWS[flow_id].redirect_uri)).port or 0)

    service.cancel(flow_id)

    assert flow_id not in oauth_flows.FLOWS
    server = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=port)
    server.close()
    with contextlib.suppress(Exception):
        await server.wait_closed()


@pytest.mark.asyncio
async def test_projects_reads_the_flow_token_before_anything_is_persisted() -> None:
    """The project is one of the things finish needs, so it is picked mid-flow."""
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "cloudresourcemanager" in str(request.url):
            seen_auth.append(request.headers.get("authorization"))
            return httpx.Response(200, json={"projects": [{"projectId": "p-1", "name": "First"}]})
        return _tokens(request)

    service = _service(handler)
    started = await service.start(mode="paste", request_host="suitest.example.com")
    flow_id = cast("str", started["flow_id"])
    state = oauth_flows.FLOWS[flow_id].state
    await service.submit_callback_url(
        flow_id, url=f"http://127.0.0.1:8765/?state={state}&code=4/abc"
    )

    found = await service.projects(flow_id)

    assert [p.project_id for p in found] == ["p-1"]
    assert seen_auth == ["Bearer ya29.live"]


@pytest.mark.asyncio
async def test_projects_before_approval_is_refused() -> None:
    """There is no token to read yet, and saying so beats an empty list."""
    service = _service()
    started = await service.start(mode="paste", request_host="suitest.example.com")

    with pytest.raises(svc.GoogleLoginError) as err:
        await service.projects(cast("str", started["flow_id"]))
    assert err.value.code == "NOT_APPROVED"


@pytest.mark.asyncio
async def test_an_antigravity_sign_in_uses_its_own_client_and_scopes() -> None:
    """It registers separately and asks for two scopes the Gemini CLI does not,
    so it cannot ride on the Google sign-in above it."""
    from urllib.parse import parse_qs

    from suitest_core.code_assist import ANTIGRAVITY_PROVIDER, variant

    session = cast("AsyncSession", object())
    service = svc.GoogleOAuthService(
        session,
        _CTX,
        transport=httpx.MockTransport(_unused),
        variant_key=ANTIGRAVITY_PROVIDER,
    )
    started = await service.start(mode="paste", request_host="suitest.example.com")
    query = parse_qs(urlparse(cast("str", started["authorize_url"])).query)

    spec = variant(ANTIGRAVITY_PROVIDER)
    assert query["client_id"] == [spec.client_id]
    scope = query["scope"][0]
    assert "cclog" in scope
    assert "experimentsandconfigs" in scope

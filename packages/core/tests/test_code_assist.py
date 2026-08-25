"""Code Assist onboarding tests — the path that asks the user for nothing."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from suitest_core.code_assist import (
    ANTIGRAVITY_PROVIDER,
    CODE_ASSIST_PROVIDER,
    CodeAssistError,
    client_metadata,
    fetch_available_models,
    load_code_assist,
    onboard_user,
    resolve_account,
    variant,
)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_the_two_variants_differ_only_where_they_have_to() -> None:
    """One protocol, two products — the table is what keeps it one adapter."""
    cli = variant(CODE_ASSIST_PROVIDER)
    ag = variant(ANTIGRAVITY_PROVIDER)

    # Separate client registrations, and Antigravity asks for two more scopes.
    assert cli.client_id != ag.client_id
    assert set(cli.scopes) < set(ag.scopes)
    assert "cclog" in " ".join(ag.scopes)

    # Different serving hosts; onboarding is shared and so is not in this table.
    assert cli.api_endpoint != ag.api_endpoint

    # Only Antigravity puts extra fields in the request envelope.
    assert cli.envelope_extra == {}
    assert ag.envelope_extra == {"userAgent": "antigravity", "requestType": "agent"}


def test_an_unknown_provider_has_no_variant() -> None:
    with pytest.raises(CodeAssistError) as err:
        variant("not-a-product")
    assert err.value.code == "UNKNOWN_VARIANT"


def test_client_metadata_reports_a_platform_the_endpoint_accepts() -> None:
    """The enum is the vendor's; an unrecognised host reports 0 rather than failing."""
    meta = client_metadata(variant(CODE_ASSIST_PROVIDER))
    assert meta["ideType"] == 9
    assert meta["pluginType"] == 2
    assert meta["platform"] in {0, 1, 2, 3, 4, 5}


@pytest.mark.asyncio
async def test_load_reads_the_existing_project_and_default_tier() -> None:
    """The account already has a project — nothing to ask, nothing to provision."""
    sent: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1internal:loadCodeAssist"
        assert request.headers["authorization"] == "Bearer ya29.live"
        sent.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "cloudaicompanionProject": {"id": "  discovered-project  "},
                "allowedTiers": [
                    {"id": "free-tier", "isDefault": False},
                    {"id": "paid-tier", "isDefault": True},
                ],
            },
        )

    async with _client(handler) as client:
        project, tier = await load_code_assist(
            client, access_token="ya29.live", spec=variant(CODE_ASSIST_PROVIDER)
        )

    assert project == "discovered-project"
    assert tier == "paid-tier"
    assert "metadata" in sent


@pytest.mark.asyncio
async def test_load_accepts_the_project_as_a_bare_string() -> None:
    """The field comes back both ways; either must resolve."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"cloudaicompanionProject": "plain-string-project"})

    async with _client(handler) as client:
        project, tier = await load_code_assist(
            client, access_token="t", spec=variant(CODE_ASSIST_PROVIDER)
        )

    assert project == "plain-string-project"
    assert tier == "legacy-tier"


@pytest.mark.asyncio
async def test_onboarding_polls_until_the_operation_settles() -> None:
    """It is long-running: treating the first reply as final yields no project."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/v1internal:onboardUser"
        if calls < 3:
            return httpx.Response(200, json={"done": False})
        return httpx.Response(
            200,
            json={"done": True, "response": {"cloudaicompanionProject": {"id": "provisioned"}}},
        )

    async with _client(handler) as client:
        project = await onboard_user(
            client, access_token="t", spec=variant(CODE_ASSIST_PROVIDER), sleep_s=0
        )

    assert project == "provisioned"
    assert calls == 3


@pytest.mark.asyncio
async def test_onboarding_that_never_settles_is_an_error_not_an_empty_project() -> None:
    def never(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": False})

    async with _client(never) as client:
        with pytest.raises(CodeAssistError) as err:
            await onboard_user(
                client,
                access_token="t",
                spec=variant(CODE_ASSIST_PROVIDER),
                attempts=2,
                sleep_s=0,
            )
    assert err.value.code == "ONBOARD_TIMEOUT"


@pytest.mark.asyncio
async def test_resolve_provisions_only_when_the_account_has_no_project() -> None:
    """The whole reason this path asks the user nothing."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("loadCodeAssist"):
            return httpx.Response(200, json={"allowedTiers": []})
        return httpx.Response(
            200, json={"done": True, "response": {"cloudaicompanionProject": "fresh"}}
        )

    async with _client(handler) as client:
        account = await resolve_account(
            client, access_token="t", spec=variant(ANTIGRAVITY_PROVIDER), sleep_s=0
        )

    assert account.project_id == "fresh"
    assert paths == ["/v1internal:loadCodeAssist", "/v1internal:onboardUser"]


@pytest.mark.asyncio
async def test_resolve_skips_onboarding_when_a_project_already_exists() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"cloudaicompanionProject": "already-there"})

    async with _client(handler) as client:
        account = await resolve_account(
            client, access_token="t", spec=variant(CODE_ASSIST_PROVIDER), sleep_s=0
        )

    assert account.project_id == "already-there"
    assert paths == ["/v1internal:loadCodeAssist"]


@pytest.mark.asyncio
async def test_a_rejected_load_surfaces_rather_than_returning_no_project() -> None:
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "nope"})

    async with _client(denied) as client:
        with pytest.raises(CodeAssistError) as err:
            await load_code_assist(client, access_token="t", spec=variant(CODE_ASSIST_PROVIDER))
    assert err.value.code == "LOAD_FAILED"


@pytest.mark.asyncio
async def test_model_list_accepts_the_shapes_the_surface_uses() -> None:
    """Undocumented response: entries have been seen keyed several ways."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1internal:fetchAvailableModels"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"modelId": "gemini-2.5-pro"},
                    {"name": "models/gemini-2.5-flash"},
                    "gemini-3-flash",
                    {"modelId": "gemini-2.5-pro"},
                    {"unexpected": "shape"},
                    42,
                ]
            },
        )

    async with _client(handler) as client:
        models = await fetch_available_models(
            client, access_token="t", spec=variant(CODE_ASSIST_PROVIDER)
        )

    # Qualified ids are unqualified, repeats collapse, order is kept, and an
    # entry we cannot read is skipped rather than guessed at.
    assert models == ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-3-flash"]


@pytest.mark.asyncio
async def test_model_list_degrades_to_empty() -> None:
    """The sign-in already succeeded; an unreadable list must not undo it."""

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such method")

    async with _client(denied) as client:
        assert (
            await fetch_available_models(
                client, access_token="t", spec=variant(CODE_ASSIST_PROVIDER)
            )
            == []
        )

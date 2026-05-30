"""Tests for :class:`~suitest_api.integrations.slack_adapter.SlackAdapter` (M1d-15).

Coverage:

* :meth:`test_connection` posts a "Suitest connection test" message → 200
  returns ``ConnectionTestResult(ok=True)``.
* :meth:`send_notification` renders a Block Kit payload that includes the
  defect public id + severity emoji + back-link, and wraps it in an
  attachment whose color matches the severity.
* HTTP error translation: 200 → success, non-200 → AdapterRemoteError,
  timeout → AdapterTimeoutError.
* Severity color matrix — every Severity maps to the canonical hex.
* Webhook URL resolution: missing secret / bad JSON / missing key all
  surface as ``AdapterRemoteError`` (caught by the ARQ job's retry policy).
* Module-level registration: SlackAdapter satisfies the NotifierAdapter
  Protocol and the lifespan registers it under ``IntegrationKind.SLACK``.

We exercise the adapter directly (no FastAPI app) so the tests stay fast
and don't need a Postgres testcontainer; the adapter's only collaborator is
the injected ``httpx.AsyncClient`` which we drive with ``respx``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from suitest_api.integrations.base import (
    AdapterRemoteError,
    AdapterTimeoutError,
    ConnectionTestResult,
    DefectEvent,
    NotificationResult,
    NotifierAdapter,
)
from suitest_api.integrations.notifier_registry import (
    NotifierFactoryRegistry,
    notifier_factory_registry,
)
from suitest_api.integrations.slack_adapter import (
    DEFAULT_WEBHOOK_TIMEOUT_SECONDS,
    SEVERITY_COLOR,
    SlackAdapter,
    build_defect_blocks,
)
from suitest_db.models.integration import Integration
from suitest_shared.domain.enums import DiagnosisKind, IntegrationKind, Severity

_WEBHOOK_URL = "https://hooks.slack.com/services/T00000/B00000/XXXXXXXXXXXX"


def _make_integration(secrets_json: str | None = None) -> Integration:
    """Build an in-memory Integration row with the given secrets blob.

    The adapter never touches the DB; we set ``secrets_encrypted`` directly to
    the JSON plaintext (which is what the ``EncryptedBytes`` column type
    would return after the per-load decrypt) so we don't need a real
    ``SUITEST_ENCRYPTION_KEY`` for these tests.
    """
    integration = Integration(
        id="int_slack_1",
        workspace_id="ws_1",
        kind=IntegrationKind.SLACK,
        name="Slack Webhook",
        config={"suitest_base_url": "https://suitest.example.com"},
        secrets_encrypted=(
            secrets_json if secrets_json is not None else json.dumps({"webhook_url": _WEBHOOK_URL})
        ),
        status="active",
    )
    return integration


def _make_event(
    *,
    severity: Severity = Severity.HIGH,
    diagnosis: DiagnosisKind = DiagnosisKind.REGRESSION,
    run_id: str | None = "run_42",
    test_case: str | None = "TC-7",
) -> DefectEvent:
    return DefectEvent(
        defect_id="defc_1",
        defect_public_id="DEF-42",
        title="Login form rejects valid credentials",
        severity=severity,
        diagnosis_kind=diagnosis,
        workspace_id="ws_1",
        run_id=run_id,
        test_case_public_id=test_case,
        suitest_base_url=None,
    )


# ---------------------------------------------------------------------------
# Protocol membership + registry wiring
# ---------------------------------------------------------------------------


def test_slack_adapter_satisfies_notifier_protocol() -> None:
    """``@runtime_checkable`` Protocol membership keeps registry isinstance happy."""
    integration = _make_integration()
    # Build the client without awaiting it — we never issue a request, so a
    # raw construction is enough to satisfy the Protocol membership check.
    client = httpx.AsyncClient()
    adapter = SlackAdapter(integration, client)
    assert isinstance(adapter, NotifierAdapter)
    assert adapter.kind is IntegrationKind.SLACK


def test_notifier_factory_registry_round_trip() -> None:
    """Register + retrieve + invoke factory yields a configured SlackAdapter."""
    registry = NotifierFactoryRegistry()
    registry.register(IntegrationKind.SLACK, SlackAdapter)

    factory = registry.get(IntegrationKind.SLACK)
    integration = _make_integration()
    client = httpx.AsyncClient()
    adapter = factory(integration, client)
    assert isinstance(adapter, SlackAdapter)
    assert adapter.integration is integration


def test_module_singleton_has_slack_after_lifespan() -> None:
    """After the API lifespan runs once, the module-singleton has SLACK registered.

    Smoke-tests that :mod:`suitest_api.main` actually wires the factory rather
    than just importing it.
    """
    # Importing :mod:`suitest_api.main` doesn't run the lifespan automatically,
    # but the lifespan code path is the only thing that registers Slack. Run a
    # tiny lifespan to confirm.
    import asyncio

    from asgi_lifespan import LifespanManager
    from suitest_api.main import create_app

    async def _go() -> None:
        app = create_app()
        async with LifespanManager(app):
            assert IntegrationKind.SLACK in notifier_factory_registry
            assert IntegrationKind.SLACK in app.state.notifier_factory_registry

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# Block Kit payload shape
# ---------------------------------------------------------------------------


def test_build_defect_blocks_header_carries_severity_emoji_and_public_id() -> None:
    event = _make_event(severity=Severity.CRITICAL)
    blocks = build_defect_blocks(event, suitest_base_url="https://app.example")

    assert blocks[0]["type"] == "header"
    header_text = blocks[0]["text"]["text"]
    # Critical severity uses the fire emoji per SEVERITY_EMOJI.
    assert ":fire:" in header_text
    assert "[DEF-42]" in header_text
    assert "Login form" in header_text


def test_build_defect_blocks_section_fields_include_severity_and_diagnosis() -> None:
    event = _make_event(severity=Severity.HIGH, diagnosis=DiagnosisKind.FLAKE)
    blocks = build_defect_blocks(event, suitest_base_url="https://app.example")

    section = next(b for b in blocks if b["type"] == "section")
    field_texts = [f["text"] for f in section["fields"]]
    assert any("Severity" in t and "HIGH" in t for t in field_texts)
    assert any("Diagnosis" in t and "Flaky" in t for t in field_texts)
    # Test case public id surfaces too.
    assert any("Test case" in t and "TC-7" in t for t in field_texts)
    # Run link surfaces when both run_id and base_url present.
    assert any("Run" in t and "run_42" in t for t in field_texts)


def test_build_defect_blocks_no_run_link_when_base_url_missing() -> None:
    event = _make_event(run_id="run_42")
    blocks = build_defect_blocks(event, suitest_base_url=None)

    section = next(b for b in blocks if b["type"] == "section")
    field_texts = [f["text"] for f in section["fields"]]
    assert not any("Run" in t for t in field_texts)


def test_build_defect_blocks_context_block_links_to_defect_page() -> None:
    event = _make_event()
    blocks = build_defect_blocks(event, suitest_base_url="https://app.example/")
    context = next(b for b in blocks if b["type"] == "context")
    rendered = context["elements"][0]["text"]
    # Trailing slash trimmed, defect page deep-linked.
    assert "https://app.example/defects/DEF-42" in rendered
    assert "View defect DEF-42" in rendered


# ---------------------------------------------------------------------------
# Severity color matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "expected"),
    [
        (Severity.LOW, "#9CA3AF"),
        (Severity.MEDIUM, "#FBBF24"),
        (Severity.HIGH, "#F87171"),
        (Severity.CRITICAL, "#DC2626"),
    ],
)
def test_severity_color_matrix(severity: Severity, expected: str) -> None:
    assert SEVERITY_COLOR[severity] == expected


# ---------------------------------------------------------------------------
# test_connection happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_connection_posts_blocks_to_webhook_url_and_returns_ok() -> None:
    integration = _make_integration()

    async with httpx.AsyncClient() as client:
        adapter = SlackAdapter(integration, client)
        with respx.mock(assert_all_called=True) as router:
            route = router.post(_WEBHOOK_URL).respond(200, text="ok")
            result = await adapter.test_connection()

        assert isinstance(result, ConnectionTestResult)
        assert result.ok is True
        assert result.error is None
        # Exactly one POST.
        assert route.call_count == 1
        # Body carries a "Suitest connection test" message.
        body = json.loads(route.calls[0].request.content)
        assert "blocks" in body
        first_block_text = body["blocks"][0]["text"]["text"]
        assert "Suitest connection test" in first_block_text


@pytest.mark.asyncio
async def test_test_connection_returns_error_on_non_200() -> None:
    integration = _make_integration()

    async with httpx.AsyncClient() as client:
        adapter = SlackAdapter(integration, client)
        with respx.mock() as router:
            router.post(_WEBHOOK_URL).respond(404, text="channel_not_found")
            result = await adapter.test_connection()

        assert result.ok is False
        assert result.error is not None
        assert "channel_not_found" in result.error


@pytest.mark.asyncio
async def test_test_connection_returns_error_when_secrets_missing() -> None:
    # No secret blob at all.
    integration = _make_integration(secrets_json="")

    async with httpx.AsyncClient() as client:
        adapter = SlackAdapter(integration, client)
        result = await adapter.test_connection()

    assert result.ok is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# send_notification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_notification_posts_attachment_with_severity_color() -> None:
    integration = _make_integration()
    event = _make_event(severity=Severity.CRITICAL)

    async with httpx.AsyncClient() as client:
        adapter = SlackAdapter(integration, client)
        with respx.mock(assert_all_called=True) as router:
            route = router.post(_WEBHOOK_URL).respond(200, text="ok")
            result = await adapter.send_notification(
                event,
                config={"suitest_base_url": "https://app.example"},
                secrets={"webhook_url": _WEBHOOK_URL},
            )

        assert isinstance(result, NotificationResult)
        assert result.sent is True
        body = json.loads(route.calls[0].request.content)
        # Attachment-wrapped (because color is set).
        assert "attachments" in body
        attachment = body["attachments"][0]
        assert attachment["color"] == "#DC2626"  # CRITICAL
        # Blocks survived the wrap.
        assert any(b["type"] == "header" for b in attachment["blocks"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("severity", "expected_color"),
    [
        (Severity.LOW, "#9CA3AF"),
        (Severity.MEDIUM, "#FBBF24"),
        (Severity.HIGH, "#F87171"),
        (Severity.CRITICAL, "#DC2626"),
    ],
)
async def test_send_notification_severity_color_round_trip(
    severity: Severity, expected_color: str
) -> None:
    integration = _make_integration()
    event = _make_event(severity=severity)

    async with httpx.AsyncClient() as client:
        adapter = SlackAdapter(integration, client)
        with respx.mock() as router:
            route = router.post(_WEBHOOK_URL).respond(200, text="ok")
            await adapter.send_notification(
                event,
                config={},
                secrets={"webhook_url": _WEBHOOK_URL},
            )
        body = json.loads(route.calls[0].request.content)
        assert body["attachments"][0]["color"] == expected_color


@pytest.mark.asyncio
async def test_send_notification_non_200_raises_remote_error() -> None:
    integration = _make_integration()
    event = _make_event()

    async with httpx.AsyncClient() as client:
        adapter = SlackAdapter(integration, client)
        with respx.mock() as router:
            router.post(_WEBHOOK_URL).respond(429, text="rate_limited")
            with pytest.raises(AdapterRemoteError) as excinfo:
                await adapter.send_notification(
                    event,
                    config={},
                    secrets={"webhook_url": _WEBHOOK_URL},
                )
        assert "429" in str(excinfo.value)


@pytest.mark.asyncio
async def test_send_notification_timeout_raises_timeout_error() -> None:
    integration = _make_integration()
    event = _make_event()

    async with httpx.AsyncClient() as client:
        adapter = SlackAdapter(integration, client)
        with respx.mock() as router:
            router.post(_WEBHOOK_URL).mock(side_effect=httpx.ReadTimeout("slow"))
            with pytest.raises(AdapterTimeoutError):
                await adapter.send_notification(
                    event,
                    config={},
                    secrets={"webhook_url": _WEBHOOK_URL},
                )


@pytest.mark.asyncio
async def test_send_notification_missing_webhook_url_in_secrets_raises() -> None:
    integration = _make_integration()
    event = _make_event()

    async with httpx.AsyncClient() as client:
        adapter = SlackAdapter(integration, client)
        with pytest.raises(AdapterRemoteError):
            await adapter.send_notification(event, config={}, secrets={})


@pytest.mark.asyncio
async def test_send_notification_request_uses_default_timeout() -> None:
    """Smoke: the POST is invoked with the documented 10s timeout."""
    integration = _make_integration()
    event = _make_event()
    captured: dict[str, Any] = {}

    class _CapturingClient:
        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            timeout: float,  # noqa: ASYNC109 — httpx kwarg name, not a cancellation budget
        ) -> httpx.Response:
            captured["url"] = url
            captured["timeout"] = timeout
            captured["json"] = json
            return httpx.Response(200, text="ok")

    adapter = SlackAdapter(integration, _CapturingClient())  # type: ignore[arg-type]
    await adapter.send_notification(
        event,
        config={},
        secrets={"webhook_url": _WEBHOOK_URL},
    )
    assert captured["url"] == _WEBHOOK_URL
    assert captured["timeout"] == DEFAULT_WEBHOOK_TIMEOUT_SECONDS

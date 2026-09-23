"""Unit tests for headed browser launcher module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from suitest_agent.generators.browser_launcher import (
    close_headed_browser,
    has_active_headed_browser,
    is_display_available,
    launch_headed_browser,
)


def test_is_display_available_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """On darwin or win32 without CI, display is available."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SUITEST_FORCE_HEADED", raising=False)
    monkeypatch.setattr("sys.platform", "darwin")
    assert is_display_available() is True


def test_is_display_available_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """When CI is true and SUITEST_FORCE_HEADED is not set, display is not available."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("SUITEST_FORCE_HEADED", raising=False)
    assert is_display_available() is False

    # But if forced, it returns True (or checks display)
    monkeypatch.setenv("SUITEST_FORCE_HEADED", "true")
    monkeypatch.setattr("sys.platform", "darwin")
    assert is_display_available() is True


def test_is_display_available_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux, depends on DISPLAY or WAYLAND_DISPLAY env vars."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("sys.platform", "linux")

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert is_display_available() is False

    monkeypatch.setenv("DISPLAY", ":0")
    assert is_display_available() is True

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert is_display_available() is True


@pytest.mark.asyncio
async def test_launch_and_close_headed_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """launch_headed_browser creates background task and close_headed_browser terminates it."""
    monkeypatch.setattr(
        "suitest_agent.generators.browser_launcher.is_display_available", lambda: True
    )

    session_id = "rec_test_lifecycle_123"

    # Mock the browser loop so Playwright isn't actually spawned in this unit test
    async def _mock_loop(
        sess_id: str, *args: object, close_event: asyncio.Event, **kwargs: object
    ) -> None:
        await close_event.wait()

    with patch(
        "suitest_agent.generators.browser_launcher._run_headed_browser_loop", side_effect=_mock_loop
    ):
        launched = await launch_headed_browser(
            session_id=session_id,
            start_url="https://app.example.com",
            api_url="http://localhost:8000/api/v1",
            workspace_id="ws_test",
        )
        assert launched is True
        assert has_active_headed_browser(session_id) is True

        # Close browser
        await close_headed_browser(session_id)
        assert has_active_headed_browser(session_id) is False


@pytest.mark.asyncio
async def test_launch_skipped_when_no_display(monkeypatch: pytest.MonkeyPatch) -> None:
    """When display is not available, launch_headed_browser returns False immediately."""
    monkeypatch.setattr(
        "suitest_agent.generators.browser_launcher.is_display_available", lambda: False
    )
    launched = await launch_headed_browser(
        session_id="rec_no_display",
        start_url="https://app.example.com",
        api_url="http://localhost:8000/api/v1",
    )
    assert launched is False
    assert has_active_headed_browser("rec_no_display") is False


@pytest.mark.asyncio
async def test_native_event_bridge_callback() -> None:
    """_run_headed_browser_loop exposes __suitest_native_post_event__ and forwards to on_event."""
    import json
    from unittest.mock import AsyncMock, MagicMock, patch

    from suitest_agent.generators.browser_launcher import _run_headed_browser_loop

    received_events: list[dict[str, Any]] = []

    async def _on_event(evt: dict[str, Any]) -> None:
        received_events.append(evt)

    close_event = asyncio.Event()
    exposed_callbacks: dict[str, Any] = {}

    mock_context = AsyncMock()
    mock_context.pages = []
    mock_context.on = MagicMock()

    def _expose(name: str, fn: Any) -> None:
        exposed_callbacks[name] = fn

    mock_context.expose_function.side_effect = _expose

    mock_page = AsyncMock()
    mock_page.on = MagicMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = AsyncMock()
    mock_browser.on = MagicMock()
    mock_browser.new_context.return_value = mock_context

    mock_p = AsyncMock()
    mock_p.chromium.launch.return_value = mock_browser

    with patch("playwright.async_api.async_playwright") as mock_ap:
        mock_cm = AsyncMock()
        mock_cm.start = AsyncMock(return_value=mock_p)
        mock_cm.__aexit__ = AsyncMock()
        mock_ap.return_value = mock_cm

        task = asyncio.create_task(
            _run_headed_browser_loop(
                session_id="rec_native_test",
                start_url="https://example.com",
                api_url="http://localhost:8000/api/v1",
                workspace_id="ws_native",
                agent_script="",
                close_event=close_event,
                on_event=_on_event,
            )
        )

        for _ in range(50):
            if "__suitest_native_post_event__" in exposed_callbacks:
                break
            await asyncio.sleep(0.01)

        assert "__suitest_native_post_event__" in exposed_callbacks
        bridge_fn = exposed_callbacks["__suitest_native_post_event__"]

        # Call with json string
        res = await bridge_fn(json.dumps({"kind": "click", "selector": "#test-btn"}))
        assert res == {"ok": True}

        # Call with dict
        res2 = await bridge_fn({"kind": "type", "selector": "#input-txt", "text": "hello"})
        assert res2 == {"ok": True}

        close_event.set()
        await task

    assert len(received_events) == 2
    assert received_events[0] == {"kind": "click", "selector": "#test-btn"}
    assert received_events[1] == {"kind": "type", "selector": "#input-txt", "text": "hello"}

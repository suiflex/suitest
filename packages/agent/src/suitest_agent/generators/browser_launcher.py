"""Headed Playwright browser launcher for live recording sessions.

Spawns a native Chromium/Chrome browser window directly on the desktop
(bypassing reverse-proxy limitations, CORS, and CSP), and injects the
Suitest recorder agent script into every frame/tab via CDP.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def is_display_available() -> bool:
    """Return True if a graphical desktop environment is available."""
    if os.environ.get("CI") == "true" and os.environ.get("SUITEST_FORCE_HEADED") != "true":
        return False
    if sys.platform == "darwin" or sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@dataclass
class HeadedSessionHandle:
    session_id: str
    task: asyncio.Task[None]
    close_event: asyncio.Event


_ACTIVE_HEADED_SESSIONS: dict[str, HeadedSessionHandle] = {}


def _resolve_agent_script() -> str:
    """Locate recorder_agent.js in apps/web/public or fallback."""
    candidates = [
        Path(__file__).resolve().parents[5] / "apps" / "web" / "public" / "recorder_agent.js",
        Path.cwd() / "apps" / "web" / "public" / "recorder_agent.js",
    ]
    for p in candidates:
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return "// Suitest recorder agent"


async def _run_headed_browser_loop(
    session_id: str,
    start_url: str,
    api_url: str,
    workspace_id: str,
    agent_script: str,
    close_event: asyncio.Event,
    on_event: Any = None,
) -> None:
    """Manage the Playwright headed browser lifecycle until close_event is set."""
    from playwright.async_api import async_playwright

    bootstrap_js = f"""
    window.__SUITEST_SESSION_ID__ = "{session_id}";
    window.__SUITEST_WORKSPACE_ID__ = "{workspace_id}";
    window.__SUITEST_API_URL__ = "{api_url}";
    window.__SUITEST_HEADED_MODE__ = true;
    """

    browser = None
    playwright_cm = None
    try:
        playwright_cm = async_playwright()
        p = await playwright_cm.start()

        launch_kwargs: dict[str, Any] = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--no-first-run",
                "--disable-web-security",
                "--allow-running-insecure-content",
                "--disable-features=IsolateOrigins,site-per-process,BlockInsecurePrivateNetworkRequests",
            ],
        }

        # Try system Google Chrome first (fastest, user familiar), fallback to Playwright Chromium
        try:
            browser = await p.chromium.launch(channel="chrome", **launch_kwargs)
        except Exception as chrome_err:
            log.debug(
                "Could not launch system Chrome, falling back to bundled Chromium: %s", chrome_err
            )
            browser = await p.chromium.launch(**launch_kwargs)

        context = await browser.new_context(viewport={"width": 1280, "height": 850})

        # Expose direct CDP native bridge for event streaming (bypasses CORS/CSP/Mixed Content)
        async def _native_on_event(raw_data: Any) -> dict[str, Any]:
            try:
                import json

                import httpx

                if isinstance(raw_data, str):
                    evt = json.loads(raw_data)
                elif isinstance(raw_data, dict):
                    evt = raw_data
                else:
                    return {"ok": False, "error": "invalid payload"}

                if on_event is not None:
                    res = on_event(evt)
                    if asyncio.iscoroutine(res):
                        await res
                    return {"ok": True}

                async with httpx.AsyncClient(timeout=10.0) as client:
                    headers = {"Content-Type": "application/json"}
                    if workspace_id:
                        headers["X-Workspace-Id"] = workspace_id
                    target_url = (
                        f"{api_url.rstrip('/')}/generators/recorder/sessions/{session_id}/events"
                    )
                    params = {"workspaceId": workspace_id} if workspace_id else {}
                    res = await client.post(target_url, json=evt, headers=headers, params=params)
                    if res.is_success:
                        payload = res.json()
                        return payload if isinstance(payload, dict) else {"ok": True}
                    log.warning("Native event forward returned %s: %s", res.status_code, res.text)
                    return {"ok": False, "status": res.status_code}
            except Exception as exc:
                log.error("Failed to forward native recorder event: %s", exc, exc_info=True)
                return {"ok": False, "error": str(exc)}

        await context.expose_function("__suitest_native_post_event__", _native_on_event)

        # Inject bootstrap and recorder agent into all documents/frames
        await context.add_init_script(bootstrap_js)
        await context.add_init_script(agent_script)

        page = await context.new_page()

        # Handle user manually closing the browser window (only when all tabs are closed)
        def _on_page_close(_p: object) -> None:
            open_pages = [p for p in context.pages if not p.is_closed()]
            if not open_pages and not close_event.is_set():
                close_event.set()

        def _on_browser_disconnected(_b: object) -> None:
            if not close_event.is_set():
                close_event.set()

        def _on_new_page(new_p: Any) -> None:
            new_p.on("close", _on_page_close)

        page.on("close", _on_page_close)
        context.on("page", _on_new_page)
        browser.on("disconnected", _on_browser_disconnected)

        try:
            await page.goto(start_url, timeout=45000)
        except Exception as nav_err:
            log.warning(
                "Headed browser initial navigation to %s encountered error: %s", start_url, nav_err
            )

        # Wait until finalize / cancel / close event is signaled
        await close_event.wait()
    except asyncio.CancelledError:
        log.info("Headed browser task for session %s cancelled", session_id)
    except Exception as exc:
        log.error("Headed browser session %s error: %s", session_id, exc, exc_info=True)
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        if playwright_cm is not None:
            with contextlib.suppress(Exception):
                await playwright_cm.__aexit__(None, None, None)
        _ACTIVE_HEADED_SESSIONS.pop(session_id, None)
        log.info("Headed browser session %s cleanly terminated", session_id)


async def launch_headed_browser(
    session_id: str,
    start_url: str,
    api_url: str,
    workspace_id: str = "",
    agent_script: str | None = None,
    on_event: Any = None,
) -> bool:
    """Launch a headed browser for the session in a background task.

    Returns True if successfully spawned, False if display is unavailable.
    """
    if not is_display_available():
        log.info("Display is not available; headed browser launch skipped")
        return False

    # Close any pre-existing instance for this session
    await close_headed_browser(session_id)

    script = agent_script or _resolve_agent_script()
    close_event = asyncio.Event()

    task = asyncio.create_task(
        _run_headed_browser_loop(
            session_id=session_id,
            start_url=start_url,
            api_url=api_url,
            workspace_id=workspace_id,
            agent_script=script,
            close_event=close_event,
            on_event=on_event,
        ),
        name=f"headed_browser:{session_id}",
    )

    _ACTIVE_HEADED_SESSIONS[session_id] = HeadedSessionHandle(
        session_id=session_id,
        task=task,
        close_event=close_event,
    )
    return True


async def close_headed_browser(session_id: str) -> None:
    """Signal close and wait briefly for the headed browser to terminate."""
    handle = _ACTIVE_HEADED_SESSIONS.get(session_id)
    if handle is None:
        return

    handle.close_event.set()
    try:
        await asyncio.wait_for(asyncio.shield(handle.task), timeout=5.0)
    except (TimeoutError, asyncio.CancelledError, Exception) as exc:
        log.debug("Headed browser close wait exception (tolerated): %s", exc)
        handle.task.cancel()
    finally:
        _ACTIVE_HEADED_SESSIONS.pop(session_id, None)


def has_active_headed_browser(session_id: str) -> bool:
    """Check if session currently has a running headed browser."""
    handle = _ACTIVE_HEADED_SESSIONS.get(session_id)
    return handle is not None and not handle.close_event.is_set() and not handle.task.done()

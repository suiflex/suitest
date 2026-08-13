"""Frontend execution runtime — Suitest owns the browser, not the user.

Like TestSprite (which bundles its own browser-driving agent), Suitest ships the
Playwright runtime and auto-provisions BOTH the Playwright package and the
Chromium binary on first use. The person testing their app only runs their app —
they never ``pip install playwright`` or ``playwright install`` themselves.

``ensure_browser`` is idempotent and fast when everything is already cached: it
installs the ``playwright`` package into the running interpreter (or its venv)
when missing, then provisions Chromium. It degrades to a clear, actionable
message instead of letting a raw ``ModuleNotFoundError`` crash the tool.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

from suitest_lifecycle import pydeps


@dataclass(frozen=True)
class BrowserStatus:
    ready: bool
    detail: str


def _playwright_importable() -> bool:
    return pydeps.importable("playwright.async_api")


def _install_playwright_package(timeout_sec: int) -> BrowserStatus:
    status = pydeps.install("playwright", "playwright.async_api", timeout_sec)
    return BrowserStatus(status.ready, status.detail)


def _chromium_present() -> bool:
    """True if the Chromium binary is installed (cheap, no browser launch)."""
    from importlib.util import find_spec

    if find_spec("playwright") is None:
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
        import os

        return bool(path) and os.path.exists(path)
    except Exception:
        return False


def _install_chromium(timeout_sec: int) -> BrowserStatus:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return BrowserStatus(False, f"playwright install chromium failed: {exc}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return BrowserStatus(False, "playwright install chromium failed: " + " | ".join(tail))
    return BrowserStatus(True, "chromium installed on demand")


def ensure_browser(*, auto_install: bool = True, timeout_sec: int = 600) -> BrowserStatus:
    """Ensure the Playwright package + Chromium are usable in this interpreter.

    Idempotent: no-op fast path when both are already present. Installs whatever
    is missing when ``auto_install`` is set; otherwise reports what's missing.
    """
    if not _playwright_importable():
        if not auto_install:
            return BrowserStatus(
                False,
                "playwright package not installed and auto-install disabled "
                f"(run: {sys.executable} -m pip install playwright)",
            )
        status = _install_playwright_package(timeout_sec)
        if not status.ready:
            return status
    if _chromium_present():
        return BrowserStatus(True, "ready")
    if not auto_install:
        return BrowserStatus(False, "chromium not installed (auto-install disabled)")
    return _install_chromium(timeout_sec)


__all__ = ["BrowserStatus", "ensure_browser"]

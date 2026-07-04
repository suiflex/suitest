"""Frontend execution runtime — Suitest owns the browser, not the user.

Like TestSprite (which bundles its own browser-driving agent), Suitest ships the
Playwright runtime and auto-provisions the Chromium binary on first use. The
person testing their app only runs their app — they never `pip install playwright`
or `playwright install` themselves.

``ensure_browser`` is idempotent and fast when the browser is already cached.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserStatus:
    ready: bool
    detail: str


def _playwright_importable() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


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


def ensure_browser(*, auto_install: bool = True, timeout_sec: int = 600) -> BrowserStatus:
    """Ensure Playwright + Chromium are usable; install the browser if missing."""
    if not _playwright_importable():
        return BrowserStatus(
            False,
            "playwright not installed in the Suitest environment "
            "(install the 'frontend' extra: pip install 'suiflex-suitest-lifecycle[frontend]')",
        )
    if _chromium_present():
        return BrowserStatus(True, "chromium already installed")
    if not auto_install:
        return BrowserStatus(False, "chromium not installed (auto-install disabled)")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return BrowserStatus(False, f"playwright install failed: {exc}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return BrowserStatus(False, "playwright install chromium failed: " + " | ".join(tail))
    return BrowserStatus(True, "chromium installed on demand")


__all__ = ["BrowserStatus", "ensure_browser"]

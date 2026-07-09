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

import contextlib
import importlib
import site
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


def _pip_install_variants(pkg: str) -> list[list[str]]:
    """pip argv variants to try in order, adapting to the interpreter.

    - Inside a venv (``sys.prefix != sys.base_prefix``): install into the venv
      site — no ``--user`` (disallowed in venvs), no PEP-668 marker to fight.
    - System/Homebrew/distro interpreter: prefer ``--user`` (contained to the
      user site, importable by this interpreter AND the subprocesses that run
      the generated tests), with a ``--break-system-packages`` fallback for
      PEP-668 "externally-managed" environments (Homebrew, Debian).
    """
    base = [sys.executable, "-m", "pip", "install", "--upgrade", pkg]
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        return [base]
    return [[*base, "--user"], [*base, "--user", "--break-system-packages"]]


def _ensure_pip() -> None:
    """Best-effort: bootstrap pip via ensurepip when the interpreter lacks it
    (minimal venvs / stripped pythons ship without pip)."""
    try:
        import pip  # noqa: F401

        return
    except ImportError:
        pass
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            capture_output=True,
            text=True,
            timeout=180,
        )


def _make_importable_in_process() -> None:
    """Surface a just-installed package to the RUNNING interpreter without a
    restart. A server started before the user-site dir existed never got it on
    ``sys.path`` (``site`` only adds user-site at startup, and only if it
    exists) — add it now and drop import caches."""
    usersite = site.getusersitepackages()
    if isinstance(usersite, str):
        site.addsitedir(usersite)
    importlib.invalidate_caches()


def _install_playwright_package(timeout_sec: int) -> BrowserStatus:
    _ensure_pip()
    detail = "pip unavailable"
    for argv in _pip_install_variants("playwright"):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_sec)
        except (subprocess.TimeoutExpired, OSError) as exc:
            detail = str(exc)
            continue
        if proc.returncode == 0:
            _make_importable_in_process()
            if _playwright_importable():
                return BrowserStatus(True, "playwright package installed on demand")
            detail = "pip reported success but playwright is still not importable"
            continue
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        detail = " | ".join(tail) if tail else f"pip exited {proc.returncode}"
    return BrowserStatus(
        False,
        "could not auto-install the playwright package "
        f"(interpreter: {sys.executable}): {detail}. "
        "Install it manually: "
        f"'{sys.executable} -m pip install playwright'",
    )


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

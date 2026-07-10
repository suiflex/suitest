"""Unit tests for on-demand Playwright provisioning + the browser-tool guard.

Hermetic: no real pip, no browser. We assert the argv-selection logic (the
money path: venv vs system, PEP-668 fallback) and that a browser tool degrades
to a clean envelope instead of crashing when provisioning fails.
"""

from __future__ import annotations

import suitest_lifecycle.frontend_runtime as fr
from suitest_lifecycle.blackbox import mcp as bbmcp
from suitest_lifecycle.frontend_runtime import BrowserStatus


def test_pip_variants_in_venv_installs_into_venv(monkeypatch) -> None:
    # venv => prefix differs from base_prefix; no --user, no PEP-668 fight.
    monkeypatch.setattr(fr.sys, "prefix", "/tmp/venv")
    monkeypatch.setattr(fr.sys, "base_prefix", "/usr")
    variants = fr._pip_install_variants("playwright")
    assert len(variants) == 1
    assert "--user" not in variants[0]
    assert "--break-system-packages" not in variants[0]
    assert variants[0][-1] == "playwright"


def test_pip_variants_system_has_user_then_break_system(monkeypatch) -> None:
    # Non-venv => --user first, then --break-system-packages for PEP-668.
    monkeypatch.setattr(fr.sys, "prefix", "/usr")
    monkeypatch.setattr(fr.sys, "base_prefix", "/usr")
    variants = fr._pip_install_variants("playwright")
    assert len(variants) == 2
    assert "--user" in variants[0] and "--break-system-packages" not in variants[0]
    assert "--user" in variants[1] and "--break-system-packages" in variants[1]


def test_ensure_browser_no_autoinstall_reports_missing(monkeypatch) -> None:
    monkeypatch.setattr(fr, "_playwright_importable", lambda: False)
    status = fr.ensure_browser(auto_install=False)
    assert status.ready is False
    assert "playwright" in status.detail.lower()


def test_browser_tool_degrades_gracefully(monkeypatch) -> None:
    # The core regression: a browser tool must NOT raise ModuleNotFoundError.
    # When provisioning fails it returns success=False with the reason.
    monkeypatch.setattr(
        bbmcp, "ensure_browser", lambda **_: BrowserStatus(False, "no pip, offline")
    )
    guarded = bbmcp.BLACKBOX_TOOLS["blackbox_discover_app"]
    out = guarded(url="https://example.test")
    assert out["success"] is False
    assert "browser runtime unavailable" in out["summary"]
    assert out["errors"] == ["no pip, offline"]


def test_nonbrowser_tool_is_not_gated() -> None:
    # summarize reads saved JSON only — it must not be wrapped by the guard.
    assert (
        bbmcp.BLACKBOX_TOOLS["blackbox_summarize_findings"]
        is (bbmcp._RAW_BLACKBOX_TOOLS["blackbox_summarize_findings"])
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))

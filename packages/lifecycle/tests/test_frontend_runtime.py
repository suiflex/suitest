"""Unit tests for on-demand Playwright provisioning + the browser-tool guard.

Hermetic: no real pip, no browser. The pip argv-selection logic itself lives in
``pydeps`` and is covered by ``test_pydeps.py``; here we assert that a browser
tool degrades to a clean envelope instead of crashing when provisioning fails.
"""

from __future__ import annotations

import suitest_lifecycle.frontend_runtime as fr
from suitest_lifecycle.blackbox import mcp as bbmcp
from suitest_lifecycle.frontend_runtime import BrowserStatus


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

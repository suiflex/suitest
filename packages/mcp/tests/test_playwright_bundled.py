"""Unit tests for :mod:`suitest_mcp.bundled.playwright` (M1c Task 7).

These tests cover the metadata layer only — they never spawn ``npx``. A single
integration roundtrip is gated behind the ``PLAYWRIGHT_MCP_REAL=1`` env var
and is skipped by default so CI does not require Node + network egress.
"""

from __future__ import annotations

import os

import pytest
from suitest_mcp.bundled.playwright import (
    DECLARED_TOOLS,
    PLAYWRIGHT_COMMAND,
    PLAYWRIGHT_SPEC,
    bootstrap_playwright_provider,
)
from suitest_mcp.models import McpProviderConfig, McpToolSchema, McpTransport

EXPECTED_TOOL_NAMES: set[str] = {
    "browser.navigate",
    "browser.click",
    "browser.type",
    "browser.screenshot",
    "browser.evaluate",
    "browser.wait_for",
    "browser.get_dom",
    "browser.start_recording",
    "browser.stop_recording",
    "browser.network_logs",
}


def test_playwright_command_is_npx_invocation() -> None:
    """``-y`` must come before the package or npx will prompt and deadlock."""
    assert PLAYWRIGHT_COMMAND[0] == "npx"
    assert "-y" in PLAYWRIGHT_COMMAND
    assert PLAYWRIGHT_COMMAND.index("-y") < PLAYWRIGHT_COMMAND.index("@playwright/mcp@latest")
    assert PLAYWRIGHT_COMMAND[-1] == "@playwright/mcp@latest"


def test_playwright_spec_basic_fields() -> None:
    assert isinstance(PLAYWRIGHT_SPEC, McpProviderConfig)
    assert PLAYWRIGHT_SPEC.name == "playwright-mcp"
    assert PLAYWRIGHT_SPEC.kind == "playwright-mcp"
    assert PLAYWRIGHT_SPEC.transport is McpTransport.STDIO
    assert PLAYWRIGHT_SPEC.command == PLAYWRIGHT_COMMAND
    assert PLAYWRIGHT_SPEC.id.startswith("builtin:")
    assert PLAYWRIGHT_SPEC.workspace_id == "_builtin_"


def test_playwright_spec_env_is_empty() -> None:
    """Empty env keeps Playwright's browser auto-detect path; no secret leak."""
    assert PLAYWRIGHT_SPEC.env == {}


def test_playwright_spec_default_routing_fe_web() -> None:
    assert PLAYWRIGHT_SPEC.is_default_for_target.get("FE_WEB") is True


def test_playwright_spec_pool_tuning() -> None:
    assert PLAYWRIGHT_SPEC.max_sessions == 2
    assert PLAYWRIGHT_SPEC.spawn_timeout_seconds == pytest.approx(30.0)


def test_playwright_spec_config_json_carries_catalog() -> None:
    cfg = PLAYWRIGHT_SPEC.config_json
    assert cfg.get("version_pin") == "@playwright/mcp@latest"
    declared = cfg.get("declared_tools")
    assert isinstance(declared, list)
    assert set(declared) == EXPECTED_TOOL_NAMES


def test_declared_tools_catalog() -> None:
    assert len(DECLARED_TOOLS) == len(EXPECTED_TOOL_NAMES)
    names = {t.name for t in DECLARED_TOOLS}
    assert names == EXPECTED_TOOL_NAMES
    for tool in DECLARED_TOOLS:
        assert isinstance(tool, McpToolSchema)
        assert tool.description != ""


def test_bootstrap_playwright_provider_rebinds_workspace() -> None:
    cfg = bootstrap_playwright_provider("ws-acme")
    assert isinstance(cfg, McpProviderConfig)
    assert cfg.workspace_id == "ws-acme"
    assert cfg.id == "builtin:playwright-mcp:ws-acme"
    # Other fields must be a clean clone of the template.
    assert cfg.name == PLAYWRIGHT_SPEC.name
    assert cfg.kind == PLAYWRIGHT_SPEC.kind
    assert cfg.transport is McpTransport.STDIO
    assert cfg.command == PLAYWRIGHT_COMMAND
    assert cfg.is_default_for_target == PLAYWRIGHT_SPEC.is_default_for_target
    assert cfg.max_sessions == PLAYWRIGHT_SPEC.max_sessions


def test_bootstrap_does_not_mutate_template() -> None:
    """``model_copy`` must produce a fresh config; template stays canonical."""
    original_workspace = PLAYWRIGHT_SPEC.workspace_id
    original_id = PLAYWRIGHT_SPEC.id
    _ = bootstrap_playwright_provider("ws-1")
    _ = bootstrap_playwright_provider("ws-2")
    assert PLAYWRIGHT_SPEC.workspace_id == original_workspace
    assert PLAYWRIGHT_SPEC.id == original_id


def test_bootstrap_rejects_blank_workspace() -> None:
    """``McpProviderConfig`` enforces ``min_length=1`` on ``workspace_id``."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        bootstrap_playwright_provider("")


# ---------------------------------------------------------------------------
# Integration smoke: real npx subprocess. Skipped unless PLAYWRIGHT_MCP_REAL=1.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("PLAYWRIGHT_MCP_REAL"),
    reason="set PLAYWRIGHT_MCP_REAL=1 to exercise real npx subprocess",
)
async def test_playwright_real_subprocess_lists_tools() -> None:
    """Spawn the real ``npx @playwright/mcp@latest`` and list its tools.

    Requires Node + network egress for the first ``npx`` install. We do not
    drive an actual browser here — just open the session and confirm the
    server advertises at least one ``browser.*`` tool, which is enough to
    prove the stdio wire is up.
    """
    from suitest_mcp.client import open_session

    cfg = bootstrap_playwright_provider("ws-integration")
    sess = await open_session(cfg)
    try:
        tools = await sess.list_tools()
    finally:
        await sess.cleanup()
    advertised = {t["name"] for t in tools}
    assert any(name.startswith("browser") for name in advertised), advertised

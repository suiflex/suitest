"""Registry + routing tests.

Pure-routing tests use ``McpRegistry.register_builtin(...)`` so they avoid the
DB. The DB-backed test exercises ``load_for_workspace`` end-to-end and lives
in the db-tests harness via the ``session`` fixture from ``packages/db/tests``.
"""

from __future__ import annotations

import pytest
from suitest_mcp.errors import McpProviderUnavailable
from suitest_mcp.models import McpProviderConfig, McpTransport
from suitest_mcp.registry import McpRegistry
from suitest_mcp.routing import resolve_provider
from suitest_shared.domain.enums import TargetKind


def _registry_with_builtins(workspace_id: str = "ws-1") -> McpRegistry:
    reg = McpRegistry()
    reg.register_builtin(workspace_id)
    return reg


def test_registry_register_builtin_seeds_three_providers() -> None:
    reg = _registry_with_builtins()
    providers = {p.name for p in reg.list_for_workspace("ws-1")}
    assert providers == {"api-http-mcp", "playwright-mcp", "postgres-mcp"}


def test_registry_get_reattributes_workspace_id() -> None:
    reg = _registry_with_builtins("ws-42")
    spec = reg.get("ws-42", "playwright-mcp")
    assert spec.workspace_id == "ws-42"
    assert spec.transport is McpTransport.STDIO


def test_registry_get_missing_raises() -> None:
    reg = _registry_with_builtins()
    with pytest.raises(McpProviderUnavailable):
        reg.get("ws-1", "nonexistent-mcp")


def test_registry_get_unloaded_workspace_raises() -> None:
    reg = McpRegistry()
    with pytest.raises(McpProviderUnavailable):
        reg.get("ws-none", "api-http-mcp")


def test_routing_be_rest_default_to_api_http() -> None:
    reg = _registry_with_builtins()
    cfg = resolve_provider(reg, workspace_id="ws-1", target_kind=TargetKind.BE_REST, explicit=None)
    assert cfg.name == "api-http-mcp"


def test_routing_fe_web_default_to_playwright() -> None:
    reg = _registry_with_builtins()
    cfg = resolve_provider(reg, workspace_id="ws-1", target_kind=TargetKind.FE_WEB, explicit=None)
    assert cfg.name == "playwright-mcp"


def test_routing_data_default_to_postgres() -> None:
    reg = _registry_with_builtins()
    cfg = resolve_provider(reg, workspace_id="ws-1", target_kind=TargetKind.DATA, explicit=None)
    assert cfg.name == "postgres-mcp"


def test_routing_explicit_provider_wins() -> None:
    reg = _registry_with_builtins()
    cfg = resolve_provider(
        reg,
        workspace_id="ws-1",
        target_kind=TargetKind.FE_WEB,
        explicit="api-http-mcp",
    )
    # FE_WEB default would be playwright-mcp, but explicit forces api-http.
    assert cfg.name == "api-http-mcp"


def test_routing_workspace_override_wins_over_default() -> None:
    reg = _registry_with_builtins()
    overrides = {"BE_REST": {"primary": "postgres-mcp"}}
    cfg = resolve_provider(
        reg,
        workspace_id="ws-1",
        target_kind=TargetKind.BE_REST,
        explicit=None,
        overrides=overrides,
    )
    assert cfg.name == "postgres-mcp"


def test_routing_override_falls_back_when_primary_missing() -> None:
    reg = _registry_with_builtins()
    overrides = {"BE_REST": {"primary": "missing-mcp", "fallback": "api-http-mcp"}}
    cfg = resolve_provider(
        reg,
        workspace_id="ws-1",
        target_kind=TargetKind.BE_REST,
        explicit=None,
        overrides=overrides,
    )
    assert cfg.name == "api-http-mcp"


def test_routing_override_raises_when_no_fallback() -> None:
    reg = _registry_with_builtins()
    overrides = {"BE_REST": {"primary": "missing-mcp"}}
    with pytest.raises(McpProviderUnavailable):
        resolve_provider(
            reg,
            workspace_id="ws-1",
            target_kind=TargetKind.BE_REST,
            explicit=None,
            overrides=overrides,
        )


def test_routing_custom_target_without_explicit_raises() -> None:
    reg = _registry_with_builtins()
    with pytest.raises(McpProviderUnavailable):
        resolve_provider(
            reg,
            workspace_id="ws-1",
            target_kind=TargetKind.CUSTOM,
            explicit=None,
        )


def test_routing_explicit_unknown_raises() -> None:
    reg = _registry_with_builtins()
    with pytest.raises(McpProviderUnavailable):
        resolve_provider(
            reg,
            workspace_id="ws-1",
            target_kind=TargetKind.BE_REST,
            explicit="missing-mcp",
        )


def test_routing_falls_back_to_default_when_override_rule_lacks_primary() -> None:
    reg = _registry_with_builtins()
    overrides = {"BE_REST": {"primary": None}}
    cfg = resolve_provider(
        reg,
        workspace_id="ws-1",
        target_kind=TargetKind.BE_REST,
        explicit=None,
        overrides=overrides,
    )
    assert cfg.name == "api-http-mcp"


def test_row_to_config_maps_db_columns_and_overrides() -> None:
    """``_row_to_config`` lifts pool knobs from ``config_json`` and
    handles plain string transports (DB ENUM passes through ``.value``)."""
    from types import SimpleNamespace

    from suitest_mcp.registry import _row_to_config

    row = SimpleNamespace(
        id="cuid-xyz",
        workspace_id="ws-9",
        name="vendor-http",
        kind="http",
        transport="sse",  # raw string (DB ENUM lowered)
        endpoint="https://example.test/sse",
        config_json={
            "max_sessions": 8,
            "idle_ttl_seconds": 30,
            "spawn_timeout_seconds": 5.0,
            "call_timeout_seconds": 12.5,
            "headers": {"x-api-key": "sentinel"},
            "command": [],
            "env": {},
        },
        is_default_for_target={"BE_REST": True, "BE_GRAPHQL": False},
    )
    cfg = _row_to_config(row)  # type: ignore[arg-type]
    assert cfg.id == "cuid-xyz"
    assert cfg.workspace_id == "ws-9"
    assert cfg.transport is McpTransport.SSE
    assert cfg.max_sessions == 8
    assert cfg.idle_ttl_seconds == 30
    assert cfg.spawn_timeout_seconds == pytest.approx(5.0)
    assert cfg.call_timeout_seconds == pytest.approx(12.5)
    assert cfg.is_default_for_target == {"BE_REST": True, "BE_GRAPHQL": False}
    # config_json passthrough drops the consumed keys (command / env).
    assert "headers" in cfg.config_json
    assert "command" not in cfg.config_json


def test_routing_falls_back_when_default_primary_missing() -> None:
    """If the workspace catalog drops the default primary but a fallback
    is hard-coded (none today), we still raise — covers the assertion that
    the resolver does not silently mis-route to whichever provider happens
    to be first in the dict."""
    reg = McpRegistry()
    # Register a workspace catalog WITHOUT the BE_REST default (api-http-mcp).
    reg._by_workspace["ws-empty"] = {
        "playwright-mcp": McpProviderConfig(
            id="builtin:playwright-mcp",
            workspace_id="ws-empty",
            name="playwright-mcp",
            kind="browser",
            transport=McpTransport.STDIO,
            command=["true"],
        )
    }
    with pytest.raises(McpProviderUnavailable):
        resolve_provider(
            reg,
            workspace_id="ws-empty",
            target_kind=TargetKind.BE_REST,
            explicit=None,
        )

"""Unit tests for custom MCP entrypoint discovery and registry hook (M9-1).

Tests are self-contained — they do not rely on the entry_points registry being
populated. Instead they use the loader's internal helpers and mock the
importlib.metadata surface directly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from suitest_mcp.entrypoints.base import CustomMcpProviderBase, CustomMcpSpec
from suitest_mcp.entrypoints.loader import (
    discover_custom_mcp_providers,
)
from suitest_mcp.entrypoints.registry_hook import (
    _EP_WORKSPACE,
    register_discovered_providers,
)
from suitest_mcp.registry import McpRegistry

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _GoodProvider(CustomMcpProviderBase):
    spec = CustomMcpSpec(
        name="test-db-mcp",
        display_name="Test DB MCP",
        description="A test provider",
        version="1.2.3",
        transport="stdio",
        command=["python", "-m", "test_db_mcp"],
        author="tester",
    )

    async def invoke(self, tool: str, args: dict[str, object]) -> dict[str, object]:
        return {"result": f"called {tool}"}


class _NoSpecProvider(CustomMcpProviderBase):
    # Intentionally no `spec` attribute.
    async def invoke(self, tool: str, args: dict[str, object]) -> dict[str, object]:
        return {}


class _NotAProvider:
    """Not a subclass of CustomMcpProviderBase."""

    name = "impostor"


def _make_ep(name: str, value: str, load_result: Any) -> MagicMock:
    ep = MagicMock()
    ep.name = name
    ep.value = value
    ep.load.return_value = load_result
    return ep


def _make_failing_ep(name: str) -> MagicMock:
    ep = MagicMock()
    ep.name = name
    ep.value = "bad.module:BadClass"
    ep.load.side_effect = ImportError("no module named bad.module")
    return ep


# ---------------------------------------------------------------------------
# CustomMcpSpec validation
# ---------------------------------------------------------------------------


class TestCustomMcpSpec:
    def test_valid_spec(self) -> None:
        spec = CustomMcpSpec(
            name="my-mcp",
            display_name="My MCP",
            description="desc",
            version="0.1.0",
            transport="stdio",
            command=["my-mcp-server"],
        )
        assert spec.name == "my-mcp"
        assert spec.version == "0.1.0"
        assert spec.transport == "stdio"

    def test_http_transport_no_command(self) -> None:
        spec = CustomMcpSpec(
            name="http-mcp",
            display_name="HTTP MCP",
            version="2.0.0",
            transport="http",
            base_url="http://localhost:9000",
        )
        assert spec.command is None
        assert spec.base_url == "http://localhost:9000"

    def test_version_pattern_enforced(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CustomMcpSpec(
                name="bad",
                display_name="Bad",
                version="not-a-semver",
                transport="stdio",
            )

    def test_name_required(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CustomMcpSpec(
                name="",
                display_name="Missing name",
                version="1.0.0",
                transport="stdio",
            )


# ---------------------------------------------------------------------------
# CustomMcpProviderBase ABC
# ---------------------------------------------------------------------------


class TestCustomMcpProviderBase:
    def test_good_provider_has_spec(self) -> None:
        assert isinstance(_GoodProvider.spec, CustomMcpSpec)
        assert _GoodProvider.spec.name == "test-db-mcp"

    def test_subclass_invoke_is_abstract(self) -> None:
        # Abstract method: instantiating the base without invoke raises TypeError.
        with pytest.raises(TypeError):
            CustomMcpProviderBase()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_good_provider_invoke(self) -> None:
        provider = _GoodProvider()
        result = await provider.invoke("ping", {})
        assert result == {"result": "called ping"}


# ---------------------------------------------------------------------------
# discover_custom_mcp_providers
# ---------------------------------------------------------------------------


class TestDiscoverCustomMcpProviders:
    def _patch_eps(self, eps: list[MagicMock]) -> Any:
        return patch(
            "suitest_mcp.entrypoints.loader.importlib.metadata.entry_points", return_value=eps
        )

    def test_empty_group_returns_empty_list(self) -> None:
        with self._patch_eps([]):
            result = discover_custom_mcp_providers()
        assert result == []

    def test_valid_provider_discovered(self) -> None:
        ep = _make_ep("test-db-mcp", "test_pkg:_GoodProvider", _GoodProvider)
        with self._patch_eps([ep]):
            result = discover_custom_mcp_providers()
        assert len(result) == 1
        assert result[0] is _GoodProvider

    def test_load_failure_skipped(self) -> None:
        bad_ep = _make_failing_ep("broken-mcp")
        good_ep = _make_ep("test-db-mcp", "test_pkg:_GoodProvider", _GoodProvider)
        with self._patch_eps([bad_ep, good_ep]):
            result = discover_custom_mcp_providers()
        assert len(result) == 1
        assert result[0] is _GoodProvider

    def test_non_subclass_skipped(self) -> None:
        ep = _make_ep("impostor", "test_pkg:_NotAProvider", _NotAProvider)
        with self._patch_eps([ep]):
            result = discover_custom_mcp_providers()
        assert result == []

    def test_missing_spec_skipped(self) -> None:
        ep = _make_ep("no-spec", "test_pkg:_NoSpecProvider", _NoSpecProvider)
        with self._patch_eps([ep]):
            result = discover_custom_mcp_providers()
        assert result == []

    def test_multiple_valid_providers(self) -> None:
        class _SecondProvider(CustomMcpProviderBase):
            spec = CustomMcpSpec(
                name="second-mcp",
                display_name="Second",
                version="0.0.1",
                transport="in_process",
            )

            async def invoke(self, tool: str, args: dict[str, object]) -> dict[str, object]:
                return {}

        ep1 = _make_ep("test-db-mcp", "pkg:_GoodProvider", _GoodProvider)
        ep2 = _make_ep("second-mcp", "pkg:_SecondProvider", _SecondProvider)
        with self._patch_eps([ep1, ep2]):
            result = discover_custom_mcp_providers()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# register_discovered_providers (registry_hook)
# ---------------------------------------------------------------------------


class TestRegistryHook:
    def _patch_discover(self, classes: list[type[CustomMcpProviderBase]]) -> Any:
        return patch(
            "suitest_mcp.entrypoints.registry_hook.discover_custom_mcp_providers",
            return_value=classes,
        )

    def test_no_providers_returns_zero(self) -> None:
        registry = McpRegistry()
        with self._patch_discover([]):
            count = register_discovered_providers(registry)
        assert count == 0

    def test_registers_provider_config(self) -> None:
        registry = McpRegistry()
        with self._patch_discover([_GoodProvider]):
            count = register_discovered_providers(registry)
        assert count == 1
        assert _EP_WORKSPACE in registry._by_workspace
        assert "test-db-mcp" in registry._by_workspace[_EP_WORKSPACE]

    def test_registered_config_transport_is_in_process(self) -> None:
        from suitest_mcp.models import McpTransport

        registry = McpRegistry()
        with self._patch_discover([_GoodProvider]):
            register_discovered_providers(registry)
        config = registry._by_workspace[_EP_WORKSPACE]["test-db-mcp"]
        assert config.transport == McpTransport.IN_PROCESS

    def test_registered_config_id_prefix(self) -> None:
        registry = McpRegistry()
        with self._patch_discover([_GoodProvider]):
            register_discovered_providers(registry)
        config = registry._by_workspace[_EP_WORKSPACE]["test-db-mcp"]
        assert config.id.startswith("ep:")

    def test_multiple_providers_all_registered(self) -> None:
        class _Another(CustomMcpProviderBase):
            spec = CustomMcpSpec(
                name="another-mcp",
                display_name="Another",
                version="1.0.0",
                transport="http",
                base_url="http://localhost:8000",
            )

            async def invoke(self, tool: str, args: dict[str, object]) -> dict[str, object]:
                return {}

        registry = McpRegistry()
        with self._patch_discover([_GoodProvider, _Another]):
            count = register_discovered_providers(registry)
        assert count == 2
        providers = registry._by_workspace[_EP_WORKSPACE]
        assert "test-db-mcp" in providers
        assert "another-mcp" in providers

    def test_second_call_overwrites_existing(self) -> None:
        """Calling register_discovered_providers twice must not duplicate entries."""
        registry = McpRegistry()
        with self._patch_discover([_GoodProvider]):
            register_discovered_providers(registry)
            register_discovered_providers(registry)
        assert len(registry._by_workspace[_EP_WORKSPACE]) == 1

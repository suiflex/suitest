"""Unit tests for the plugin SDK (M8-3).

Pure — no DB, no LLM, no network.  Covers:
  * AgentPluginSpec validation (happy + error cases)
  * YAML round-trip
  * PluginRegistry register / get / list_all / unregister / clear
  * discover_plugins with a mock entry-point group
  * Example agents (SecurityAgent, A11yAgent) have valid specs
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from suitest_agent.plugin_sdk.base import AgentPluginBase, AgentPluginSpec
from suitest_agent.plugin_sdk.loader import ENTRY_POINT_GROUP, discover_plugins
from suitest_agent.plugin_sdk.registry import PluginRegistry

# ---------------------------------------------------------------------------
# AgentPluginSpec validation
# ---------------------------------------------------------------------------


def test_spec_valid_minimal() -> None:
    spec = AgentPluginSpec(
        name="my-agent",
        version="1.0.0",
        display_name="My Agent",
        description="Does stuff.",
        system_prompt="You are helpful.",
    )
    assert spec.name == "my-agent"
    assert spec.requires_tier == "ZERO"
    assert spec.tool_whitelist == []
    assert spec.model_preference is None


def test_spec_invalid_name_spaces() -> None:
    with pytest.raises(Exception, match="kebab-case"):
        AgentPluginSpec(
            name="My Agent",
            version="1.0.0",
            display_name="x",
            description="x",
            system_prompt="x",
        )


def test_spec_invalid_name_uppercase() -> None:
    with pytest.raises(Exception, match="kebab-case"):
        AgentPluginSpec(
            name="MyAgent",
            version="1.0.0",
            display_name="x",
            description="x",
            system_prompt="x",
        )


def test_spec_invalid_requires_tier() -> None:
    with pytest.raises(Exception, match="requires_tier"):
        AgentPluginSpec(
            name="my-agent",
            version="1.0.0",
            display_name="x",
            description="x",
            system_prompt="x",
            requires_tier="ENTERPRISE",
        )


def test_spec_valid_cloud_tier() -> None:
    spec = AgentPluginSpec(
        name="my-cloud-agent",
        version="2.1.0",
        display_name="Cloud Agent",
        description="Needs cloud.",
        system_prompt="You use the cloud.",
        requires_tier="CLOUD",
    )
    assert spec.requires_tier == "CLOUD"


def test_spec_system_prompt_max_length() -> None:
    with pytest.raises(ValueError):
        AgentPluginSpec(
            name="my-agent",
            version="1.0.0",
            display_name="x",
            description="x",
            system_prompt="x" * 4001,
        )


def test_spec_yaml_round_trip() -> None:
    spec = AgentPluginSpec(
        name="round-trip",
        version="1.2.3",
        display_name="RT Agent",
        description="Tests YAML.",
        system_prompt="You round-trip.",
        tool_whitelist=["api_http_mcp.call"],
        requires_tier="LOCAL",
        author="test",
    )
    dumped = yaml.safe_dump(spec.model_dump())
    loaded_data = yaml.safe_load(dumped)
    rehydrated = AgentPluginSpec.model_validate(loaded_data)
    assert rehydrated == spec


# ---------------------------------------------------------------------------
# PluginRegistry
# ---------------------------------------------------------------------------


class _DummyAgent(AgentPluginBase):
    spec = AgentPluginSpec(
        name="dummy-agent",
        version="1.0.0",
        display_name="Dummy",
        description="Test plugin.",
        system_prompt="You are a dummy.",
    )

    async def build_context(self, test_case_id: str, step_index: int) -> dict[str, object]:
        return {}


class _AnotherAgent(AgentPluginBase):
    spec = AgentPluginSpec(
        name="another-agent",
        version="0.5.0",
        display_name="Another",
        description="Another test plugin.",
        system_prompt="You are another.",
    )

    async def build_context(self, test_case_id: str, step_index: int) -> dict[str, object]:
        return {"source": "another"}


def _fresh_registry() -> PluginRegistry:
    r = PluginRegistry()
    return r


def test_registry_register_and_get() -> None:
    reg = _fresh_registry()
    reg.register(_DummyAgent)
    cls = reg.get("dummy-agent")
    assert cls is _DummyAgent


def test_registry_get_missing_returns_none() -> None:
    reg = _fresh_registry()
    assert reg.get("nonexistent") is None


def test_registry_list_all_sorted() -> None:
    reg = _fresh_registry()
    reg.register(_DummyAgent)
    reg.register(_AnotherAgent)
    specs = reg.list_all()
    assert [s.name for s in specs] == ["another-agent", "dummy-agent"]


def test_registry_duplicate_overwrites_with_warning(caplog: Any) -> None:
    import logging

    reg = _fresh_registry()
    reg.register(_DummyAgent)

    class _DummyV2(AgentPluginBase):
        spec = AgentPluginSpec(
            name="dummy-agent",
            version="2.0.0",
            display_name="Dummy v2",
            description="Replaced.",
            system_prompt="v2",
        )

        async def build_context(self, test_case_id: str, step_index: int) -> dict[str, object]:
            return {}

    with caplog.at_level(logging.WARNING, logger="suitest_agent.plugin_sdk.registry"):
        reg.register(_DummyV2)

    assert reg.get("dummy-agent") is _DummyV2
    assert "replacing existing plugin" in caplog.text.lower()


def test_registry_no_spec_raises_type_error() -> None:
    class _NoSpec(AgentPluginBase):
        async def build_context(self, test_case_id: str, step_index: int) -> dict[str, object]:
            return {}

    reg = _fresh_registry()
    with pytest.raises(TypeError, match="spec"):
        reg.register(_NoSpec)


def test_registry_unregister() -> None:
    reg = _fresh_registry()
    reg.register(_DummyAgent)
    assert reg.unregister("dummy-agent") is True
    assert reg.get("dummy-agent") is None
    assert reg.unregister("dummy-agent") is False


def test_registry_len_and_contains() -> None:
    reg = _fresh_registry()
    reg.register(_DummyAgent)
    reg.register(_AnotherAgent)
    assert len(reg) == 2
    assert "dummy-agent" in reg
    assert "missing" not in reg


def test_registry_clear() -> None:
    reg = _fresh_registry()
    reg.register(_DummyAgent)
    reg.clear()
    assert len(reg) == 0


# ---------------------------------------------------------------------------
# discover_plugins (mock entry points)
# ---------------------------------------------------------------------------


def test_discover_plugins_happy_path() -> None:
    mock_ep = MagicMock()
    mock_ep.name = "dummy-agent"
    mock_ep.value = "suitest_agent.plugin_sdk.examples.security_agent:SecurityAgent"
    mock_ep.load.return_value = _DummyAgent

    with patch(
        "suitest_agent.plugin_sdk.loader.entry_points",
        return_value=[mock_ep],
    ):
        found = discover_plugins()

    assert _DummyAgent in found


def test_discover_plugins_skips_non_subclass() -> None:
    mock_ep = MagicMock()
    mock_ep.name = "bad"
    mock_ep.value = "something:Bad"
    mock_ep.load.return_value = str  # not a subclass of AgentPluginBase

    with patch("suitest_agent.plugin_sdk.loader.entry_points", return_value=[mock_ep]):
        found = discover_plugins()

    assert found == []


def test_discover_plugins_skips_load_error() -> None:
    mock_ep = MagicMock()
    mock_ep.name = "broken"
    mock_ep.value = "nonexistent.module:Cls"
    mock_ep.load.side_effect = ImportError("no module")

    with patch("suitest_agent.plugin_sdk.loader.entry_points", return_value=[mock_ep]):
        found = discover_plugins()

    assert found == []


def test_discover_plugins_empty_group() -> None:
    with patch("suitest_agent.plugin_sdk.loader.entry_points", return_value=[]):
        found = discover_plugins()
    assert found == []


def test_entry_point_group_constant() -> None:
    assert ENTRY_POINT_GROUP == "suitest.plugins"


# ---------------------------------------------------------------------------
# Example agents
# ---------------------------------------------------------------------------


def test_security_agent_spec() -> None:
    from suitest_agent.plugin_sdk.examples.security_agent import SecurityAgent

    assert SecurityAgent.spec.name == "security-agent"
    assert SecurityAgent.spec.requires_tier == "CLOUD"
    assert "api_http_mcp.call" in SecurityAgent.spec.tool_whitelist
    assert SecurityAgent.spec.model_preference == "claude-sonnet-4-6"


def test_a11y_agent_spec() -> None:
    from suitest_agent.plugin_sdk.examples.a11y_agent import A11yAgent

    assert A11yAgent.spec.name == "a11y-agent"
    assert A11yAgent.spec.requires_tier == "LOCAL"
    assert "playwright_mcp.navigate" in A11yAgent.spec.tool_whitelist
    assert A11yAgent.spec.model_preference == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_security_agent_build_context() -> None:
    from suitest_agent.plugin_sdk.examples.security_agent import SecurityAgent

    agent = SecurityAgent()
    ctx = await agent.build_context("case-123", 2)
    assert ctx["agent_role"] == "security-tester"
    assert ctx["test_case_id"] == "case-123"
    assert ctx["step_index"] == 2


@pytest.mark.asyncio
async def test_a11y_agent_build_context() -> None:
    from suitest_agent.plugin_sdk.examples.a11y_agent import A11yAgent

    agent = A11yAgent()
    ctx = await agent.build_context("case-456", 0)
    assert ctx["agent_role"] == "a11y-tester"
    assert ctx["wcag_version"] == "2.2"

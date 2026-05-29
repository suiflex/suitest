"""Pydantic model validation tests for :mod:`suitest_mcp.models`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from suitest_mcp.errors import (
    McpError,
    McpHandshakeFailed,
    McpPoolExhausted,
    McpProviderUnavailable,
    McpProviderUnhealthy,
    McpToolFailed,
    McpToolTimeout,
)
from suitest_mcp.models import (
    McpArtifact,
    McpHealthState,
    McpHealthStatus,
    McpProviderConfig,
    McpToolCall,
    McpToolResult,
    McpToolSchema,
    McpTransport,
)


def test_tool_schema_valid() -> None:
    schema = McpToolSchema(name="echo", description="echo", input_schema={"type": "object"})
    assert schema.name == "echo"
    assert schema.input_schema == {"type": "object"}


def test_tool_schema_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        McpToolSchema(name="")


def test_provider_config_required_fields() -> None:
    cfg = McpProviderConfig(
        id="p1",
        workspace_id="w1",
        name="mock",
        kind="test",
        transport=McpTransport.STDIO,
        command=["echo"],
    )
    assert cfg.transport is McpTransport.STDIO
    assert cfg.max_sessions == 4
    assert cfg.call_timeout_seconds == pytest.approx(30.0)


def test_provider_config_rejects_blank_id() -> None:
    with pytest.raises(ValidationError):
        McpProviderConfig(
            id="",
            workspace_id="w",
            name="n",
            kind="k",
            transport=McpTransport.STDIO,
        )


def test_provider_config_from_attributes() -> None:
    from types import SimpleNamespace

    row = SimpleNamespace(
        id="rid",
        workspace_id="ws",
        name="name",
        kind="http",
        transport=McpTransport.SSE,
        endpoint="https://example.com",
        config_json={"k": "v"},
        env={},
        command=[],
        is_default_for_target={"BE_REST": True},
    )
    cfg = McpProviderConfig.model_validate(row)
    assert cfg.endpoint == "https://example.com"
    assert cfg.is_default_for_target == {"BE_REST": True}


def test_artifact_alias_bytes() -> None:
    art = McpArtifact(
        kind="SCREENSHOT",
        filename="shot.png",
        content_type="image/png",
        bytes=b"\x89PNG",
    )
    assert art.bytes_ == b"\x89PNG"
    assert art.text is None


def test_artifact_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        McpArtifact.model_validate(
            {"kind": "UNKNOWN", "filename": "x", "content_type": "text/plain"}
        )


def test_tool_call_optional_refs() -> None:
    call = McpToolCall(provider="mock", tool="echo", arguments={"x": 1})
    assert call.run_id is None
    assert call.workspace_id is None


def test_tool_result_default_collections() -> None:
    res = McpToolResult(ok=True, duration_ms=42)
    assert res.output == {}
    assert res.artifacts == []


def test_health_status_round_trip() -> None:
    now = datetime.now(tz=UTC)
    status = McpHealthStatus(
        provider_id="p1",
        name="mock",
        state=McpHealthState.OK,
        latency_ms=12,
        checked_at=now,
    )
    assert status.state is McpHealthState.OK
    assert status.checked_at == now


def test_transport_enum_values() -> None:
    assert {t.value for t in McpTransport} == {"stdio", "sse", "ws", "in_process"}


def test_health_state_enum_values() -> None:
    assert {s.value for s in McpHealthState} == {"ok", "degraded", "down", "unknown"}


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (McpError("x"), "MCP_GENERIC"),
        (McpProviderUnavailable("x"), "MCP_PROVIDER_UNAVAILABLE"),
        (McpProviderUnhealthy("x"), "MCP_PROVIDER_UNHEALTHY"),
        (McpToolTimeout("x"), "MCP_TOOL_TIMEOUT"),
        (McpToolFailed("x"), "MCP_TOOL_FAILED"),
        (McpPoolExhausted("x"), "MCP_POOL_EXHAUSTED"),
        (McpHandshakeFailed("x"), "MCP_HANDSHAKE_FAILED"),
    ],
)
def test_error_codes(exc: McpError, code: str) -> None:
    assert exc.code == code
    assert str(exc) == "x"


def test_error_override_code() -> None:
    exc = McpToolFailed("boom", code="CUSTOM")
    assert exc.code == "CUSTOM"

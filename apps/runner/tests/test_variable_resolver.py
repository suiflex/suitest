"""Unit tests for suitest_runner.executors.variable_resolver.VariableResolver."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from suitest_mcp.models import McpToolResult
from suitest_runner.executors.step_executor import execute_step
from suitest_runner.executors.variable_resolver import VariableResolver
from suitest_shared.domain.enums import StepOutcome, TargetKind


def test_resolver_hierarchy() -> None:
    # 1. Workspace variable default
    resolver_ws = VariableResolver(
        workspace_variables={"base_url": "https://default.com", "api_key": "ws-key"}
    )
    assert resolver_ws.get("base_url") == "https://default.com"
    assert resolver_ws.get("api_key") == "ws-key"

    # 2. Suite variable overrides workspace
    resolver_suite = VariableResolver(
        workspace_variables={"base_url": "https://default.com", "api_key": "ws-key"},
        suite_variables={"base_url": "https://staging.suite.com"},
    )
    assert resolver_suite.get("base_url") == "https://staging.suite.com"
    assert resolver_suite.get("api_key") == "ws-key"

    # 3. Case dataset row overrides suite and workspace
    resolver_case = VariableResolver(
        workspace_variables={"base_url": "https://default.com", "user": "ws-user"},
        suite_variables={"base_url": "https://staging.suite.com"},
        dataset_row={"name": "Admin Row", "values": {"user": "admin@suitest.dev"}},
    )
    assert resolver_case.get("user") == "admin@suitest.dev"
    assert resolver_case.get("base_url") == "https://staging.suite.com"


def test_resolver_env_fallback(monkeypatch) -> None:
    monkeypatch.setenv("CI_JOB_TOKEN", "token-999")
    resolver = VariableResolver(
        workspace_variables={"foo": "bar"},
        env_fallback=True,
    )
    assert resolver.get("foo") == "bar"
    assert resolver.get("CI_JOB_TOKEN") == "token-999"
    assert resolver.get("NONEXISTENT_VAR") is None


def test_interpolate_string() -> None:
    resolver = VariableResolver(
        workspace_variables={"host": "api.test.io", "port": "8080", "secret": "s3cr3t"},
        dataset_row={"values": {"role": "manager"}},
    )

    # Standard {{var}} syntax
    text = "http://{{host}}:{{port}}/v1/users?role={{role}}&extra={{unknown}}"
    interpolated = resolver.interpolate_string(text)
    assert interpolated == "http://api.test.io:8080/v1/users?role=manager&extra={{unknown}}"

    # Compatibility ${var} syntax
    text2 = "Bearer ${secret}"
    assert resolver.interpolate_string(text2) == "Bearer s3cr3t"


def test_interpolate_nested_data() -> None:
    resolver = VariableResolver(
        workspace_variables={"base_url": "https://app.test", "auth_token": "bearer-123"},
        dataset_row={"values": {"username": "qa_tester", "user_id": "42"}},
    )

    payload = {
        "url": "{{base_url}}/api/login",
        "headers": {
            "Authorization": "Bearer {{auth_token}}",
            "Content-Type": "application/json",
        },
        "body": {
            "user": "{{username}}",
            "id": "{{user_id}}",
            "active": True,
            "roles": ["member", "{{username}}"],
        },
    }

    result = resolver.interpolate_data(payload)
    assert result["url"] == "https://app.test/api/login"
    assert result["headers"]["Authorization"] == "Bearer bearer-123"
    assert result["body"]["user"] == "qa_tester"
    assert result["body"]["id"] == "42"
    assert result["body"]["active"] is True
    assert result["body"]["roles"] == ["member", "qa_tester"]


@pytest.mark.asyncio
async def test_execute_step_interpolates_arguments_with_resolver() -> None:
    invoker = MagicMock()
    invoker.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, stdout="{}", artifacts=[], duration_ms=10)
    )

    step = MagicMock()
    step.id = "s1"
    step.code = json.dumps(
        {
            "tool": "browser_navigate",
            "arguments": {"url": "{{base_url}}/dashboard?user={{username}}"},
        }
    )
    step.mcp_provider = "playwright-mcp"
    step.target_kind = TargetKind.FE_WEB.value

    resolver = VariableResolver(
        workspace_variables={"base_url": "https://corp.com"},
        dataset_row={"values": {"username": "jane_doe"}},
    )

    res = await execute_step(
        invoker=invoker,
        test_step=step,
        run_id="r1",
        workspace_id="ws1",
        actor_user_id="u1",
        routing_overrides=None,
        variable_resolver=resolver,
    )

    assert res.outcome == StepOutcome.PASS
    invoker.invoke.assert_awaited_once()
    called_kwargs = invoker.invoke.call_args.kwargs
    assert called_kwargs["arguments"]["url"] == "https://corp.com/dashboard?user=jane_doe"


@pytest.mark.asyncio
async def test_execute_step_interpolates_username_and_password_from_dataset(monkeypatch) -> None:
    # Even if environment has a fallback password like 'secret_sauce', dataset_row takes precedence
    monkeypatch.setenv("SUITEST_PASSWORD", "secret_sauce")

    invoker = MagicMock()
    invoker.invoke = AsyncMock(
        return_value=McpToolResult(ok=True, stdout="{}", artifacts=[], duration_ms=10)
    )

    step_user = MagicMock()
    step_user.id = "s1"
    step_user.code = json.dumps(
        {
            "tool": "browser_type",
            "arguments": {"target": '#loginUser input[name="username"]', "text": "{{username}}"},
        }
    )
    step_user.mcp_provider = "playwright-mcp"
    step_user.target_kind = TargetKind.FE_WEB.value

    step_pass = MagicMock()
    step_pass.id = "s2"
    step_pass.code = json.dumps(
        {
            "tool": "browser_type",
            "arguments": {"target": '#loginUser input[name="password"]', "text": "{{password}}"},
        }
    )
    step_pass.mcp_provider = "playwright-mcp"
    step_pass.target_kind = TargetKind.FE_WEB.value

    resolver = VariableResolver(
        dataset_row={"values": {"username": "user", "password": "123"}},
    )

    await execute_step(
        invoker=invoker,
        test_step=step_user,
        run_id="r1",
        workspace_id="ws1",
        actor_user_id="u1",
        routing_overrides=None,
        variable_resolver=resolver,
    )
    call_args_user = invoker.invoke.call_args.kwargs
    assert call_args_user["arguments"]["text"] == "user"

    invoker.invoke.reset_mock()
    await execute_step(
        invoker=invoker,
        test_step=step_pass,
        run_id="r1",
        workspace_id="ws1",
        actor_user_id="u1",
        routing_overrides=None,
        variable_resolver=resolver,
    )
    call_args_pass = invoker.invoke.call_args.kwargs
    assert call_args_pass["arguments"]["text"] == "123"

"""Unit tests for the deterministic OpenAPI generator (M2 Task 2) — no DB.

Exercise the generator core directly: example-body synthesis, per-case-kind
coverage, options gating, rate-limit detection, and rendered-code safety (the
emitted Python must never contain ``eval`` / ``__import__`` / ``exec``).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest
from suitest_agent.generators.openapi_generator import (
    OpenApiGenerator,
    OpenApiSpecError,
)
from suitest_shared.domain.enums import CaseSource, TargetKind
from suitest_shared.schemas.generator_input import OpenApiGeneratorOptions

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from suitest_shared.schemas.generator_input import TestCaseDraft


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SPEC: dict[str, object] = {
    "openapi": "3.0.3",
    "info": {"title": "Sample", "version": "1.0.0"},
    "paths": {
        "/users": {
            "post": {
                "operationId": "createUser",
                "tags": ["users"],
                "security": [{"bearer": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["email", "age"],
                                "properties": {
                                    "email": {"type": "string", "format": "email"},
                                    "age": {"type": "integer", "minimum": 1, "maximum": 120},
                                    "nickname": {
                                        "type": "string",
                                        "minLength": 3,
                                        "maxLength": 8,
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "created",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/User"}}
                        },
                    }
                },
            }
        },
        "/health": {
            "get": {
                "operationId": "health",
                "tags": ["ops"],
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
    "components": {
        "schemas": {
            "User": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "email": {"type": "string"}},
            }
        },
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
    },
}

_RATE_LIMITED_SPEC: dict[str, object] = {
    "openapi": "3.0.3",
    "info": {"title": "RL", "version": "1.0.0"},
    "paths": {
        "/ping": {
            "get": {
                "operationId": "ping",
                "responses": {
                    "200": {
                        "description": "ok",
                        "headers": {
                            "X-RateLimit-Limit": {
                                "schema": {"type": "integer"},
                                "example": 3,
                            }
                        },
                    },
                    "429": {"description": "too many requests"},
                },
            }
        }
    },
}


async def _collect(gen: OpenApiGenerator) -> list[TestCaseDraft]:
    drafts: list[TestCaseDraft] = []
    agen: AsyncIterator[TestCaseDraft] = gen.generate()
    async for draft in agen:
        drafts.append(draft)
    return drafts


def _make(options: OpenApiGeneratorOptions | None = None) -> OpenApiGenerator:
    return OpenApiGenerator(httpx.AsyncClient(), options or OpenApiGeneratorOptions())


# ---------------------------------------------------------------------------
# fetch_spec
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_spec_from_content_parses() -> None:
    gen = _make()
    spec = await gen.fetch_spec(None, json.dumps(_SPEC))
    assert spec.paths is not None
    assert "/users" in spec.paths


@pytest.mark.asyncio
async def test_fetch_spec_invalid_raises() -> None:
    gen = _make()
    with pytest.raises(OpenApiSpecError):
        await gen.fetch_spec(None, "{not json and not: yaml: [")


@pytest.mark.asyncio
async def test_fetch_spec_requires_input() -> None:
    gen = _make()
    with pytest.raises(OpenApiSpecError):
        await gen.fetch_spec(None, None)


# ---------------------------------------------------------------------------
# Example body synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_example_body_uses_format_and_required() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_SPEC))
    schema: dict[str, object] = {
        "type": "object",
        "required": ["email", "age"],
        "properties": {
            "email": {"type": "string", "format": "email"},
            "age": {"type": "integer", "minimum": 1, "maximum": 120},
        },
    }
    body = gen._build_example_body(schema)
    assert isinstance(body, dict)
    assert "email" in body and "age" in body
    assert "@example.com" in str(body["email"])
    age = body["age"]
    assert isinstance(age, int)
    assert 1 <= age <= 120


@pytest.mark.asyncio
async def test_build_example_body_prefers_explicit_example() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_SPEC))
    schema: dict[str, object] = {"type": "object", "example": {"hello": "world"}}
    assert gen._build_example_body(schema) == {"hello": "world"}


@pytest.mark.asyncio
async def test_build_example_body_is_deterministic() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"age": {"type": "integer", "minimum": 0, "maximum": 999}},
    }
    g1 = _make()
    await g1.fetch_spec(None, json.dumps(_SPEC))
    g2 = _make()
    await g2.fetch_spec(None, json.dumps(_SPEC))
    assert g1._build_example_body(schema) == g2._build_example_body(schema)


# ---------------------------------------------------------------------------
# Case-kind coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generates_contract_for_every_operation() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    kinds = {d.generated_from["case_kind"] for d in drafts}
    assert "contract" in kinds
    # One contract per operation (2 operations).
    contract = [d for d in drafts if d.generated_from["case_kind"] == "contract"]
    assert len(contract) == 2


@pytest.mark.asyncio
async def test_generates_auth_required_and_boundary_cases() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    kinds = {d.generated_from["case_kind"] for d in drafts}
    assert "auth_negative" in kinds
    assert "required_field" in kinds
    assert "boundary" in kinds


@pytest.mark.asyncio
async def test_all_drafts_are_mcp_source_be_rest() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    for d in drafts:
        assert d.source is CaseSource.MCP
        assert d.target_kind is TargetKind.BE_REST
        assert all(s.mcp_provider == "api-http-mcp" for s in d.steps)
        assert "api-contract" in d.tags


# ---------------------------------------------------------------------------
# Options gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_options_disabled_yields_fewer_cases() -> None:
    full = _make()
    await full.fetch_spec(None, json.dumps(_SPEC))
    full_drafts = await _collect(full)

    minimal_opts = OpenApiGeneratorOptions(
        include_negative_auth=False,
        include_required_field_tests=False,
        include_boundary_tests=False,
        include_rate_limit_tests=False,
    )
    minimal = _make(minimal_opts)
    await minimal.fetch_spec(None, json.dumps(_SPEC))
    minimal_drafts = await _collect(minimal)

    assert len(minimal_drafts) < len(full_drafts)
    assert {d.generated_from["case_kind"] for d in minimal_drafts} == {"contract"}


@pytest.mark.asyncio
async def test_tags_filter_limits_operations() -> None:
    opts = OpenApiGeneratorOptions(tags_filter=["users"])
    gen = _make(opts)
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    paths = {d.generated_from["path"] for d in drafts}
    assert paths == {"/users"}  # /health (tag "ops") filtered out


@pytest.mark.asyncio
async def test_tag_prefix_prepended() -> None:
    opts = OpenApiGeneratorOptions(tag_prefix="suiteA")
    gen = _make(opts)
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    assert all(d.tags[0] == "suiteA" for d in drafts)


@pytest.mark.asyncio
async def test_max_cases_per_operation_caps_output() -> None:
    opts = OpenApiGeneratorOptions(max_cases_per_operation=1)
    gen = _make(opts)
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    # /users has many kinds but is capped to 1; /health has 1 → 2 total.
    by_op: dict[tuple[object, object], int] = {}
    for d in drafts:
        key = (d.generated_from["method"], d.generated_from["path"])
        by_op[key] = by_op.get(key, 0) + 1
    assert all(count <= 1 for count in by_op.values())


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_case_present_when_documented() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_RATE_LIMITED_SPEC))
    drafts = await _collect(gen)
    rl = [d for d in drafts if d.generated_from["case_kind"] == "rate_limit"]
    assert len(rl) == 1
    # Documented limit example=3 → 4 probe steps (limit + 1).
    assert len(rl[0].steps) == 4
    last_step = rl[0].steps[-1]
    assert "429" in last_step.code


@pytest.mark.asyncio
async def test_no_rate_limit_case_when_absent() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    assert not [d for d in drafts if d.generated_from["case_kind"] == "rate_limit"]


# ---------------------------------------------------------------------------
# Rendered-code safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rendered_code_is_safe_and_uses_placeholders() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    for d in drafts:
        for step in d.steps:
            code = step.code
            assert "eval(" not in code
            assert "__import__" not in code
            assert "exec(" not in code
            assert "mcp.api.request(" in code
    # The contract case for /users emits placeholders + a schema assertion.
    contract = next(
        d
        for d in drafts
        if d.generated_from["case_kind"] == "contract" and d.generated_from["path"] == "/users"
    )
    code = contract.steps[0].code
    assert "{{base_url}}" in code
    assert "{{auth.token}}" in code
    assert "validate_jsonschema(" in code


@pytest.mark.asyncio
async def test_auth_negative_omits_and_injects_token() -> None:
    gen = _make()
    await gen.fetch_spec(None, json.dumps(_SPEC))
    drafts = await _collect(gen)
    auth_cases = [d for d in drafts if d.generated_from["case_kind"] == "auth_negative"]
    assert len(auth_cases) == 2
    codes = [d.steps[0].code for d in auth_cases]
    # Missing-token case has no Authorization header; invalid-token has a bogus one.
    assert any("Authorization" not in c for c in codes)
    assert any("Bearer xxxx" in c for c in codes)
    for c in codes:
        assert "401" in c and "403" in c

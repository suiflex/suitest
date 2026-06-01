"""Unit tests for the rule-based target classifier (M2 Task 1).

Pure — no DB, no LLM. Covers every branch of
:func:`suitest_agent.generators.classifier.classify`.

Note: the canonical :class:`TargetKind` has no ``MIXED`` value, so the free-form
text branches (markdown / plain text) classify as ``CUSTOM`` with the
``prd-parsing`` strategy.
"""

from __future__ import annotations

import json

import pytest
from suitest_agent.generators.classifier import classify
from suitest_shared.domain.enums import TargetKind
from suitest_shared.schemas.generator_input import (
    GenerationInput,
    GenerationInputKind,
    RecommendedStrategy,
)


def _url(value: str, **kw: str) -> GenerationInput:
    return GenerationInput(kind=GenerationInputKind.URL, value=value, **kw)


def _file(value: str, filename: str) -> GenerationInput:
    return GenerationInput(kind=GenerationInputKind.FILE_CONTENT, value=value, filename=filename)


def _raw(value: str, content_type_hint: str | None = None) -> GenerationInput:
    return GenerationInput(
        kind=GenerationInputKind.RAW_TEXT, value=value, content_type_hint=content_type_hint
    )


def test_openapi_json_url() -> None:
    r = classify(_url("https://api.example.com/openapi.json"))
    assert r.target_kind == TargetKind.BE_REST
    assert r.recommended_strategy == RecommendedStrategy.OPENAPI_GENERATOR
    assert r.recommended_mcp.name == "api-http-mcp"


def test_openapi_yaml_url() -> None:
    r = classify(_url("https://api.example.com/v1/openapi.yaml"))
    assert r.target_kind == TargetKind.BE_REST


def test_swagger_json_url() -> None:
    r = classify(_url("https://api.example.com/swagger.json"))
    assert r.target_kind == TargetKind.BE_REST


def test_graphql_url_contains_token() -> None:
    r = classify(_url("https://api.example.com/graphql"))
    assert r.target_kind == TargetKind.BE_GRAPHQL
    assert r.recommended_mcp.name == "graphql-mcp"


def test_graphql_filename() -> None:
    r = classify(_file("type Query { ping: String }", "schema.graphql"))
    assert r.target_kind == TargetKind.BE_GRAPHQL


def test_proto_filename() -> None:
    r = classify(_file('syntax = "proto3";', "service.proto"))
    assert r.target_kind == TargetKind.BE_GRPC
    assert r.recommended_mcp.name == "grpc-mcp"


def test_apk_filename() -> None:
    r = classify(_file("binary-bytes", "app-release.apk"))
    assert r.target_kind == TargetKind.FE_MOBILE


def test_ipa_filename() -> None:
    r = classify(_file("binary-bytes", "App.ipa"))
    assert r.target_kind == TargetKind.FE_MOBILE


def test_postgres_url() -> None:
    r = classify(_url("postgresql://u:p@host/db"))
    assert r.target_kind == TargetKind.DATA
    assert r.recommended_mcp.name == "postgres-mcp"


def test_mysql_url() -> None:
    r = classify(_url("mysql://u:p@host/db"))
    assert r.target_kind == TargetKind.DATA
    assert r.recommended_mcp.name == "mysql-mcp"


def test_mongodb_url() -> None:
    r = classify(_url("mongodb://u:p@host/db"))
    assert r.target_kind == TargetKind.DATA
    assert r.recommended_mcp.name == "mongo-mcp"


def test_openapi_body_json() -> None:
    body = json.dumps({"openapi": "3.0.0", "paths": {}})
    r = classify(_raw(body))
    assert r.target_kind == TargetKind.BE_REST


def test_swagger_body_json() -> None:
    body = json.dumps({"swagger": "2.0"})
    r = classify(_raw(body))
    assert r.target_kind == TargetKind.BE_REST


def test_k8s_yaml_deployment() -> None:
    body = "kind: Deployment\nmetadata:\n  name: web\n"
    r = classify(_raw(body))
    assert r.target_kind == TargetKind.INFRA
    assert r.recommended_mcp.name == "kubernetes-mcp"


def test_k8s_yaml_service() -> None:
    body = "kind: Service\nmetadata:\n  name: web\n"
    r = classify(_raw(body))
    assert r.target_kind == TargetKind.INFRA


def test_text_html_content_type() -> None:
    r = classify(_raw("<html><body>hi</body></html>", content_type_hint="text/html"))
    assert r.target_kind == TargetKind.FE_WEB


def test_text_markdown_content_type() -> None:
    # No canonical MIXED kind — free-form text maps to CUSTOM + prd-parsing.
    r = classify(_raw("# PRD\nUser can log in.", content_type_hint="text/markdown"))
    assert r.target_kind == TargetKind.CUSTOM
    assert r.recommended_strategy == RecommendedStrategy.PRD_PARSING


def test_text_plain_content_type() -> None:
    r = classify(_raw("The user logs in then sees the dashboard.", content_type_hint="text/plain"))
    assert r.target_kind == TargetKind.CUSTOM
    assert r.recommended_strategy == RecommendedStrategy.PRD_PARSING


def test_generic_https_url_falls_through_to_fe_web() -> None:
    r = classify(_url("https://example.com/app"))
    assert r.target_kind == TargetKind.FE_WEB
    assert r.recommended_strategy == RecommendedStrategy.URL_CRAWLER


def test_unmatched_returns_custom() -> None:
    r = classify(_raw("nothing special here"))
    assert r.target_kind == TargetKind.CUSTOM
    assert r.recommended_strategy == RecommendedStrategy.RECORDER
    assert r.confidence < 0.5


_ALL_INPUTS: list[GenerationInput] = [
    _url("https://api.example.com/openapi.json"),
    _url("https://api.example.com/graphql"),
    _url("postgresql://u:p@host/db"),
    _url("mysql://u:p@host/db"),
    _url("mongodb://u:p@host/db"),
    _url("https://example.com/app"),
    _file("x", "schema.graphql"),
    _file("x", "service.proto"),
    _file("x", "app.apk"),
    _file("x", "App.ipa"),
    _raw(json.dumps({"openapi": "3.0.0"})),
    _raw(json.dumps({"swagger": "2.0"})),
    _raw("kind: Deployment\n"),
    _raw("kind: Service\n"),
    _raw("<html></html>", content_type_hint="text/html"),
    _raw("# PRD", content_type_hint="text/markdown"),
    _raw("plain prd", content_type_hint="text/plain"),
    _raw("nothing"),
]


@pytest.mark.parametrize("inp", _ALL_INPUTS)
def test_confidence_bounds(inp: GenerationInput) -> None:
    r = classify(inp)
    assert 0.0 <= r.confidence <= 1.0


@pytest.mark.parametrize("inp", _ALL_INPUTS)
def test_rationale_non_empty(inp: GenerationInput) -> None:
    r = classify(inp)
    assert r.rationale.strip() != ""

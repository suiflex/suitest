"""Rule-based target classifier (M2 Task 1).

Pure, deterministic, NO LLM — runs in every capability tier. Given a
:class:`GenerationInput`, returns a :class:`ClassificationResult` describing the
most likely :class:`TargetKind`, the recommended MCP provider name, and a
generation strategy (plus tier-gated alternatives). First matching rule wins.

Every other M2 generator consults this to pick its default routing.

Note: the canonical :class:`TargetKind` has no ``MIXED`` value, so free-form text
(likely a PRD) maps to ``CUSTOM`` with the ``prd-parsing`` strategy.
"""

from __future__ import annotations

import json
import re
from typing import Final
from urllib.parse import urlparse

from suitest_shared.domain.enums import TargetKind
from suitest_shared.schemas.generator_input import (
    ClassificationResult,
    GenerationInput,
    GenerationInputKind,
    RecommendedMcp,
    RecommendedStrategy,
    StrategyAlternative,
)

_OPENAPI_URL_RE: Final = re.compile(r"/(openapi|swagger)(\.json|\.yaml|\.yml)$", re.I)
_GRAPHQL_URL_TOKENS: Final = ("graphql", "/gql")
_K8S_KIND_RE: Final = re.compile(
    r"^kind:\s*(Deployment|Service|StatefulSet|DaemonSet|Ingress|ConfigMap|Job|CronJob)\b",
    re.M,
)


# Per-rule result constants: target kind, confidence, default MCP provider,
# strategy, and (strategy, requires_tier) alternative pairs. Keyed by rule
# label (NOT TargetKind — ``prd_text`` and ``custom`` both map to CUSTOM).
_RULE_RESULTS: Final[
    dict[
        str,
        tuple[
            TargetKind, float, str, RecommendedStrategy, tuple[tuple[RecommendedStrategy, str], ...]
        ],
    ]
] = {
    "be_rest": (
        TargetKind.BE_REST,
        0.95,
        "api-http-mcp",
        RecommendedStrategy.OPENAPI_GENERATOR,
        ((RecommendedStrategy.PRD_PARSING, "CLOUD"),),
    ),
    "be_graphql": (
        TargetKind.BE_GRAPHQL,
        0.9,
        "graphql-mcp",
        RecommendedStrategy.OPENAPI_GENERATOR,
        (),
    ),
    "be_grpc": (TargetKind.BE_GRPC, 0.9, "grpc-mcp", RecommendedStrategy.OPENAPI_GENERATOR, ()),
    "fe_web": (
        TargetKind.FE_WEB,
        0.7,
        "playwright-mcp",
        RecommendedStrategy.URL_CRAWLER,
        ((RecommendedStrategy.RECORDER, "ZERO"), (RecommendedStrategy.URL_SEMANTIC, "CLOUD")),
    ),
    "fe_mobile": (TargetKind.FE_MOBILE, 0.95, "appium-mcp", RecommendedStrategy.URL_CRAWLER, ()),
    "data": (TargetKind.DATA, 0.95, "postgres-mcp", RecommendedStrategy.OPENAPI_GENERATOR, ()),
    "infra": (TargetKind.INFRA, 0.85, "kubernetes-mcp", RecommendedStrategy.OPENAPI_GENERATOR, ()),
    # Free-form text — no canonical MIXED kind, so map to CUSTOM + PRD parsing.
    # PRD parsing is LLM-driven (CLOUD/LOCAL); the deterministic fallback is
    # the recorder, which works in ZERO tier.
    "prd_text": (
        TargetKind.CUSTOM,
        0.6,
        "playwright-mcp",
        RecommendedStrategy.PRD_PARSING,
        ((RecommendedStrategy.RECORDER, "ZERO"),),
    ),
    "custom": (TargetKind.CUSTOM, 0.3, "playwright-mcp", RecommendedStrategy.RECORDER, ()),
}

# DB connection URL scheme → bundled MCP provider (overrides the ``data``
# rule's default provider).
_DATA_SCHEME_PROVIDERS: Final[dict[str, str]] = {
    "postgresql": "postgres-mcp",
    "mysql": "mysql-mcp",
    "mongodb": "mongo-mcp",
}


def _result(rule: str, rationale: str, *, mcp_name: str | None = None) -> ClassificationResult:
    """Build the :class:`ClassificationResult` for one matched rule."""
    target_kind, confidence, default_mcp, strategy, alt_pairs = _RULE_RESULTS[rule]
    return ClassificationResult(
        target_kind=target_kind,
        confidence=confidence,
        recommended_mcp=RecommendedMcp(name=mcp_name if mcp_name is not None else default_mcp),
        recommended_strategy=strategy,
        alternatives=[StrategyAlternative(strategy=s, requires_tier=tier) for s, tier in alt_pairs],
        rationale=rationale,
    )


def classify(inp: GenerationInput) -> ClassificationResult:
    """Rule-based classifier; first match wins."""
    # URL-based signals
    if inp.kind == GenerationInputKind.URL:
        parsed = urlparse(inp.value)
        path_lower = parsed.path.lower()
        if _OPENAPI_URL_RE.search(path_lower):
            return _result("be_rest", "URL ends in openapi|swagger spec path")
        if any(t in inp.value.lower() for t in _GRAPHQL_URL_TOKENS):
            return _result("be_graphql", "URL contains graphql token")
        if parsed.scheme in _DATA_SCHEME_PROVIDERS:
            return _result(
                "data",
                "DB connection URL scheme",
                mcp_name=_DATA_SCHEME_PROVIDERS[parsed.scheme],
            )
        if parsed.scheme in {"http", "https"}:
            return _result("fe_web", "Generic HTTP(S) URL — assume web UI")
    # Filename signals (file content kind)
    if inp.kind == GenerationInputKind.FILE_CONTENT and inp.filename:
        low = inp.filename.lower()
        if low.endswith(".graphql"):
            return _result("be_graphql", "Filename ends in .graphql")
        if low.endswith(".proto"):
            return _result("be_grpc", "Filename ends in .proto")
        if low.endswith((".apk", ".ipa")):
            return _result("fe_mobile", "Mobile binary file extension")
    # Body content signals (file_content or raw_text)
    if inp.kind in {GenerationInputKind.FILE_CONTENT, GenerationInputKind.RAW_TEXT}:
        body = inp.value
        try:
            j = json.loads(body)
            if isinstance(j, dict):
                if "openapi" in j or "swagger" in j:
                    return _result("be_rest", "JSON body has openapi/swagger field")
                if j.get("kind") == "Service" and "spec" in j:
                    return _result("infra", "JSON body kind=Service with spec")
        except ValueError:  # json.JSONDecodeError is a ValueError subclass
            pass
        if _K8S_KIND_RE.search(body):
            return _result("infra", "YAML kind: Deployment/Service/...")
    # Content-type signals
    if inp.content_type_hint:
        ct = inp.content_type_hint.lower()
        if ct.startswith("text/html"):
            return _result("fe_web", "Content-Type text/html")
        if ct.startswith(("text/markdown", "text/plain")):
            return _result("prd_text", "Free-form text — likely PRD")
    return _result("custom", "No rule matched")

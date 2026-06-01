"""Generator input + classification schemas (M2 Task 1).

These are the wire/DTO types shared by the rule-based target classifier
(:mod:`suitest_agent.generators.classifier`) and the ``POST /generators/classify``
endpoint. ``TargetKind`` is NOT redefined here — it is the single canonical enum in
:mod:`suitest_shared.domain.enums` (it maps 1:1 to a Postgres ENUM); we re-use it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from suitest_shared.domain.enums import TargetKind


class GenerationInputKind(StrEnum):
    URL = "url"
    FILE_CONTENT = "file_content"
    RAW_TEXT = "raw_text"


class GenerationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    kind: GenerationInputKind
    value: Annotated[str, Field(min_length=1, max_length=2_000_000)]
    content_type_hint: str | None = None
    filename: str | None = None


class RecommendedStrategy(StrEnum):
    OPENAPI_GENERATOR = "openapi-generator"
    URL_CRAWLER = "url-crawler"
    RECORDER = "recorder"
    URL_SEMANTIC = "url-semantic"  # requires LLM
    MCP_DISCOVERY = "mcp-discovery"  # requires LLM
    PRD_PARSING = "prd-parsing"  # requires LLM


class RecommendedMcp(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None = None  # null when no registered provider matches the name
    name: str  # e.g. "api-http-mcp"


class StrategyAlternative(BaseModel):
    strategy: RecommendedStrategy
    requires_tier: Literal["ZERO", "LOCAL", "CLOUD"]


class ClassificationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_kind: TargetKind
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    recommended_mcp: RecommendedMcp
    recommended_strategy: RecommendedStrategy
    alternatives: list[StrategyAlternative] = Field(default_factory=list)
    rationale: str

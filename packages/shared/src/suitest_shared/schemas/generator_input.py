"""Generator input + classification schemas (M2 Task 1).

These are the wire/DTO types shared by the rule-based target classifier
(:mod:`suitest_agent.generators.classifier`) and the ``POST /generators/classify``
endpoint. ``TargetKind`` is NOT redefined here — it is the single canonical enum in
:mod:`suitest_shared.domain.enums` (it maps 1:1 to a Postgres ENUM); we re-use it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from suitest_shared.domain.enums import CaseSource, Priority, TargetKind


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


# ---------------------------------------------------------------------------
# M2 Task 2 — deterministic OpenAPI generator I/O
# ---------------------------------------------------------------------------
#
# ``POST /generators/openapi`` ingests an OpenAPI 3.0 spec (by URL or inline
# content) and streams back per-operation contract :class:`TestCaseDraft`s over
# SSE. The generator is pure rules (NO LLM) so it lives in every tier
# (``TierFlag.ANY``). ``source`` / ``priority`` re-use the canonical
# :mod:`suitest_shared.domain.enums` enums — they are never redefined here.


class OpenApiGeneratorOptions(BaseModel):
    """Per-request toggles for which case kinds the generator emits.

    Defaults emit the full deterministic suite; callers disable categories to
    keep a generated suite focused (e.g. contract-only). ``tags_filter`` limits
    generation to operations carrying at least one of the listed OpenAPI tags.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    include_negative_auth: bool = True
    include_schema_validation: bool = True
    include_required_field_tests: bool = True
    include_boundary_tests: bool = True
    include_rate_limit_tests: bool = True
    # M3-8: when the workspace has an active LLM, propose extra edge cases
    # (boundary / fuzz / negative) on top of the deterministic contract suite.
    # Ignored (graceful ZERO degrade) when no LLM is configured.
    include_llm_edge_cases: bool = False
    tag_prefix: str | None = None
    tags_filter: list[str] = Field(default_factory=list)
    auth_profile_id: str | None = None
    max_cases_per_operation: Annotated[int, Field(ge=1, le=100)] = 20
    base_url_override: str | None = None


class OpenApiGenerateRequest(BaseModel):
    """Generation request: exactly one of ``spec_url`` / ``spec_content``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    target_suite_id: Annotated[str, Field(min_length=1)]
    spec_url: str | None = None
    spec_content: str | None = None
    options: OpenApiGeneratorOptions = Field(default_factory=OpenApiGeneratorOptions)


class TestStepDraft(BaseModel):
    """One synthesised step — ``code`` is runner-executable Python (no LLM)."""

    __test__ = False  # not a pytest test class (name starts with "Test")

    order: int
    action: str
    expected: str
    code: str
    mcp_provider: str
    target_kind: TargetKind
    data: dict[str, object] | None = None


class TestCaseDraft(BaseModel):
    """One generated test case, persisted as a DRAFT :class:`TestCase`."""

    __test__ = False  # not a pytest test class (name starts with "Test")

    name: str
    description: str
    priority: Priority = Priority.P2
    source: CaseSource
    target_kind: TargetKind
    tags: list[str] = Field(default_factory=list)
    generated_from: dict[str, object] = Field(default_factory=dict)
    steps: list[TestStepDraft]


# ---------------------------------------------------------------------------
# M2 Task 3 — heuristic URL crawler generator I/O
# ---------------------------------------------------------------------------
#
# ``POST /generators/crawler`` drives ``playwright-mcp`` to BFS a site from a
# start URL, emit a navigate→no-console-error smoke case per visited page, and
# (optionally) one form-fill case per discovered ``<form>`` with Faker-seeded
# field values. Pure heuristics (NO LLM) → runs in every tier (``TierFlag.ANY``).
# Generated cases re-use the canonical :class:`CaseSource.HEURISTIC_CRAWL` +
# :class:`TargetKind.FE_WEB`; they are never redefined here.


class CrawlerAuthConfig(BaseModel):
    """Optional pre-crawl authentication. ``kind="none"`` (default) skips auth.

    The crawler does not itself perform login today — the config is captured on
    the :class:`~suitest_db.models.generator_run.GeneratorRun` for provenance and
    threaded into generated cases so a later run can replay the auth context.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: Literal["none", "cookie", "bearer", "form"] = "none"
    login_url: str | None = None
    cookie: str | None = None
    token: str | None = None
    credentials: dict[str, str] | None = None


class CrawlerOptions(BaseModel):
    """Per-request crawl bounds + emission toggles.

    ``max_depth`` / ``max_pages`` cap the BFS so a large site cannot run away;
    ``same_origin_only`` drops off-origin links from the frontier;
    ``include_form_cases`` toggles the per-``<form>`` fill cases.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    max_depth: Annotated[int, Field(ge=1, le=5)] = 2
    max_pages: Annotated[int, Field(ge=1, le=200)] = 20
    same_origin_only: bool = True
    faker_locale: str = "en_US"
    tag_prefix: str | None = None
    include_form_cases: bool = True


class CrawlerGenerateRequest(BaseModel):
    """Crawl request: a target suite + a start URL + bounds/auth."""

    model_config = ConfigDict(str_strip_whitespace=True)

    target_suite_id: Annotated[str, Field(min_length=1)]
    start_url: Annotated[str, Field(min_length=1)]
    auth: CrawlerAuthConfig = Field(default_factory=CrawlerAuthConfig)
    options: CrawlerOptions = Field(default_factory=CrawlerOptions)


class PrdGenerateRequest(BaseModel):
    """LLM-driven PRD generation (M3-6) — CLOUD/LOCAL only.

    ``prd_text`` is the requirement / user story / free text. The agent extracts
    stories and drafts happy-path + edge cases. ``default_target_kind`` decides
    the steps' default ``mcp_provider`` (steps are agentic — code is translated at
    execution time, M3-10). ``seed`` is threaded for reproducibility (M3-5).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    target_suite_id: Annotated[str, Field(min_length=1)]
    prd_text: Annotated[str, Field(min_length=1, max_length=200_000)]
    default_target_kind: TargetKind = TargetKind.CUSTOM
    seed: int | None = None
    max_cases: Annotated[int, Field(ge=1, le=100)] = 20


class GeneratorRunResponse(BaseModel):
    """Terminal SSE ``complete`` payload + the synchronous run summary."""

    generator_run_id: str
    target_suite_id: str
    cases_created: int
    public_ids: list[str]
    duration_ms: int


class GeneratorSseEvent(BaseModel):
    """One Server-Sent Event frame. ``kind`` is the SSE ``event:`` field."""

    kind: Literal["progress", "case", "complete", "error"]
    data: dict[str, object]


# ---------------------------------------------------------------------------
# M2 Task 4 — live browser recorder I/O
# ---------------------------------------------------------------------------
#
# ``POST /generators/recorder/sessions`` opens a live Playwright-MCP recording
# session; events stream over the WS gateway (``recorder:<id>`` channel) and
# ``POST .../finalize`` converts the captured event log into a DRAFT
# :class:`TestCase` (``source=RECORDER``, ``target_kind=FE_WEB``). Pure
# deterministic event→step mapping (NO LLM) → runs in every tier.


class RecorderSessionStartRequest(BaseModel):
    """Body for ``POST /generators/recorder/sessions``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: Annotated[str, Field(min_length=1)]
    start_url: Annotated[str, Field(min_length=1)]
    mcp_provider: str = "playwright-mcp"


class RecorderSessionStartResponse(BaseModel):
    """200 body — the session id + the WS room to subscribe for live events."""

    session_id: str
    ws_room: str
    browser_url: str | None = None
    expires_at: datetime


class RecorderEventKind(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    ASSERT = "assert"
    NETWORK = "network"


class RecorderEvent(BaseModel):
    """One captured interaction. ``masked`` flags secret ``type`` input.

    ``network`` carries ``{"status": int, "url": str, "method": str}`` for
    ``NETWORK`` events; a 4xx/5xx status becomes an auto-assertion step at
    finalize time.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: RecorderEventKind
    timestamp: datetime
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    masked: bool = False
    assertion: dict[str, object] | None = None
    network: dict[str, object] | None = None


class RecorderFinalizeRequest(BaseModel):
    """Body for ``POST .../finalize`` — where + how to persist the new case."""

    model_config = ConfigDict(str_strip_whitespace=True)

    target_suite_id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    description: str | None = None

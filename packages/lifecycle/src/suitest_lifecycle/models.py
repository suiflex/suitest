"""Domain models for the Sutest testing lifecycle.

Plain ``dataclasses`` (not Pydantic) on purpose: the lifecycle core runs as a
CLI / MCP subprocess with a stdlib-only footprint so it can drive *any* target
project without dragging in the API stack. All structures are fully typed (mypy
strict, no ``Any``) and serialise to/from JSON via :func:`to_jsonable`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Mode(str, Enum):
    """Which side of the target app the lifecycle drives."""

    BACKEND = "backend"
    FRONTEND = "frontend"


class TestOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class Priority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


# --------------------------------------------------------------------------- #
# Code analysis
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Endpoint:
    """A single discovered HTTP endpoint of the backend under test."""

    method: str  # GET / POST / PUT / DELETE / PATCH
    path: str  # e.g. /api/products/:id  (full, mount-prefixed)
    auth_required: bool
    source_file: str  # repo-relative path the route was found in
    handler: str = ""  # controller/handler name if recoverable
    summary: str = ""


@dataclass(frozen=True)
class Page:
    """A single discovered frontend page/route."""

    route: str  # e.g. /products/:id
    name: str  # component name, e.g. ProductFormPage
    protected: bool
    source_file: str


@dataclass
class CodeSummary:
    """Static analysis result for one target project (the ``code_summary``)."""

    project_name: str
    mode: Mode
    tech_stack: list[str] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    auth_flow: str = ""  # short human description if detected


# --------------------------------------------------------------------------- #
# PRD + test plan
# --------------------------------------------------------------------------- #
@dataclass
class PrdFeature:
    name: str
    description: str
    user_flows: list[str] = field(default_factory=list)


@dataclass
class Prd:
    """Normalised product requirement doc — mirrors TestSprite ``standard_prd``."""

    project: str
    date: str
    prepared_by: str
    product_overview: str
    core_goals: list[str]
    features: list[PrdFeature]


@dataclass
class PlanStep:
    type: str  # "action" | "assertion"
    description: str


@dataclass
class PlanCase:
    """One entry in the generated test plan (the source-of-truth test case)."""

    id: str  # TC001 ...
    title: str  # snake/sentence title
    description: str
    category: str
    priority: Priority
    steps: list[PlanStep] = field(default_factory=list)
    # Traceability back to source (Goal 8 — no dummy tests).
    source_ref: str = ""  # "POST /api/products" or "page:/products/new"
    automation_file: str = ""  # filename of the exported TCxxx.py
    tags: list[str] = field(default_factory=list)  # e.g. ["llm"] for enriched cases


# --------------------------------------------------------------------------- #
# Execution results
# --------------------------------------------------------------------------- #
@dataclass
class StepResult:
    """A recorded per-step outcome (drives the web Steps panel)."""

    index: int
    type: str  # "action" | "assertion"
    description: str
    status: TestOutcome
    duration_ms: int = 0


@dataclass
class TestResult:
    test_id: str
    title: str
    description: str
    status: TestOutcome
    duration_ms: int
    error: str = ""
    automation_file: str = ""
    artifacts: list[str] = field(default_factory=list)
    # Phase 2 — rich recording (collected from each test's sidecar JSON).
    steps: list[StepResult] = field(default_factory=list)
    video_path: str = ""
    screenshot_path: str = ""


@dataclass
class RunSummary:
    project: str
    mode: Mode
    base_url: str
    total: int
    passed: int
    failed: int
    skipped: int
    errored: int
    duration_ms: int
    results: list[TestResult] = field(default_factory=list)
    server_started: bool = False
    ready: bool = False
    ready_detail: str = ""
    startup_log_tail: str = ""

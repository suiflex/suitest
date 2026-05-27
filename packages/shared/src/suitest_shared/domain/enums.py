"""All Suitest domain enums (docs/DATA_MODEL.md §6).

Python ``StrEnum`` (3.11+) so values serialise as plain strings over JSON and
map 1:1 to Postgres ``ENUM`` types via SQLAlchemy ``Enum(..., name=...)``.

``Tier`` and ``AutonomyLevel`` stay canonical in ``suitest_core.capabilities``
(the capability resolver owns them); they are re-exported here so the data layer
has a single import site for every enum it references. Do NOT redefine them.
"""

from __future__ import annotations

from enum import StrEnum

from suitest_core.capabilities import AutonomyLevel, Tier

__all__ = [
    "AgentSessionKind",
    "ArtifactKind",
    "AutonomyLevel",
    "CaseSource",
    "CaseStatus",
    "DefectStatus",
    "DiagnosisKind",
    "DocumentKind",
    "IntegrationKind",
    "McpTransport",
    "MessageRole",
    "Priority",
    "Role",
    "RunStatus",
    "RunTrigger",
    "Severity",
    "StepOutcome",
    "TargetKind",
    "Tier",
]


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    QA = "QA"
    VIEWER = "VIEWER"


class CaseSource(StrEnum):
    MANUAL = "MANUAL"
    AI = "AI"
    MCP = "MCP"
    IMPORT = "IMPORT"
    RECORDER = "RECORDER"
    HEURISTIC_CRAWL = "HEURISTIC_CRAWL"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CaseStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class RunTrigger(StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    CI_PUSH = "CI_PUSH"
    CI_PR = "CI_PR"
    WEBHOOK = "WEBHOOK"
    AGENT = "AGENT"


class StepOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"
    PENDING = "PENDING"


class ArtifactKind(StrEnum):
    SCREENSHOT = "SCREENSHOT"
    HAR = "HAR"
    DOM_SNAPSHOT = "DOM_SNAPSHOT"
    VIDEO = "VIDEO"
    CONSOLE_LOG = "CONSOLE_LOG"
    TRACE = "TRACE"
    CUSTOM = "CUSTOM"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DefectStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    WONT_FIX = "WONT_FIX"


class IntegrationKind(StrEnum):
    GITHUB = "GITHUB"
    GITLAB = "GITLAB"
    JENKINS = "JENKINS"
    JIRA = "JIRA"
    LINEAR = "LINEAR"
    SLACK = "SLACK"
    MCP_BROWSER_USE = "MCP_BROWSER_USE"
    MCP_PLAYWRIGHT = "MCP_PLAYWRIGHT"
    MCP_CUSTOM = "MCP_CUSTOM"
    OPENAPI = "OPENAPI"
    # NEW for OSS pivot
    MCP_API = "MCP_API"
    MCP_POSTGRES = "MCP_POSTGRES"
    MCP_KUBERNETES = "MCP_KUBERNETES"
    MCP_GRAPHQL = "MCP_GRAPHQL"
    MCP_GRPC = "MCP_GRPC"
    MCP_APPIUM = "MCP_APPIUM"
    MCP_MONGO = "MCP_MONGO"
    MCP_MYSQL = "MCP_MYSQL"


class AgentSessionKind(StrEnum):
    GENERATION = "GENERATION"
    EXECUTION = "EXECUTION"
    DIAGNOSIS = "DIAGNOSIS"
    CONVERSATION = "CONVERSATION"


class MessageRole(StrEnum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class DocumentKind(StrEnum):
    PRD = "PRD"
    OPENAPI = "OPENAPI"
    URL_CRAWL = "URL_CRAWL"
    LINEAR_ISSUE = "LINEAR_ISSUE"
    NOTION_PAGE = "NOTION_PAGE"
    CUSTOM = "CUSTOM"


class TargetKind(StrEnum):
    BE_REST = "BE_REST"
    BE_GRAPHQL = "BE_GRAPHQL"
    BE_GRPC = "BE_GRPC"
    FE_WEB = "FE_WEB"
    FE_MOBILE = "FE_MOBILE"
    DATA = "DATA"
    INFRA = "INFRA"
    CUSTOM = "CUSTOM"


class DiagnosisKind(StrEnum):
    REGRESSION = "REGRESSION"
    FLAKE = "FLAKE"
    INFRA = "INFRA"
    SPEC_DRIFT = "SPEC_DRIFT"
    MANUAL_TRIAGE = "MANUAL_TRIAGE"  # ZERO tier rule-based fallback


class McpTransport(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    WS = "ws"

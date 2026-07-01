"""Request/response schemas for the lifecycle ingest endpoints (Phase 2).

The Sutest lifecycle (``suitest test``) executes tests itself, then publishes the
*completed* results here. These models carry generated cases (+ their runnable
source) and finished run results — there is no ARQ execution on this path.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Camel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


# --------------------------------------------------------------------------- #
# bulk-import (cases + steps)
# --------------------------------------------------------------------------- #
class IngestStep(_Camel):
    order: int
    action: str
    expected: str
    code: str | None = None


class IngestCase(_Camel):
    source_ref: str = Field(alias="sourceRef")
    name: str
    description: str | None = None
    preconditions: str | None = None
    priority: str = "P2"  # P1 | P2 | P3
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    automation_file_path: str | None = Field(default=None, alias="automationFilePath")
    automation_code: str | None = Field(default=None, alias="automationCode")
    generated_by: str | None = Field(default=None, alias="generatedBy")
    steps: list[IngestStep] = Field(default_factory=list)


class BulkImportBody(_Camel):
    project_id: str = Field(alias="projectId")
    suite_name: str = Field(alias="suiteName")
    mode: str = "backend"  # backend | frontend -> target_kind / mcp_provider defaults
    cases: list[IngestCase] = Field(default_factory=list)


class ImportedCase(_Camel):
    source_ref: str = Field(alias="sourceRef")
    case_id: str = Field(alias="caseId")
    public_id: str = Field(alias="publicId")
    created: bool


class BulkImportResult(_Camel):
    suite_id: str = Field(alias="suiteId")
    imported: list[ImportedCase] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# runs/ingest (completed run)
# --------------------------------------------------------------------------- #
class IngestRunStep(_Camel):
    order: int
    type: str = "action"
    description: str = ""
    outcome: str = "PASSED"  # PASSED | FAILED | SKIPPED | ERROR
    duration_ms: int | None = Field(default=None, alias="durationMs")
    screenshot: str = ""  # per-step screenshot URL (drives "Preview: Step N")


class IngestArtifact(_Camel):
    kind: str  # VIDEO | SCREENSHOT | CONSOLE_LOG | ...
    url: str  # file:// or s3:// already-resolved location
    mime_type: str = Field(default="application/octet-stream", alias="mimeType")
    size_bytes: int = Field(default=0, alias="sizeBytes")


class IngestResult(_Camel):
    name: str = ""  # case name — the idempotency/match key (source_ref is not unique)
    source_ref: str = Field(default="", alias="sourceRef")
    outcome: str = "PASSED"
    duration_ms: int = Field(default=0, alias="durationMs")
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    steps: list[IngestRunStep] = Field(default_factory=list)
    artifacts: list[IngestArtifact] = Field(default_factory=list)


class RunIngestBody(_Camel):
    project_id: str = Field(alias="projectId")
    suite_name: str = Field(alias="suiteName")
    name: str
    env: str = "staging"
    branch: str | None = None
    commit_sha: str | None = Field(default=None, alias="commitSha")
    results: list[IngestResult] = Field(default_factory=list)


class RunIngestResult(_Camel):
    run_id: str = Field(alias="runId")
    status: str
    total: int
    passed: int
    failed: int

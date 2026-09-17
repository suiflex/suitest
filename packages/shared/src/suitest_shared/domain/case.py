"""Test case / step domain models (docs/DATA_MODEL.md §2.2).

``TestStep.executable`` is a **computed** domain method — it depends on the
workspace LLM readiness at read time, so it is intentionally NOT a DB column (see
DATA_MODEL.md §3.4 / §5).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import Field

from suitest_shared.domain.base import DomainModel
from suitest_shared.domain.enums import (
    CaseSource,
    CaseStatus,
    Priority,
    TargetKind,
)


class TestStep(DomainModel):
    __test__ = False  # not a pytest test class

    id: str
    case_id: str
    order: int
    action: str
    expected: str
    code: str | None = None
    data: dict[str, Any] | None = None
    mcp_provider: str = "playwright-mcp"
    target_kind: TargetKind = TargetKind.FE_WEB

    def executable(self, llm_ready: bool) -> bool:
        """A coded step is runnable; action-only steps require a validated LLM."""
        if self.code:
            return True
        return llm_ready and bool(self.action)


class TestCase(DomainModel):
    __test__ = False  # not a pytest test class

    id: str
    suite_id: str
    public_id: str
    name: str
    description: str | None = None
    preconditions: str | None = None
    source: CaseSource
    status: CaseStatus = CaseStatus.ACTIVE
    priority: Priority = Priority.P2
    owner_id: uuid.UUID | None = None
    generated_by: str | None = None
    generated_from: dict[str, Any] | None = None
    estimated_ms: int | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    deleted_at: dt.datetime | None = None
    steps: list[TestStep] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

"""Test case / step domain models (docs/DATA_MODEL.md §2.2).

``TestStep.executable`` is a **computed** domain method — it depends on the
workspace tier at read time, so it is intentionally NOT a DB column (see
DATA_MODEL.md §3.4 / §5).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from suitest_shared.domain.base import DomainModel
from suitest_shared.domain.enums import (
    CaseSource,
    CaseStatus,
    Priority,
    TargetKind,
    Tier,
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

    def executable(self, tier: Tier) -> bool:
        """A step is executable iff it has explicit ``code`` (deterministic), OR
        the workspace has an LLM tier (LOCAL/CLOUD) plus an ``action`` to translate.
        """
        if self.code:
            return True
        return tier in (Tier.LOCAL, Tier.CLOUD) and bool(self.action)


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
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    steps: list[TestStep] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

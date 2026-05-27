"""Test case + step response DTOs (docs/API.md §3.3).

``TestStepPublic.executable`` is a plain field — NOT a Pydantic computed property —
set at construction time from the workspace's effective capability tier (the
domain rule ``suitest_shared.domain.case.TestStep.executable(tier)``). The router
resolves the tier once per request and stamps every step.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import CaseSource, CaseStatus, Priority, TargetKind


class TestStepPublic(BaseModel):
    __test__ = False  # not a pytest test class

    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    order: int
    action: str
    expected: str
    code: str | None = None
    data: dict[str, Any] | None = None
    mcp_provider: str
    target_kind: TargetKind
    executable: bool


class TestCaseListItem(BaseModel):
    """List row — metadata only, no steps (docs/API.md §3.3)."""

    __test__ = False  # not a pytest test class

    model_config = ConfigDict(from_attributes=True)

    id: str
    suite_id: str
    public_id: str
    name: str
    description: str | None = None
    source: CaseSource
    status: CaseStatus
    priority: Priority
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class TestCaseDetail(TestCaseListItem):
    """Detail — adds steps (with ``executable``) + tags."""

    __test__ = False  # not a pytest test class

    preconditions: str | None = None
    steps: list[TestStepPublic] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

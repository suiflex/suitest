"""Requirement + traceability response DTOs (docs/API.md §3.7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from suitest_shared.domain.enums import CaseSource, CaseStatus, DefectStatus, Severity


class RequirementListItem(BaseModel):
    """List row with a computed ``link_count`` (number of linked cases)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    public_id: str
    title: str
    description: str | None = None
    source: str | None = None
    external_url: str | None = None
    link_count: int
    created_at: datetime
    updated_at: datetime


class RequirementDetail(BaseModel):
    """Detail with the public ids of linked cases + linked defects."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    public_id: str
    title: str
    description: str | None = None
    source: str | None = None
    external_url: str | None = None
    case_public_ids: list[str] = Field(default_factory=list)
    defect_public_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# -- traceability matrix (docs/API.md §3.7) -------------------------------


class MatrixRequirement(BaseModel):
    """One requirement row: its public id, title, and linked test/defect public ids."""

    id: str
    title: str
    tests: list[str] = Field(default_factory=list)
    defects: list[str] = Field(default_factory=list)


class MatrixCase(BaseModel):
    __test__ = False  # not a pytest test class

    id: str
    name: str
    source: CaseSource
    status: CaseStatus


class MatrixDefect(BaseModel):
    id: str
    title: str
    severity: Severity
    status: DefectStatus


class TraceabilityMatrix(BaseModel):
    """``GET /traceability/matrix`` — grid view payload (docs/API.md §3.7)."""

    requirements: list[MatrixRequirement] = Field(default_factory=list)
    cases: list[MatrixCase] = Field(default_factory=list)
    defects: list[MatrixDefect] = Field(default_factory=list)

"""Requirement + traceability request / response DTOs (docs/API.md §3.7).

Write surface (M1d-6): ``RequirementCreate``, ``RequirementUpdate`` and
``RequirementLinkCreate``. All write payloads honour ``extra="forbid"`` so
caller-side typos surface as 422 rather than being silently dropped. JSON wire
field names use the camelCase aliases documented in ``docs/API.md §3.7`` while
Python attributes stay snake_case.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

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


# ---------------------------------------------------------------------------
# M1d-6 write DTOs
# ---------------------------------------------------------------------------


_WRITE_CONFIG = ConfigDict(
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


class RequirementCreate(BaseModel):
    """Body for ``POST /requirements`` (docs/API.md §3.7).

    ``project_id`` is workspace-scoped (cross-workspace ids return 404). The
    ``REQ-N`` ``public_id`` is assigned by the ``before_insert`` listener via
    ``generate_public_id`` (docs/DATA_MODEL §8) — never accepted from the caller.
    """

    model_config = _WRITE_CONFIG

    project_id: Annotated[str, Field(min_length=1, alias="projectId")]
    title: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    source: str | None = None
    external_url: str | None = Field(default=None, alias="externalUrl")


class RequirementUpdate(BaseModel):
    """Body for ``PATCH /requirements/:id`` — metadata patch.

    All fields optional; only ``model_dump(exclude_unset=True)`` keys are
    applied. Sending ``null`` explicitly clears the field (description / source
    / external_url are nullable in the model).
    """

    model_config = _WRITE_CONFIG

    title: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    description: str | None = None
    source: str | None = None
    external_url: str | None = Field(default=None, alias="externalUrl")


class RequirementLinkCreate(BaseModel):
    """Body for ``POST /requirements/:id/links`` — ``{ "testCaseId": "..." }``.

    Accepts both ``test_case_id`` (Pythonic) and ``testCaseId`` / ``caseId``
    (docs/API.md §3.7 wire shape) for FE compatibility.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    test_case_id: Annotated[str, Field(min_length=1, alias="testCaseId")]

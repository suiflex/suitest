"""Suite write DTOs (docs/API.md §3.4 — M1d-4).

Read-side ``SuitePublic`` lives in :mod:`suitest_api.schemas.project` for
historical reasons (the suite read router was the first consumer). Write
payloads use camelCase JSON aliases per ``docs/API.md §3.4`` while Python
attributes stay snake_case. ``extra="forbid"`` so typos in the body raise loud
422s rather than being silently swallowed (caller-side fix is cheaper than a
half-applied PATCH).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

_WRITE_CONFIG = ConfigDict(
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


class SuiteCreate(BaseModel):
    """Body for ``POST /suites``.

    ``order`` defaults to ``0``; callers usually leave it blank and let the
    repository's ``order ASC, created_at DESC`` ordering position the suite.
    """

    model_config = _WRITE_CONFIG

    project_id: Annotated[str, Field(min_length=1, alias="projectId")]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: str | None = None
    order: int = Field(default=0, ge=0)


class SuiteUpdate(BaseModel):
    """Body for ``PATCH /suites/:id`` (docs/API.md §3.4).

    All fields optional; only ``model_dump(exclude_unset=True)`` keys are
    applied. ``case_order`` (when present) drives an atomic reorder of every
    active case in the suite — the submitted id set must match the live set
    exactly or a 400 with ``details.missing`` / ``details.unknown`` lands.
    """

    model_config = _WRITE_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    description: str | None = None
    order: int | None = Field(default=None, ge=0)
    case_order: list[str] | None = Field(default=None, alias="caseOrder")

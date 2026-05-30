"""Project + suite response/write DTOs (docs/API.md §3.2, §3.4).

Write surface (M1d-5) covers ``POST /projects``, ``PATCH /projects/:id``,
``DELETE /projects/:id?confirmCascade=...``, and ``POST /projects/:id/restore``.
All write payloads use camelCase JSON aliases per ``docs/API.md §3.2`` while
Python attributes stay snake_case. ``extra="forbid"`` so typos in the body
raise loud 422s rather than being silently swallowed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

_WRITE_CONFIG = ConfigDict(
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


class ProjectPublic(BaseModel):
    """A project, workspace-scoped (docs/API.md §3.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    slug: str
    name: str
    description: str | None = None
    gating_suite_id: str | None = None
    default_mcp_routing: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SuitePublic(BaseModel):
    """A suite with its non-deleted ``case_count`` (set by the service)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str | None = None
    order: int
    case_count: int
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    """Body for ``POST /projects`` (docs/API.md §3.2).

    ``slug`` is optional — when omitted the service derives it from ``name``
    via :func:`suitest_api.utils.slug.slugify` and retries with a ``-2``
    suffix once on collision before bubbling 409.
    """

    model_config = _WRITE_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=120)]
    slug: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    description: str | None = None


class ProjectUpdate(BaseModel):
    """Body for ``PATCH /projects/:id`` (docs/API.md §3.2).

    Slug is **immutable** post-create — attempting to PATCH it raises a 400
    ``IMMUTABLE_SLUG``. ``gating_suite_id`` must reference a suite that lives
    in this project (cross-project assignments raise 400
    ``INVALID_GATING_SUITE``). All fields optional; only
    ``model_dump(exclude_unset=True)`` keys are applied.
    """

    model_config = _WRITE_CONFIG

    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    description: str | None = None
    gating_suite_id: str | None = Field(default=None, alias="gatingSuiteId")
    default_mcp_routing: dict[str, Any] | None = Field(default=None, alias="defaultMcpRouting")
    # The router rejects ``slug`` explicitly via the validator below so the
    # 400 envelope says ``IMMUTABLE_SLUG`` rather than the generic Pydantic
    # ``extra_forbidden``. Keeping the field present (with a sentinel) lets
    # the service detect the attempt and raise the typed error.
    slug: str | None = Field(default=None)

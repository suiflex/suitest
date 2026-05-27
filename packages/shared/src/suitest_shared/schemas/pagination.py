"""Cursor pagination wrappers shared across the read-only REST endpoints.

The wire shape is ``{"items": [...], "meta": {"nextCursor": <str|null>, "limit": N}}``.
``nextCursor`` is an opaque keyset token (see ``suitest_db.repositories.cursor``);
clients hand it back verbatim on the next request. ``Page`` is a PEP 695 generic so
each router declares its element type (``Page[ProjectPublic]`` etc.).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PageMeta(BaseModel):
    """Pagination metadata: the next cursor (``null`` when exhausted) + page size."""

    model_config = ConfigDict(populate_by_name=True)

    next_cursor: str | None = Field(default=None, alias="nextCursor")
    limit: int


class Page[T](BaseModel):
    """A single keyset page of ``items`` plus the cursor for the following page."""

    items: list[T]
    meta: PageMeta


class CursorParams(BaseModel):
    """Common cursor query model: opaque ``cursor`` token + bounded ``limit``."""

    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)

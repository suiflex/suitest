"""Pydantic schemas for Workspace and Suite Variables / Secrets."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

_WRITE_CONFIG = ConfigDict(
    populate_by_name=True,
    str_strip_whitespace=True,
    extra="forbid",
)


class VariablePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    key: str
    is_secret: bool = Field(alias="isSecret")
    value: str | None = None
    has_value: bool = Field(alias="hasValue")
    description: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class VariableCreate(BaseModel):
    model_config = _WRITE_CONFIG

    key: Annotated[str, Field(min_length=1, max_length=120)]
    value: str | None = None
    is_secret: bool = Field(default=False, alias="isSecret")
    description: str | None = None


class VariableUpdate(BaseModel):
    model_config = _WRITE_CONFIG

    key: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    value: str | None = None
    is_secret: bool | None = Field(default=None, alias="isSecret")
    description: str | None = None


class ResolvedVariableItem(BaseModel):
    """Resolved variable payload used by runner, step preview, and UI hover tooltip."""

    model_config = ConfigDict(populate_by_name=True)

    key: str
    value: str | None = None
    is_secret: bool = Field(alias="isSecret")
    has_value: bool = Field(alias="hasValue")
    source_scope: str = Field(alias="sourceScope")  # "workspace" | "suite"
    source_id: str = Field(alias="sourceId")  # workspace_id or suite_id
    description: str | None = None

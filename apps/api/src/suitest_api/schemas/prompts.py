"""Workspace prompt-fork API schemas (M5-3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PromptForkPublic(BaseModel):
    """One versioned fork of a prompt for a workspace."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    prompt_name: str = Field(serialization_alias="promptName")
    base_version: str = Field(serialization_alias="baseVersion")
    fork_version: int = Field(serialization_alias="forkVersion")
    label: str | None = None
    is_active: bool = Field(serialization_alias="isActive")
    hash: str
    content: str | None = None
    created_at: datetime = Field(serialization_alias="createdAt")


class PromptDefaultPublic(BaseModel):
    """A file-based default prompt + whether the workspace forks it."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    base_version: str = Field(serialization_alias="baseVersion")
    has_active_fork: bool = Field(serialization_alias="hasActiveFork")
    active_fork_version: int | None = Field(default=None, serialization_alias="activeForkVersion")


class PromptListEnvelope(BaseModel):
    """``GET /prompts`` — every overridable default + its fork status."""

    items: list[PromptDefaultPublic] = Field(default_factory=list)


class PromptDetailPublic(BaseModel):
    """``GET /prompts/:name`` — default content + the workspace's fork history."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    base_version: str = Field(serialization_alias="baseVersion")
    default_content: str = Field(serialization_alias="defaultContent")
    forks: list[PromptForkPublic] = Field(default_factory=list)


class PromptForkCreate(BaseModel):
    """``POST /prompts/:name/forks`` body."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=120)
    base_version: str = Field(default="v1", max_length=32)
    activate: bool = True


class ExperimentVariantStats(BaseModel):
    """Per-variant impression / success counters + conversion (M5-4)."""

    model_config = ConfigDict(populate_by_name=True)

    variant: str
    override_id: str | None = Field(default=None, serialization_alias="overrideId")
    impressions: int
    successes: int
    conversion_pct: float = Field(serialization_alias="conversionPct")


class PromptExperimentPublic(BaseModel):
    """One prompt A/B experiment + live stats."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    prompt_name: str = Field(serialization_alias="promptName")
    status: str
    split_pct: int = Field(serialization_alias="splitPct")
    variant_a: ExperimentVariantStats = Field(serialization_alias="variantA")
    variant_b: ExperimentVariantStats = Field(serialization_alias="variantB")
    winner: str | None = None
    created_at: datetime = Field(serialization_alias="createdAt")


class PromptExperimentListEnvelope(BaseModel):
    items: list[PromptExperimentPublic] = Field(default_factory=list)


class PromptExperimentCreateBody(BaseModel):
    """``POST /prompt-experiments`` body."""

    model_config = ConfigDict(extra="forbid")

    prompt_name: str = Field(max_length=120)
    variant_a_override_id: str | None = None
    variant_b_override_id: str | None = None
    split_pct: int = Field(default=50, ge=0, le=100)


class ExperimentOutcomeBody(BaseModel):
    """``POST /prompt-experiments/:id/outcome`` body."""

    model_config = ConfigDict(extra="forbid")

    variant: str = Field(pattern="^[AB]$")
    success: bool = True

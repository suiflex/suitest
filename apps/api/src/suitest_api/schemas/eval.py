"""Eval harness API schemas (M4-8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvalRunRequest(BaseModel):
    """``POST /eval/runs`` body."""

    model_config = ConfigDict(extra="forbid")

    suite_name: str = Field(default="default", max_length=120)


class EvalFixtureResult(BaseModel):
    """Per-fixture pass/fail row in the report."""

    suite: str
    fixture: str
    passed: bool
    detail: str


class EvalRunPublic(BaseModel):
    """``GET /eval/runs/:id`` + ``POST /eval/runs`` response."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    suite_name: str = Field(serialization_alias="suiteName")
    fixtures_count: int = Field(serialization_alias="fixturesCount")
    passed: int
    failed: int
    model_id: str = Field(serialization_alias="modelId")
    run_at: datetime = Field(serialization_alias="runAt")
    results: list[EvalFixtureResult] = Field(default_factory=list)

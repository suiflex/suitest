"""Analytics response DTOs (docs/API.md §3.8).

Field aliases use the camelCase wire names from API.md (``passRate``, ``runCount``,
…). ``model_config`` enables ``populate_by_name`` so the service builds them with
snake_case kwargs while the JSON serialises camelCase (``by_alias`` at the router).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KpisOut(BaseModel):
    """``GET /analytics/kpis`` → pass rate, run count, avg duration, open defects."""

    model_config = ConfigDict(populate_by_name=True)

    pass_rate: float = Field(alias="passRate")
    run_count: int = Field(alias="runCount")
    avg_duration_ms: float = Field(alias="avgDurationMs")
    defects_open: int = Field(alias="defectsOpen")


class PassRatePoint(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: str
    pass_rate: float = Field(alias="passRate")


class PassRateSeriesOut(BaseModel):
    """``GET /analytics/pass-rate`` → ascending time series + total sample size."""

    series: list[PassRatePoint] = Field(default_factory=list)
    total: int


class CoverageSuiteRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    suite_id: str = Field(alias="suiteId")
    name: str
    total: int
    covered: int
    coverage: float


class CoverageRequirementRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    requirement_id: str = Field(alias="requirementId")
    total: int
    covered: int


class CoverageOut(BaseModel):
    """``GET /analytics/coverage`` → coverage by suite + by requirement."""

    model_config = ConfigDict(populate_by_name=True)

    by_suite: list[CoverageSuiteRow] = Field(default_factory=list, alias="bySuite")
    by_requirement: list[CoverageRequirementRow] = Field(
        default_factory=list, alias="byRequirement"
    )


class FlakyCaseOut(BaseModel):
    __test__ = False  # not a pytest test class

    model_config = ConfigDict(populate_by_name=True)

    case_id: str = Field(alias="caseId")
    public_id: str = Field(alias="publicId")
    flake_rate: float = Field(alias="flakeRate")
    sample_size: int = Field(alias="sampleSize")


class HeatmapCell(BaseModel):
    """One run-count cell in the day x hour grid."""

    day: datetime
    hour: int
    count: int


class ReadinessBlocker(BaseModel):
    type: str
    message: str
    ref: str | None = None


class ReadinessOut(BaseModel):
    """``GET /analytics/readiness`` → deterministic release-readiness score."""

    score: int
    blockers: list[ReadinessBlocker] = Field(default_factory=list)

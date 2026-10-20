"""Four-dimensional risk inputs and explanations, independent of model calls."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

RiskLevel = Literal["low", "medium", "high", "unknown"]
RiskCategory = Literal["weather", "budget", "transport", "fatigue"]
RiskOptimizationStatus = Literal["applied", "needs_confirmation"]


class RiskModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RiskWeather(RiskModel):
    data_kind: Literal["forecast", "seasonal_baseline", "unavailable"] = "unavailable"
    observed_at: AwareDatetime | None = None
    forecast_end_date: date | None = None
    precipitation_mm: float | None = Field(default=None, ge=0)
    precipitation_probability_pct: float | None = Field(default=None, ge=0, le=100)
    high_c: float | None = None
    low_c: float | None = None
    wind_speed_kph: float | None = Field(default=None, ge=0)
    condition_code: int | None = None
    source_label: str = Field(default="手动录入，未经外部核验", max_length=300)
    source_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def temperatures(self):
        if (
            self.high_c is not None
            and self.low_c is not None
            and self.high_c < self.low_c
        ):
            raise ValueError("最高温不能低于最低温")
        return self


class RiskCost(RiskModel):
    item_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    amount_cny: float | None = Field(default=None, ge=0, le=1e10)
    upper_cny: float | None = Field(default=None, ge=0, le=1e10)
    basis: Literal["estimate", "quote", "paid", "unknown"] = "estimate"
    source_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def amount_range(self):
        if self.upper_cny is not None and (
            self.amount_cny is None or self.upper_cny < self.amount_cny
        ):
            raise ValueError("费用上界必须不小于已填金额")
        return self


class RiskConnection(RiskModel):
    name: str = Field(min_length=1, max_length=200)
    available_minutes: float = Field(ge=-10080, le=10080)
    required_minutes: float = Field(gt=0, le=1440)
    entity_ids: list[str] = Field(default_factory=list, max_length=100)


class RiskTransport(RiskModel):
    item_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    route_status: Literal["ready", "estimated", "missing"] = "missing"
    duration_minutes: float | None = Field(default=None, ge=0, le=10080)
    available_minutes: float | None = Field(default=None, ge=0, le=10080)
    source_ids: list[str] = Field(default_factory=list, max_length=100)


class RiskDay(RiskModel):
    day_id: str = Field(min_length=1, max_length=100)
    date: date
    destination: str = Field(default="", max_length=200)
    # None means unmeasured; zero means explicitly zero, never inferred from absence.
    outdoor_minutes: float | None = Field(default=None, ge=0, le=1440)
    active_minutes: float | None = Field(default=None, ge=0, le=2880)
    walking_km: float | None = Field(default=None, ge=0, le=200)
    rest_minutes: float | None = Field(default=None, ge=0, le=1440)
    # Imported provenance.  None keeps legacy/manual payloads on the old
    # ``transport_complete`` contract; dataset imports always set a value.
    transport_coverage: Literal[
        "verified", "estimated", "missing", "none_required", "unknown"
    ] | None = None
    walking_km_estimated: bool = False
    active_minutes_estimated: bool = False
    rest_minutes_estimated: bool = False
    outdoor_minutes_estimated: bool = False
    weather: RiskWeather = Field(default_factory=RiskWeather)
    transport_complete: bool = False
    transports: list[RiskTransport] = Field(default_factory=list, max_length=200)
    connections: list[RiskConnection] = Field(default_factory=list, max_length=200)
    entity_ids: list[str] = Field(default_factory=list, max_length=300)


class RiskLimits(RiskModel):
    max_daily_walking_km: float = Field(default=8, gt=0, le=100)
    max_daily_active_hours: float = Field(default=8, gt=0, le=24)
    min_daily_rest_minutes: float = Field(default=45, ge=0, le=480)


class RiskAssessmentInput(RiskModel):
    title: str = Field(default="旅行方案", min_length=1, max_length=200)
    is_example: bool = False
    budget_cap_cny: float | None = Field(default=None, gt=0, le=1e10)
    # All cost items must use the same whole-party, whole-trip CNY scope.
    costs_complete: bool = False
    costs: list[RiskCost] = Field(default_factory=list, max_length=1000)
    days: list[RiskDay] = Field(min_length=1, max_length=31)
    limits: RiskLimits = Field(default_factory=RiskLimits)

    @model_validator(mode="after")
    def unique_inputs(self):
        for values, message in (
            ([d.day_id for d in self.days], "日期记录 ID 不能重复"),
            ([c.item_id for c in self.costs], "费用项 ID 不能重复"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(message)
        dates = [d.date for d in self.days]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("日期必须按顺序排列且不能重复；同日多目的地请合并为一日")
        transport_ids = [t.item_id for d in self.days for t in d.transports]
        if len(transport_ids) != len(set(transport_ids)):
            raise ValueError("交通项 ID 不能重复")
        return self


class RiskEvidence(RiskModel):
    field: str
    label: str
    value: float | str | bool | None
    unit: str = ""
    source_label: str = "录入或导入的方案数据，未经本次评估外部核验"
    source_ids: list[str] = Field(default_factory=list)
    observed_at: AwareDatetime | None = None


class RiskCalculation(RiskModel):
    expression: str
    result: float | str | None
    unit: str = ""


class RiskExplanation(RiskModel):
    data: list[RiskEvidence] = Field(min_length=1)
    calculation: list[RiskCalculation] = Field(min_length=1)
    rule: str
    risk_level: RiskLevel
    explanation: str


class RiskFinding(RiskModel):
    rule_id: str
    level: RiskLevel
    title: str
    reason: str
    suggestion: str
    explanation: RiskExplanation
    day_id: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class RiskDimensionResult(RiskModel):
    category: RiskCategory
    label: str
    level: RiskLevel
    coverage: Literal["complete", "partial", "missing"]
    summary: str
    explanation: RiskExplanation
    metrics: dict[str, float | str | None] = Field(default_factory=dict)
    findings: list[RiskFinding] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    estimated_data: list[str] = Field(default_factory=list)


class RiskAssessment(RiskModel):
    engine_version: Literal["travel-risk.v2"] = "travel-risk.v2"
    assessed_at: AwareDatetime
    title: str
    is_example: bool
    input_origin: Literal["manual", "journeypilot"]
    bundle_id: str | None = None
    overall_level: RiskLevel
    data_complete: bool
    summary: str
    dimensions: list[RiskDimensionResult]
    assumptions: list[str]


class RiskOptimizationProposal(RiskModel):
    """One reviewable change suggested by the deterministic optimizer."""

    proposal_id: str
    category: RiskCategory
    rule_id: str | None = None
    day_id: str | None = None
    field: str
    title: str
    reason: str
    before: float | str | None = None
    after: float | str | None = None
    unit: str = ""
    status: RiskOptimizationStatus
    requires_confirmation: bool = False


class RiskOptimizationResult(RiskModel):
    """Before/after result for one optimization loop iteration."""

    engine_version: Literal["travel-risk.v2"] = "travel-risk.v2"
    original_input: RiskAssessmentInput
    optimized_input: RiskAssessmentInput
    before: RiskAssessment
    after: RiskAssessment
    proposals: list[RiskOptimizationProposal] = Field(default_factory=list)
    applied_count: int = 0
    pending_count: int = 0
    summary: str

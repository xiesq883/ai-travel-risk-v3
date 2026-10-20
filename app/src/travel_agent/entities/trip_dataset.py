"""Versioned, per-day trip dataset for downstream risk assessment.

This contract is a *projection* of an immutable Delivery Bundle.  It never
calls a model or an external provider: every number in it either comes from a
bundle entity/fact or is produced by an explicitly named program estimate.
Missing values stay ``None``; no field is silently replaced by zero.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .contract_base import StrictModel

DATASET_SCHEMA_VERSION = "trip-dataset.v1"
DATASET_MIN_READER_VERSION = "trip-dataset.v1"

SourceType = Literal[
    "official_api",
    "third_party_api",
    "public_web",
    "program_estimate",
    "unknown",
]
PriceType = Literal["actual_quote", "estimated", "unknown"]
Confidence = Literal["verified", "estimated", "unverified", "unknown"]
CostCategory = Literal["transport", "dining", "lodging", "ticket", "other"]
MealType = Literal["breakfast", "lunch", "dinner", "snack", "other"]
RouteMode = Literal[
    "flight",
    "high_speed_rail",
    "train",
    "coach",
    "ferry",
    "metro",
    "bus",
    "tram",
    "taxi",
    "ride_hailing",
    "drive",
    "bike",
    "walk",
    "other",
    "unknown",
]


def _check_price(price_type: str, amount: Optional[float], label: str) -> None:
    if price_type == "unknown" and amount is not None:
        raise ValueError(f"{label}: unknown price cannot carry an amount")
    if price_type != "unknown" and amount is None:
        raise ValueError(f"{label}: a priced item requires an amount")


def _check_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source url must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("source url must not embed credentials")
    return value


class DatasetEndpoint(StrictModel):
    name: str = Field(min_length=1)
    place_id: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class SourceCitation(StrictModel):
    """One traceable source record, as referenced by field-level source_ids."""

    citation_id: str = Field(min_length=1)
    source_record_id: Optional[str] = None
    source_type: SourceType
    provider: str = ""
    title: str = ""
    url: Optional[str] = None
    retrieved_at: Optional[AwareDatetime] = None
    published_at: Optional[AwareDatetime] = None
    excerpt: str = ""
    confidence: Confidence = "unverified"
    fact_assertion_ids: List[str] = Field(default_factory=list)

    _url = field_validator("url")(_check_url)


class Assumption(StrictModel):
    code: str = Field(min_length=1)
    text: str = Field(min_length=1)


class DataSourceStatus(StrictModel):
    """Configuration state of one external capability, never a successful call."""

    source_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["weather", "search", "route", "place", "flight", "hotel"]
    configured: bool
    capabilities: List[str] = Field(default_factory=list)
    required_env: List[str] = Field(default_factory=list)
    note: str = ""


class TripParty(StrictModel):
    adults: int = Field(default=0, ge=0)
    children: int = Field(default=0, ge=0)
    elderly_companions: bool = False
    accessibility_required: bool = False

    @property
    def total(self) -> int:
        return self.adults + self.children


class TripPreferences(StrictModel):
    style: Optional[str] = None
    interests: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list)


class TripBasics(StrictModel):
    run_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    itinerary_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=0)
    fact_data_revision: int = Field(ge=0)
    weather_data_revision: int = Field(ge=0)
    title: str = Field(min_length=1)
    origin: Optional[DatasetEndpoint] = None
    destination_ids: List[str] = Field(default_factory=list)
    destination_names: List[str] = Field(default_factory=list)
    start_date: Date
    end_date: Date
    timezone: Optional[str] = None
    party: TripParty = Field(default_factory=TripParty)
    preferences: TripPreferences = Field(default_factory=TripPreferences)

    @model_validator(mode="after")
    def validate_dates(self) -> "TripBasics":
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        return self


class DatasetCompatibility(StrictModel):
    min_reader_version: Literal["trip-dataset.v1"] = DATASET_MIN_READER_VERSION
    legacy_bundle_contract: str = ""
    legacy_workspace_contract: str = ""
    legacy_fact_contract: str = ""
    legacy_weather_contract: str = ""
    notes: List[str] = Field(default_factory=list)


class DayWeather(StrictModel):
    data_kind: Literal["forecast", "seasonal_baseline", "observation", "unavailable"]
    forecast_end_date: Optional[Date] = None
    condition_label: Optional[str] = None
    high_c: Optional[float] = None
    low_c: Optional[float] = None
    precipitation_mm: Optional[float] = Field(default=None, ge=0)
    precipitation_probability_pct: Optional[float] = Field(default=None, ge=0, le=100)
    wind_speed_kph: Optional[float] = Field(default=None, ge=0)
    condition_code: Optional[int] = None
    retrieved_at: Optional[AwareDatetime] = None
    source_ids: List[str] = Field(default_factory=list)
    confidence: Confidence = "unknown"


class Activity(StrictModel):
    activity_id: str = Field(min_length=1)
    entity_type: Literal["visit_stop", "custom_block"]
    name: str = Field(min_length=1)
    place_id: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    visit_type: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    duration_minutes: Optional[float] = Field(default=None, ge=0)
    ticket_cny: Optional[float] = Field(default=None, ge=0)
    price_type: PriceType = "unknown"
    price_basis: Optional[str] = None
    outdoor: Optional[bool] = None
    source_ids: List[str] = Field(default_factory=list)
    retrieved_at: Optional[AwareDatetime] = None
    confidence: Confidence = "unknown"
    assumptions: List[Assumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_price(self) -> "Activity":
        _check_price(self.price_type, self.ticket_cny, "activity ticket")
        return self


class Meal(StrictModel):
    meal_id: str = Field(min_length=1)
    meal_type: MealType
    status: Literal["planned", "not_planned", "unknown"] = "unknown"
    restaurant_name: Optional[str] = None
    place_id: Optional[str] = None
    address: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    duration_minutes: Optional[float] = Field(default=None, ge=0)
    party_size: Optional[int] = Field(default=None, ge=0)
    per_person_cny: Optional[float] = Field(default=None, ge=0)
    total_cny: Optional[float] = Field(default=None, ge=0)
    price_type: PriceType = "unknown"
    price_basis: Optional[str] = None
    source_ids: List[str] = Field(default_factory=list)
    retrieved_at: Optional[AwareDatetime] = None
    confidence: Confidence = "unknown"
    assumptions: List[Assumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_price(self) -> "Meal":
        # A per-person reference can be known while the table total stays
        # unknown (party size missing).  Only the total is the priced amount.
        _check_price(self.price_type, self.total_cny, "meal")
        return self


class LodgingDatasetItem(StrictModel):
    stay_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    place_id: Optional[str] = None
    address: Optional[str] = None
    check_in_date: Date
    check_out_date: Date
    nights: int = Field(ge=1)
    room_count: Optional[int] = Field(default=None, ge=1)
    guest_count: Optional[int] = Field(default=None, ge=1)
    nightly_cny: Optional[float] = Field(default=None, ge=0)
    total_cny: Optional[float] = Field(default=None, ge=0)
    price_type: PriceType = "unknown"
    price_basis: Optional[str] = None
    availability_status: Literal["confirmed", "needs_confirmation", "unavailable", "unknown"] = "unknown"
    includes: List[str] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    retrieved_at: Optional[AwareDatetime] = None
    confidence: Confidence = "unknown"
    assumptions: List[Assumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stay(self) -> "LodgingDatasetItem":
        expected = (self.check_out_date - self.check_in_date).days
        if expected < 1 or expected != self.nights:
            raise ValueError("nights must equal check_out_date minus check_in_date")
        _check_price(self.price_type, self.total_cny if self.total_cny is not None else self.nightly_cny, "lodging")
        if self.price_type != "actual_quote" and self.availability_status == "confirmed":
            raise ValueError("only an actual quote may claim confirmed availability")
        return self


class RouteStep(StrictModel):
    mode: RouteMode
    from_name: str = ""
    to_name: str = ""
    line_name: Optional[str] = None
    service_number: Optional[str] = None
    departure_at: Optional[datetime] = None
    arrival_at: Optional[datetime] = None
    duration_minutes: Optional[float] = Field(default=None, ge=0)
    distance_m: Optional[float] = Field(default=None, ge=0)
    fare_cny: Optional[float] = Field(default=None, ge=0)


class RouteSegment(StrictModel):
    route_id: str = Field(min_length=1)
    transport_leg_id: Optional[str] = None
    from_endpoint: DatasetEndpoint
    to_endpoint: DatasetEndpoint
    mode: RouteMode
    route_status: Literal["ready", "estimated", "missing"] = "missing"
    departure_at: Optional[datetime] = None
    arrival_at: Optional[datetime] = None
    duration_minutes: Optional[float] = Field(default=None, ge=0)
    distance_m: Optional[float] = Field(default=None, ge=0)
    distance_source: SourceType = "unknown"
    distance_method: Optional[str] = None
    fare_cny: Optional[float] = Field(default=None, ge=0)
    price_type: PriceType = "unknown"
    price_basis: Optional[str] = None
    transfer_count: int = Field(default=0, ge=0)
    steps: List[RouteStep] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    retrieved_at: Optional[AwareDatetime] = None
    confidence: Confidence = "unknown"
    assumptions: List[Assumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_route(self) -> "RouteSegment":
        _check_price(self.price_type, self.fare_cny, "route fare")
        if self.distance_m is None and self.distance_method is not None:
            raise ValueError("a distance method requires a distance")
        return self


class DayMetrics(StrictModel):
    activity_minutes: Optional[float] = Field(default=None, ge=0)
    transport_minutes: Optional[float] = Field(default=None, ge=0)
    walking_m: Optional[float] = Field(default=None, ge=0)
    walking_km: Optional[float] = Field(default=None, ge=0)
    outdoor_minutes: Optional[float] = Field(default=None, ge=0)
    rest_minutes: Optional[float] = Field(default=None, ge=0)
    transfers: int = Field(default=0, ge=0)
    estimated_fields: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_walking(self) -> "DayMetrics":
        if self.walking_m is not None and self.walking_km is not None:
            expected = round(self.walking_m / 1000, 3)
            if abs(expected - self.walking_km) > 0.002:
                raise ValueError("walking_km must equal walking_m / 1000")
        return self


class DayTimelineItem(StrictModel):
    """One ordered entry inside a day, preserving activity/route interleaving."""

    order: int = Field(ge=1)
    kind: Literal["activity", "meal", "route", "lodging"]
    id: str = Field(min_length=1)


class DayDataset(StrictModel):
    day_id: str = Field(min_length=1)
    day_index: int = Field(ge=1)
    date: Date
    timezone: Optional[str] = None
    destination_id: str = ""
    destination_name: str = ""
    start_place: Optional[DatasetEndpoint] = None
    end_place: Optional[DatasetEndpoint] = None
    timeline: List[DayTimelineItem] = Field(default_factory=list)
    activities: List[Activity] = Field(default_factory=list)
    meals: List[Meal] = Field(default_factory=list)
    routes: List[RouteSegment] = Field(default_factory=list)
    lodging_stay_id: Optional[str] = None
    weather: Optional[DayWeather] = None
    metrics: DayMetrics = Field(default_factory=DayMetrics)
    warnings: List[str] = Field(default_factory=list)
    assumptions: List[Assumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timeline(self) -> "DayDataset":
        if [item.order for item in self.timeline] != list(
            range(1, len(self.timeline) + 1)
        ):
            raise ValueError("timeline order must be sequential from 1")
        ids = {
            "activity": {item.activity_id for item in self.activities},
            "meal": {item.meal_id for item in self.meals},
            "route": {item.route_id for item in self.routes},
            "lodging": {self.lodging_stay_id} - {None},
        }
        for item in self.timeline:
            if item.id not in ids[item.kind]:
                raise ValueError(f"timeline references unknown {item.kind}: {item.id}")
        return self


class AmountRange(StrictModel):
    currency: Literal["CNY"] = "CNY"
    low_cny: Optional[float] = Field(default=None, ge=0)
    high_cny: Optional[float] = Field(default=None, ge=0)
    point_cny: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "AmountRange":
        if self.low_cny is not None and self.high_cny is not None and self.high_cny < self.low_cny:
            raise ValueError("amount range high cannot be below low")
        return self


class CostItem(StrictModel):
    cost_id: str = Field(min_length=1)
    category: CostCategory
    label: str = Field(min_length=1)
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    amount_cny: Optional[float] = Field(default=None, ge=0)
    low_cny: Optional[float] = Field(default=None, ge=0)
    high_cny: Optional[float] = Field(default=None, ge=0)
    currency: Literal["CNY"] = "CNY"
    unit_scope: Literal[
        "per_person", "per_room_night", "per_group", "per_item", "unknown"
    ] = "unknown"
    quantity: Optional[float] = Field(default=None, ge=0)
    unit_label: Optional[str] = None
    price_type: PriceType = "unknown"
    price_basis: Optional[str] = None
    source_ids: List[str] = Field(default_factory=list)
    retrieved_at: Optional[AwareDatetime] = None
    confidence: Confidence = "unknown"
    assumptions: List[Assumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cost(self) -> "CostItem":
        priced = [
            value
            for value in (self.amount_cny, self.low_cny, self.high_cny)
            if value is not None
        ]
        if self.price_type == "unknown" and priced:
            raise ValueError("unknown cost item cannot carry an amount")
        if self.price_type != "unknown" and not priced:
            raise ValueError("priced cost item requires an amount")
        if self.low_cny is not None and self.high_cny is not None and self.high_cny < self.low_cny:
            raise ValueError("cost range high cannot be below low")
        return self


class CostSummary(StrictModel):
    items: List[CostItem] = Field(default_factory=list)
    transport: AmountRange = Field(default_factory=AmountRange)
    dining: AmountRange = Field(default_factory=AmountRange)
    lodging: AmountRange = Field(default_factory=AmountRange)
    ticket: AmountRange = Field(default_factory=AmountRange)
    other: AmountRange = Field(default_factory=AmountRange)
    total: AmountRange = Field(default_factory=AmountRange)
    priced_item_count: int = Field(default=0, ge=0)
    unknown_item_count: int = Field(default=0, ge=0)
    complete: bool = False
    computed_by: Literal["backend"] = "backend"


class DatasetCoverage(StrictModel):
    warnings: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    estimated_fields: List[str] = Field(default_factory=list)


class TripDataset(StrictModel):
    schema_version: Literal["trip-dataset.v1"] = DATASET_SCHEMA_VERSION
    dataset_id: str = Field(min_length=1)
    generated_at: datetime
    compatibility: DatasetCompatibility
    trip: TripBasics
    days: List[DayDataset] = Field(min_length=1)
    lodgings: List[LodgingDatasetItem] = Field(default_factory=list)
    costs: CostSummary
    sources: List[SourceCitation] = Field(default_factory=list)
    data_sources: List[DataSourceStatus] = Field(default_factory=list)
    coverage: DatasetCoverage = Field(default_factory=DatasetCoverage)
    assumptions: List[Assumption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dataset(self) -> "TripDataset":
        expected_days = (self.trip.end_date - self.trip.start_date).days + 1
        if len(self.days) != expected_days:
            raise ValueError("dataset must contain one entry per trip date")
        if [day.day_index for day in self.days] != list(range(1, expected_days + 1)):
            raise ValueError("day_index must be sequential from 1")
        if [day.date for day in self.days] != sorted(day.date for day in self.days):
            raise ValueError("days must be ordered by date")
        source_ids = {source.citation_id for source in self.sources}
        dangling = {
            source_id
            for day in self.days
            for item in [*day.routes, *day.activities, *day.meals]
            for source_id in item.source_ids
        } | {
            source_id
            for day in self.days
            if day.weather is not None
            for source_id in day.weather.source_ids
        } | {source_id for item in self.costs.items for source_id in item.source_ids}
        dangling -= source_ids
        if dangling:
            raise ValueError(f"dataset references unknown source ids: {sorted(dangling)}")
        expected = _summarize_costs(self.costs.items)
        if self.costs.priced_item_count != expected["priced_item_count"]:
            raise ValueError("priced_item_count must match cost items")
        if self.costs.unknown_item_count != expected["unknown_item_count"]:
            raise ValueError("unknown_item_count must match cost items")
        if self.costs.complete != expected["complete"]:
            raise ValueError("cost completeness must match cost items")
        for category in ("transport", "dining", "lodging", "ticket", "other", "total"):
            actual = getattr(self.costs, category)
            wanted = expected[category]
            for field in ("low_cny", "high_cny", "point_cny"):
                left = getattr(actual, field)
                right = getattr(wanted, field)
                if (left is None) != (right is None):
                    raise ValueError(f"{category}.{field} does not match cost items")
                if left is not None and right is not None and abs(left - right) > 0.011:
                    raise ValueError(f"{category}.{field} does not match cost items")
        return self


def _decimal(value: Optional[float]) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.01"))


def _summarize_costs(items: List[CostItem]) -> Dict[str, object]:
    """The single backend implementation of cost aggregation."""

    buckets: Dict[str, List[CostItem]] = {
        "transport": [],
        "dining": [],
        "lodging": [],
        "ticket": [],
        "other": [],
    }
    priced = unknown = 0
    for item in items:
        buckets[item.category].append(item)
        if item.price_type == "unknown":
            unknown += 1
        else:
            priced += 1

    def range_for(rows: List[CostItem]) -> AmountRange:
        lows, highs, points = [], [], []
        for item in rows:
            if item.price_type == "unknown":
                continue
            low = item.low_cny if item.low_cny is not None else item.amount_cny
            high = item.high_cny if item.high_cny is not None else item.amount_cny
            point = item.amount_cny
            if point is None and low is not None and high is not None:
                point = float((_decimal(low) + _decimal(high)) / 2)
            if low is not None:
                lows.append(_decimal(low))
            if high is not None:
                highs.append(_decimal(high))
            if point is not None:
                points.append(_decimal(point))
        return AmountRange(
            low_cny=float(sum(lows)) if lows else None,
            high_cny=float(sum(highs)) if highs else None,
            point_cny=float(sum(points)) if points else None,
        )

    result: Dict[str, object] = {}
    all_rows: List[CostItem] = []
    for category, rows in buckets.items():
        result[category] = range_for(rows)
        all_rows.extend(rows)
    result["total"] = range_for(all_rows)
    result["priced_item_count"] = priced
    result["unknown_item_count"] = unknown
    result["complete"] = bool(items) and unknown == 0
    return result


def summarize_costs(items: List[CostItem]) -> CostSummary:
    summary = _summarize_costs(items)
    return CostSummary(
        items=items,
        transport=summary["transport"],
        dining=summary["dining"],
        lodging=summary["lodging"],
        ticket=summary["ticket"],
        other=summary["other"],
        total=summary["total"],
        priced_item_count=summary["priced_item_count"],
        unknown_item_count=summary["unknown_item_count"],
        complete=summary["complete"],
    )


__all__ = [
    "DATASET_MIN_READER_VERSION",
    "DATASET_SCHEMA_VERSION",
    "Activity",
    "AmountRange",
    "Assumption",
    "CostItem",
    "CostSummary",
    "DataSourceStatus",
    "DatasetCompatibility",
    "DatasetCoverage",
    "DatasetEndpoint",
    "DayDataset",
    "DayMetrics",
    "DayWeather",
    "LodgingDatasetItem",
    "Meal",
    "RouteSegment",
    "RouteStep",
    "SourceCitation",
    "TripBasics",
    "TripDataset",
    "TripParty",
    "TripPreferences",
    "summarize_costs",
]

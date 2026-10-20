"""Import a trip-dataset.v1 projection into risk assessment.

The adapter never mutates the dataset and never upgrades an estimate to a
verified value.  Missing data stays missing; derived estimates keep their
``*_estimated`` flags so the engine can mark the dimension as partial.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..entities.risk_dataset_import import DatasetImportSummary
from ..entities.travel_risk import (
    RiskAssessmentInput,
    RiskConnection,
    RiskCost,
    RiskDay,
    RiskLimits,
    RiskTransport,
    RiskWeather,
)
from ..entities.trip_dataset import (
    DATASET_SCHEMA_VERSION,
    DayDataset,
    RouteSegment,
    TripDataset,
)


def _minutes(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if start is None or end is None:
        return None
    if start.tzinfo is None or end.tzinfo is None:
        return None
    if start.utcoffset() is None or end.utcoffset() is None:
        return None
    return round((end - start).total_seconds() / 60, 1)


def _transport_status(route: RouteSegment) -> str:
    if route.route_status == "missing":
        return "missing"
    if route.route_status == "ready" and route.confidence == "verified":
        return "ready"
    return "estimated"


def _transport_coverage(day: DayDataset) -> str:
    legs = [route for route in day.routes if route.transport_leg_id is not None]
    if not legs:
        return "none_required"
    if any(route.route_status == "missing" for route in legs):
        return "missing"
    if all(
        route.route_status == "ready" and route.confidence == "verified"
        for route in legs
    ):
        return "verified"
    return "estimated"


def _connections(route: RouteSegment) -> List[RiskConnection]:
    rows: List[RiskConnection] = []
    for previous, following in zip(route.steps, route.steps[1:]):
        gap = _minutes(previous.arrival_at, following.departure_at)
        if gap is None:
            continue
        modes = {previous.mode, following.mode}
        required = 120 if "flight" in modes else 60 if modes & {"train", "high_speed_rail"} else 30
        rows.append(
            RiskConnection(
                name=f"{previous.to_name or route.from_endpoint.name}换乘",
                available_minutes=gap,
                required_minutes=required,
                entity_ids=[route.route_id],
            )
        )
    return rows


def _source_label(dataset: TripDataset, source_ids: List[str]) -> str:
    by_id = {source.citation_id: source for source in dataset.sources}
    labels = []
    for source_id in source_ids:
        source = by_id.get(source_id)
        if source is None:
            continue
        label = source.title or source.provider or source.source_type
        if source.provider and source.provider not in label:
            label = f"{label}（{source.provider}）"
        if label not in labels:
            labels.append(label)
    return "、".join(labels) or "缺少可核对的来源"


def _weather(dataset: TripDataset, day: DayDataset) -> RiskWeather:
    weather = day.weather
    if weather is None:
        return RiskWeather()
    data_kind = (
        weather.data_kind
        if weather.data_kind in {"forecast", "seasonal_baseline"}
        else "unavailable"
    )
    return RiskWeather(
        data_kind=data_kind,
        observed_at=weather.retrieved_at,
        forecast_end_date=weather.forecast_end_date,
        precipitation_mm=weather.precipitation_mm,
        precipitation_probability_pct=weather.precipitation_probability_pct,
        high_c=weather.high_c,
        low_c=weather.low_c,
        wind_speed_kph=weather.wind_speed_kph,
        condition_code=weather.condition_code,
        source_label=_source_label(dataset, weather.source_ids),
        source_ids=weather.source_ids,
    )


def _active_minutes(day: DayDataset) -> Optional[float]:
    activity = day.metrics.activity_minutes
    transport = day.metrics.transport_minutes
    if activity is None or transport is None:
        return None
    return round(activity + transport, 1)


def _risk_cost(dataset: TripDataset) -> List[RiskCost]:
    rows: List[RiskCost] = []
    labels = {
        "transport": "交通",
        "dining": "餐饮",
        "lodging": "住宿",
        "ticket": "门票/活动",
        "other": "其他",
    }
    for item in dataset.costs.items:
        basis = {
            "actual_quote": "quote",
            "estimated": "estimate",
            "unknown": "unknown",
        }[item.price_type]
        upper = None
        if item.amount_cny is not None:
            if item.high_cny is not None and item.high_cny >= item.amount_cny:
                upper = item.high_cny
            else:
                upper = item.amount_cny
        rows.append(
            RiskCost(
                item_id=item.cost_id,
                name=f"{labels[item.category]}：{item.label}",
                amount_cny=item.amount_cny,
                upper_cny=upper,
                basis=basis,
                source_ids=item.source_ids,
            )
        )
    return rows


def risk_input_from_dataset(
    dataset: TripDataset,
    *,
    budget_cap_cny: Optional[float] = None,
    limits: Optional[RiskLimits] = None,
) -> tuple[RiskAssessmentInput, DatasetImportSummary]:
    if dataset.schema_version != DATASET_SCHEMA_VERSION:
        raise ValueError(f"unsupported dataset schema: {dataset.schema_version}")
    days: List[RiskDay] = []
    for day in dataset.days:
        estimated = set(day.metrics.estimated_fields)
        transports = [
            RiskTransport(
                item_id=route.route_id,
                name=f"{route.from_endpoint.name} → {route.to_endpoint.name}",
                route_status=_transport_status(route),  # type: ignore[arg-type]
                duration_minutes=route.duration_minutes,
                available_minutes=_minutes(route.departure_at, route.arrival_at),
                source_ids=route.source_ids,
            )
            for route in day.routes
            if route.transport_leg_id is not None
        ]
        connections = [
            connection
            for route in day.routes
            if route.transport_leg_id is not None
            for connection in _connections(route)
        ]
        days.append(
            RiskDay(
                day_id=day.day_id,
                date=day.date,
                destination=day.destination_name or day.destination_id,
                outdoor_minutes=day.metrics.outdoor_minutes,
                active_minutes=_active_minutes(day),
                walking_km=day.metrics.walking_km,
                rest_minutes=day.metrics.rest_minutes,
                walking_km_estimated="walking_km" in estimated,
                active_minutes_estimated="active_minutes" in estimated,
                rest_minutes_estimated="rest_minutes" in estimated,
                outdoor_minutes_estimated="outdoor_minutes" in estimated,
                transport_coverage=_transport_coverage(day),  # type: ignore[arg-type]
                weather=_weather(dataset, day),
                transport_complete=_transport_coverage(day)
                in {"verified", "none_required"},
                transports=transports,
                connections=connections,
                entity_ids=[
                    item.id for item in day.timeline
                ],
            )
        )
    request = RiskAssessmentInput(
        title=dataset.trip.title,
        is_example=False,
        budget_cap_cny=budget_cap_cny,
        costs_complete=dataset.costs.complete,
        costs=_risk_cost(dataset),
        days=days,
        limits=limits or RiskLimits(),
    )
    coverage = (
        "complete"
        if dataset.costs.complete
        else "partial"
        if dataset.costs.priced_item_count
        else "missing"
    )
    summary = DatasetImportSummary(
        dataset_id=dataset.dataset_id,
        schema_version=dataset.schema_version,
        bundle_id=dataset.trip.bundle_id,
        title=dataset.trip.title,
        destinations=list(dataset.trip.destination_names),
        start_date=dataset.trip.start_date,
        end_date=dataset.trip.end_date,
        day_count=len(dataset.days),
        budget_cap_cny=budget_cap_cny,
        estimated_total=dataset.costs.total,
        cost_coverage=coverage,
        priced_cost_count=dataset.costs.priced_item_count,
        unknown_cost_count=dataset.costs.unknown_item_count,
        estimated_fields=list(dataset.coverage.estimated_fields),
        missing_fields=list(dataset.coverage.missing_fields),
        warnings=list(dataset.coverage.warnings),
        source_count=len(dataset.sources),
        data_sources=list(dataset.data_sources),
    )
    return request, summary


__all__ = ["risk_input_from_dataset"]

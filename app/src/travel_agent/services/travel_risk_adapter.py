"""Read the current immutable trip bundle without inventing missing inputs."""
from __future__ import annotations

from datetime import datetime, timezone

from ..entities.delivery_bundle import DeliveryBundle
from ..entities.travel_risk import (
    RiskAssessmentInput, RiskConnection, RiskCost, RiskDay, RiskTransport, RiskWeather,
)


def _minutes(start, end):
    if not start or not end or start.utcoffset() is None or end.utcoffset() is None:
        return None
    return (end - start).total_seconds() / 60


def risk_input_from_bundle(bundle: DeliveryBundle, *, now=None) -> RiskAssessmentInput:
    now = now or datetime.now(timezone.utc)
    itinerary = bundle.workspace.itinerary
    facts = {f.fact_assertion_id: f for f in bundle.fact_snapshot.fact_assertions}
    sources = {s.source_record_id: s for s in bundle.fact_snapshot.source_records}

    def current_fact(fact):
        return bool(
            fact and fact.status == "verified"
            and (fact.expires_at is None or (fact.expires_at.utcoffset() is not None and fact.expires_at > now))
            and fact.source_links
            and all(link.source_record_id in sources and sources[link.source_record_id].lifecycle_status == "active" for link in fact.source_links)
        )

    stops = {s.item_id: s for s in [*itinerary.visit_stops, *itinerary.dining_stops, *itinerary.custom_blocks]}
    legs = {leg.transport_leg_id: leg for leg in itinerary.transport_legs}
    weather_days = {(day.destination_id, day.date): day for day in bundle.weather_snapshot.days}
    days = []
    for day in itinerary.day_plans:
        transports, connections, spans, entity_ids = [], [], [], []
        active_minutes = 0
        activity_duration_known = True
        timeline_ids = {entry.entity_id for entry in day.timeline}
        for stop in itinerary.visit_stops:
            if stop.item_id in timeline_ids:
                active_minutes += stop.duration_minutes
        if any(block.item_id in timeline_ids for block in itinerary.custom_blocks):
            activity_duration_known = False
        route_complete = True
        for entry in day.timeline:
            entity_ids.append(entry.entity_id)
            if entry.entity_id in stops:
                stop = stops[entry.entity_id]
                if stop.planned_start and stop.planned_end:
                    spans.append((stop.planned_start, stop.planned_end, stop.item_id, stop.name if hasattr(stop, "name") else stop.title))
            leg = legs.get(entry.entity_id)
            if not leg or entry.projection_role == "arrival":
                continue  # an overnight leg is measured on its departure day only
            current = bool(leg.lineage.fact_assertion_ids) and all(current_fact(facts.get(f)) for f in leg.lineage.fact_assertion_ids)
            window = _minutes(leg.departure_at, leg.arrival_at)
            transports.append(RiskTransport(
                item_id=leg.transport_leg_id,
                name=f"{leg.from_endpoint.name} → {leg.to_endpoint.name}",
                route_status="ready" if leg.route_status == "ready" and current else "estimated" if leg.route_status == "ready" else "missing",
                duration_minutes=leg.duration_minutes,
                available_minutes=max(0, window) if window is not None else None,
                source_ids=leg.lineage.source_record_ids,
            ))
            route_complete = route_complete and current and leg.route_status == "ready"
            if leg.duration_minutes is None:
                activity_duration_known = False
            else:
                active_minutes += leg.duration_minutes
            if leg.departure_at and leg.arrival_at:
                spans.append((leg.departure_at, leg.arrival_at, leg.transport_leg_id, transports[-1].name))
            for previous, following in zip(leg.segments, leg.segments[1:]):
                gap = _minutes(previous.arrival_at, following.departure_at)
                if gap is None:
                    route_complete = False
                    continue
                required = 120 if "flight" in {previous.mode.value, following.mode.value} else 60 if {previous.mode.value, following.mode.value} & {"train", "high_speed_rail"} else 30
                connections.append(RiskConnection(name=f"{previous.to_endpoint.name}换乘", available_minutes=gap, required_minutes=required, entity_ids=[leg.transport_leg_id, previous.segment_id, following.segment_id]))
        # Preserve explicit schedule conflicts; do not infer travel time from a gap.
        aware_spans = [span for span in spans if span[0].utcoffset() is not None and span[1].utcoffset() is not None]
        for start, end, item_id, title in aware_spans:
            duration = _minutes(start, end)
            if duration is not None and duration < 0:
                connections.append(RiskConnection(name=f"{title}起止时间", available_minutes=duration, required_minutes=1, entity_ids=[item_id]))
        ordered = sorted(aware_spans, key=lambda x: x[0])
        for i, previous in enumerate(ordered):
            for following in ordered[i + 1:]:
                gap = _minutes(previous[1], following[0])
                if gap is not None and gap < 0:
                    connections.append(RiskConnection(name=f"{previous[3]}与{following[3]}时间重叠", available_minutes=gap, required_minutes=1, entity_ids=[previous[2], following[2]]))
        weather = weather_days.get((day.destination_id, day.date))
        weather_input = RiskWeather()
        if weather:
            supporting = [facts.get(f) for f in weather.fact_assertion_ids]
            usable = bool(supporting) and all(current_fact(f) for f in supporting)
            timestamps = [f.observed_at for f in supporting if f and f.observed_at and f.observed_at.utcoffset() is not None]
            source_ids = list(dict.fromkeys(link.source_record_id for f in supporting if f for link in f.source_links))
            values = {field: getattr(weather, field) for field in ("precipitation_mm", "precipitation_probability_pct", "high_c", "low_c", "wind_speed_kph", "condition_code")}
            weather_input = RiskWeather(
                **values, data_kind=weather.data_kind if usable else "unavailable",
                observed_at=min(timestamps) if timestamps else None,
                source_label="、".join(sources[s].title for s in source_ids if s in sources) or "缺少可核对的天气来源",
                source_ids=source_ids,
            )
        # The bundle does not guarantee door-to-door walking, outdoor exposure,
        # or explicit rest duration. Keep them unknown for the traveler to supply.
        days.append(RiskDay(
            day_id=day.day_id, date=day.date, destination=day.theme,
            active_minutes=active_minutes if activity_duration_known else None,
            transport_complete=route_complete and bool(transports),
            transports=transports, connections=connections, weather=weather_input,
            entity_ids=entity_ids,
        ))
    cost = itinerary.cost_summary
    costs = []
    if cost.known_subtotal_cny is not None:
        costs.append(RiskCost(item_id="bundle.cost_summary", name="JourneyPilot 已计入费用（仍需确认同行人和整趟口径）", amount_cny=cost.known_subtotal_cny, upper_cny=cost.estimated_total_cny if cost.estimated_total_cny is not None and cost.estimated_total_cny >= cost.known_subtotal_cny else None, basis="estimate"))
    return RiskAssessmentInput(
        title=itinerary.title, budget_cap_cny=cost.budget_cap_cny,
        costs_complete=cost.coverage == "complete", costs=costs, days=days,
    )

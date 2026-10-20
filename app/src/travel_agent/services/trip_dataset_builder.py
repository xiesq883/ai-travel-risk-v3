"""Deterministic Delivery Bundle -> trip-dataset.v1 projection.

No model call, no network call.  Every value is either read from the immutable
bundle or produced by a named estimate whose method and assumptions travel with
the value.  The builder owns all money aggregation; callers never add up costs.
"""

from __future__ import annotations

import hashlib
import math
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, List, Optional, Tuple

from ..entities.delivery_bundle import (
    DELIVERY_BUNDLE_CONTRACT_VERSION,
    DeliveryBundle,
)
from ..entities.trip_dataset import (
    DATASET_SCHEMA_VERSION,
    Activity,
    Assumption,
    CostItem,
    DataSourceStatus,
    DatasetCompatibility,
    DatasetCoverage,
    DatasetEndpoint,
    DayDataset,
    DayMetrics,
    DayTimelineItem,
    DayWeather,
    LodgingDatasetItem,
    Meal,
    RouteSegment,
    RouteStep,
    SourceCitation,
    TripBasics,
    TripDataset,
    TripParty,
    TripPreferences,
    summarize_costs,
)

_MONEY = Decimal("0.01")
_WALK_METRES_PER_MINUTE = 80.0
_WALK_DETOUR_FACTOR = 1.3
_MODES = {
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
}
_COST_FIELDS = {
    "estimated_cost_cny",
    "average_spend_cny",
    "nightly_price_cny",
    "total_price_cny",
    "total_cost_cny",
    "cost_cny",
}
_MEAL_SLOTS = ("breakfast", "lunch", "dinner")


def _money(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(_MONEY))


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value


def _minutes(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    start, end = _aware(start), _aware(end)
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 60, 1)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _enum_value(value: Any, default: str = "other") -> str:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) and raw else default


def _mode(value: Any) -> str:
    raw = _enum_value(value, "unknown")
    return raw if raw in _MODES else "other"


def _endpoint(value: Any) -> Optional[DatasetEndpoint]:
    if value is None:
        return None
    name = str(_attr(value, "name", "") or "").strip()
    if not name:
        return None
    return DatasetEndpoint(
        name=name,
        place_id=_attr(value, "place_id"),
        latitude=_attr(value, "latitude"),
        longitude=_attr(value, "longitude"),
    )


def _haversine_m(
    from_endpoint: Optional[DatasetEndpoint], to_endpoint: Optional[DatasetEndpoint]
) -> Optional[float]:
    if from_endpoint is None or to_endpoint is None:
        return None
    if None in (
        from_endpoint.latitude,
        from_endpoint.longitude,
        to_endpoint.latitude,
        to_endpoint.longitude,
    ):
        return None
    lat1, lon1 = math.radians(from_endpoint.latitude), math.radians(from_endpoint.longitude)
    lat2, lon2 = math.radians(to_endpoint.latitude), math.radians(to_endpoint.longitude)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


class _SourceCatalog:
    """Fact/source lineage in the one shape the dataset needs."""

    def __init__(self, bundle: DeliveryBundle) -> None:
        records = getattr(getattr(bundle, "fact_snapshot", None), "source_records", []) or []
        facts = getattr(getattr(bundle, "fact_snapshot", None), "fact_assertions", []) or []
        self.records = {item.source_record_id: item for item in records}
        self.facts = {item.fact_assertion_id: item for item in facts}
        self._cited_by_verified_fact = {
            link.source_record_id
            for fact in facts
            if getattr(fact, "status", "") == "verified"
            for link in getattr(fact, "source_links", []) or []
        }
        self.citations = [self._citation(record) for record in records]

    def _citation(self, record: Any) -> SourceCitation:
        provider = str(getattr(record, "provider_name", "") or "")
        kind = str(getattr(record, "source_kind", "") or "")
        if provider in {"12306", "12306-train"}:
            source_type = "official_api"
        elif kind in {"external_tool"}:
            source_type = "third_party_api"
        elif kind in {"external_web"}:
            source_type = "public_web"
        else:
            source_type = "unknown"
        fact_ids = [
            fact.fact_assertion_id
            for fact in self.facts.values()
            if any(
                link.source_record_id == record.source_record_id
                for link in getattr(fact, "source_links", []) or []
            )
        ]
        confidence = (
            "verified"
            if record.source_record_id in self._cited_by_verified_fact
            else "unverified"
        )
        raw_url = getattr(record, "canonical_url", None)
        if raw_url is not None:
            try:
                SourceCitation(citation_id="probe", source_type="unknown", url=raw_url)
            except Exception:
                # A malformed upstream URL must not make the whole dataset
                # unreadable; keep the citation and drop only the link.
                raw_url = None
        return SourceCitation(
            citation_id=record.source_record_id,
            source_record_id=record.source_record_id,
            source_type=source_type,
            provider=provider,
            title=str(getattr(record, "title", "") or ""),
            url=raw_url,
            retrieved_at=_aware(getattr(record, "retrieved_at", None)),
            published_at=_aware(getattr(record, "published_at", None)),
            excerpt=str(getattr(record, "public_excerpt", "") or "")[:1200],
            confidence=confidence,
            fact_assertion_ids=fact_ids,
        )

    def for_fact_ids(
        self, fact_ids: Iterable[str], *, now: datetime
    ) -> Tuple[List[str], str, Optional[datetime]]:
        ids: List[str] = []
        verified = True
        retrieved: List[datetime] = []
        found = False
        for fact_id in fact_ids or ():
            fact = self.facts.get(fact_id)
            if fact is None:
                verified = False
                continue
            found = True
            links = list(getattr(fact, "source_links", []) or [])
            if getattr(fact, "status", "") != "verified" or not links:
                verified = False
            expires = _aware(getattr(fact, "expires_at", None))
            if expires is not None and expires <= now:
                verified = False
            for link in links:
                record = self.records.get(link.source_record_id)
                if record is None or getattr(record, "lifecycle_status", "active") != "active":
                    verified = False
                    continue
                if link.source_record_id not in ids:
                    ids.append(link.source_record_id)
                stamp = _aware(getattr(record, "retrieved_at", None))
                if stamp is not None:
                    retrieved.append(stamp)
        if not found:
            return ids, "unknown", None
        return ids, ("verified" if verified else "unverified"), (max(retrieved) if retrieved else None)

    def for_lineage(
        self, lineage: Any, *, now: datetime
    ) -> Tuple[List[str], str, Optional[datetime]]:
        fact_ids = list(getattr(lineage, "fact_assertion_ids", []) or [])
        ids = [
            source_id
            for source_id in getattr(lineage, "source_record_ids", []) or []
            if source_id in self.records
        ]
        extra, confidence, retrieved = self.for_fact_ids(fact_ids, now=now)
        ids.extend(source_id for source_id in extra if source_id not in ids)
        if not ids and confidence == "unknown":
            return [], "unknown", None
        if confidence == "unknown":
            active = [
                self.records[source_id]
                for source_id in ids
                if getattr(self.records[source_id], "lifecycle_status", "active") == "active"
            ]
            confidence = "unverified" if active else "unknown"
            stamps = [
                stamp
                for stamp in (_aware(getattr(record, "retrieved_at", None)) for record in active)
                if stamp is not None
            ]
            retrieved = max(stamps) if stamps else None
        return ids, confidence, retrieved

    def facts_for(self, entity_id: str, fields: Iterable[str]) -> List[str]:
        wanted = set(fields)
        return [
            fact.fact_assertion_id
            for fact in self.facts.values()
            if getattr(getattr(fact, "entity_ref", None), "entity_id", None) == entity_id
            and getattr(fact, "field_path", "").split(".")[-1] in wanted
        ]


def _party(identity: Any) -> TripParty:
    raw = _attr(identity, "party", {}) or {}
    return TripParty(
        adults=int(_attr(raw, "adults", 0) or 0),
        children=int(_attr(raw, "children", 0) or 0),
        elderly_companions=bool(_attr(raw, "elderly_companions", False)),
        accessibility_required=bool(_attr(raw, "accessibility_required", False)),
    )


def _preferences(identity: Any, workspace: Any) -> TripPreferences:
    style = _attr(_attr(identity, "style", {}) or {}, "primary", None)
    interests = list(
        _attr(_attr(identity, "style", {}) or {}, "secondary_interests", []) or []
    )
    snapshot = getattr(workspace, "intent_contract_snapshot", None)
    requirements = []
    for item in getattr(snapshot, "requirements", []) or []:
        text = _attr(item, "text", None) or _attr(item, "summary", None) or item
        if isinstance(text, (str, int, float)):
            requirements.append(str(text))
    requirements = requirements[:20]
    return TripPreferences(
        style=style,
        interests=[str(item) for item in interests][:20],
        requirements=requirements,
    )


def _trip_basics(bundle: DeliveryBundle, identity: Any) -> TripBasics:
    workspace = bundle.workspace
    itinerary = workspace.itinerary
    manifest = bundle.manifest
    days = sorted(itinerary.day_plans, key=lambda item: item.date)
    # The materialized Day list is the authority for dataset span: a dataset
    # must contain exactly one entry per materialized day.
    start = days[0].date
    end = days[-1].date
    destinations = list(_attr(identity, "destinations", []) or [])
    destination_ids = [
        str(_attr(item, "place_id", "") or "") for item in destinations if _attr(item, "place_id", None)
    ] or list(itinerary.destination_ids)
    destination_names = [
        str(_attr(item, "name", "") or "") for item in destinations if _attr(item, "name", None)
    ]
    weather_days = getattr(getattr(bundle, "weather_snapshot", None), "days", []) or []
    timezones = {
        str(_attr(day, "timezone"))
        for day in weather_days
        if _attr(day, "timezone", None)
    }
    return TripBasics(
        run_id=manifest.run_id,
        bundle_id=manifest.bundle_id,
        itinerary_id=str(
            _attr(itinerary, "itinerary_id", None) or f"{manifest.run_id}:itinerary"
        ),
        workspace_revision=manifest.workspace_revision,
        fact_data_revision=manifest.fact_data_revision,
        weather_data_revision=manifest.weather_data_revision,
        title=itinerary.title,
        origin=_endpoint(_attr(identity, "origin", None)),
        destination_ids=destination_ids,
        destination_names=destination_names,
        start_date=start,
        end_date=end,
        timezone=next(iter(timezones)) if len(timezones) == 1 else None,
        party=_party(identity),
        preferences=_preferences(identity, workspace),
    )


def _data_sources(settings: Any) -> List[DataSourceStatus]:
    if settings is None:
        try:
            from ..config import get_settings

            settings = get_settings()
        except Exception:  # configuration absence is reported as "not configured"
            settings = None
    servers = getattr(settings, "mcp_servers", {}) or {}

    def enabled(name: str) -> bool:
        item = servers.get(name) if isinstance(servers, dict) else None
        if item is None:
            return False
        return not bool(_attr(item, "disabled", False))

    def status(
        source_id: str,
        name: str,
        kind: str,
        configured: bool,
        capabilities: List[str],
        required_env: List[str],
        note: str,
    ) -> DataSourceStatus:
        return DataSourceStatus(
            source_id=source_id,
            name=name,
            kind=kind,
            configured=configured,
            capabilities=capabilities,
            required_env=required_env,
            note=note,
        )

    amap_item = servers.get("amap-maps") if isinstance(servers, dict) else None
    amap_env = getattr(amap_item, "env", {}) or {}
    amap_configured = enabled("amap-maps") or bool(
        os.getenv("AMAP_WEB_SERVICE_KEY")
        or os.getenv("AMAP_MAPS_API_KEY")
        or (amap_env.get("AMAP_MAPS_API_KEY") if isinstance(amap_env, dict) else None)
    )

    return [
        status(
            "open-meteo",
            "Open-Meteo",
            "weather",
            enabled("open-meteo"),
            ["daily_forecast", "current_weather"],
            [],
            "免密钥天气接口；缺报时逐日天气保持 unknown。" if enabled("open-meteo") else "未启用，无法补齐缺失天气。",
        ),
        status(
            "duckduckgo-search",
            "DuckDuckGo",
            "search",
            enabled("duckduckgo-search"),
            ["web_search"],
            [],
            "免密钥网页搜索；结果按公开网页记录，不视为官方报价。",
        ),
        status(
            "tavily-search",
            "Tavily",
            "search",
            enabled("tavily-search"),
            ["web_search", "extract"],
            ["TAVILY_API_KEY"],
            "需要 Tavily Key；未配置时餐饮/酒店只能沿用已有资料。",
        ),
        status(
            "brave-search",
            "Brave Search",
            "search",
            enabled("brave-search"),
            ["web_search"],
            ["BRAVE_API_KEY"],
            "需要 Brave Key。",
        ),
        status(
            "firecrawl",
            "Firecrawl",
            "search",
            enabled("firecrawl"),
            ["crawl", "extract"],
            ["FIRECRAWL_API_KEY"],
            "需要 Firecrawl Key。",
        ),
        status(
            "amap-maps",
            "高德地图",
            "route",
            amap_configured,
            ["place_search", "route_planning", "transit_fare"],
            ["AMAP_WEB_SERVICE_KEY", "AMAP_MAPS_API_KEY"],
            "高德 Web 服务 Key 已配置；中国大陆 POI、路线与可获取的公交票价可用。"
            if amap_configured
            else "需要高德 Key；未配置时中国大陆精细路线与地铁票价不可查询。",
        ),
        status(
            "global-route-search",
            "Transitous / 高德 路径规划",
            "route",
            True,
            ["public_transit", "walk", "drive", "bike"],
            [],
            "免密钥全球路径规划；中国大陆覆盖依赖高德 Key。",
        ),
        status(
            "nominatim",
            "OpenStreetMap Nominatim",
            "place",
            True,
            ["place_identity", "geocoding"],
            [],
            "免密钥地点身份查询，受速率限制。",
        ),
        status(
            "12306-train",
            "中国铁路 12306",
            "route",
            enabled("12306-train"),
            ["train_schedule", "published_fare"],
            [],
            "官方列车时刻与公布票价。",
        ),
        status(
            "duffel-flights",
            "Duffel",
            "flight",
            enabled("duffel-flights"),
            ["flight_search", "live_quote"],
            ["DUFFEL_API_KEY_LIVE"],
            "需要 Duffel Key；未配置时航班价格保持 unknown。",
        ),
        status(
            "hotel-booking",
            "酒店实时报价",
            "hotel",
            False,
            ["availability", "live_quote"],
            [],
            "当前项目未接入酒店实时报价接口；住宿价格只能是参考估算，不能声称有房。",
        ),
    ]


def _price_for(
    amount: Optional[float],
    *,
    verified: bool,
    basis_when_verified: str,
    basis_when_estimated: str,
) -> Tuple[Optional[float], str, Optional[str]]:
    amount = _money(amount)
    if amount is None:
        return None, "unknown", None
    if verified:
        return amount, "actual_quote", basis_when_verified
    return amount, "estimated", basis_when_estimated


def _route_from_leg(
    leg: Any, sources: _SourceCatalog, now: datetime
) -> RouteSegment:
    from_endpoint = _endpoint(leg.from_endpoint)
    to_endpoint = _endpoint(leg.to_endpoint)
    mode = _mode(leg.selected_mode)
    source_ids, confidence, retrieved = sources.for_lineage(
        _attr(leg, "lineage", None), now=now
    )
    distance = _money(getattr(leg, "distance_meters", None))
    distance_source = "third_party_api" if distance is not None else "unknown"
    distance_method = None
    assumptions: List[Assumption] = []
    duration = getattr(leg, "duration_minutes", None)
    if distance is None and mode == "walk" and duration:
        distance = _money(float(duration) * _WALK_METRES_PER_MINUTE)
        distance_source = "program_estimate"
        distance_method = "walk_duration_x_4.8kmh"
        assumptions.append(
            Assumption(
                code="walk_distance_from_duration",
                text="未取得步行距离，按 4.8 km/h 的步行速度由计划时长反推，误差可能较大。",
            )
        )
    fare, price_type, price_basis = _price_for(
        getattr(leg, "total_cost_cny", None),
        verified=confidence == "verified",
        basis_when_verified="published_fare",
        basis_when_estimated="itinerary_estimate",
    )
    steps = [
        RouteStep(
            mode=_mode(getattr(segment, "mode", None)),
            from_name=str(getattr(getattr(segment, "from_endpoint", None), "name", "") or ""),
            to_name=str(getattr(getattr(segment, "to_endpoint", None), "name", "") or ""),
            line_name=getattr(segment, "line_name", None),
            service_number=getattr(segment, "service_number", None),
            departure_at=_aware(getattr(segment, "departure_at", None)),
            arrival_at=_aware(getattr(segment, "arrival_at", None)),
            duration_minutes=(
                float(segment.duration_minutes)
                if getattr(segment, "duration_minutes", None) is not None
                else None
            ),
            distance_m=(
                float(segment.distance_meters)
                if getattr(segment, "distance_meters", None) is not None
                else None
            ),
            fare_cny=_money(getattr(segment, "cost_cny", None)),
        )
        for segment in (getattr(leg, "segments", None) or [])
    ]
    return RouteSegment(
        route_id=leg.transport_leg_id,
        transport_leg_id=leg.transport_leg_id,
        from_endpoint=from_endpoint or DatasetEndpoint(name="未知起点"),
        to_endpoint=to_endpoint or DatasetEndpoint(name="未知终点"),
        mode=mode,
        route_status=(
            "ready"
            if getattr(leg, "route_status", "") == "ready"
            else "estimated"
            if getattr(leg, "route_status", "") == "pending"
            else "missing"
        ),
        departure_at=_aware(getattr(leg, "departure_at", None)),
        arrival_at=_aware(getattr(leg, "arrival_at", None)),
        duration_minutes=float(duration) if duration is not None else None,
        distance_m=distance,
        distance_source=distance_source,
        distance_method=distance_method,
        fare_cny=fare,
        price_type=price_type,
        price_basis=price_basis,
        transfer_count=int(getattr(leg, "transfer_count", 0) or 0),
        steps=steps,
        source_ids=source_ids,
        retrieved_at=retrieved,
        confidence=confidence if confidence != "unknown" else ("unverified" if distance is not None else "unknown"),
        assumptions=assumptions,
    )


def _gap_route(
    start: Optional[DatasetEndpoint], end: Optional[DatasetEndpoint]
) -> RouteSegment:
    distance = _haversine_m(start, end)
    assumptions: List[Assumption] = []
    method = None
    duration = None
    if distance is not None:
        distance = _money(distance * _WALK_DETOUR_FACTOR)
        duration = round(distance / _WALK_METRES_PER_MINUTE, 1)
        method = "haversine_x_1.3_walk_4.8kmh"
        assumptions.append(
            Assumption(
                code="unqueried_walk_gap",
                text="行程未给出这段步行路线；按两点直线距离 × 1.3 的道路绕行系数估算，属于程序估算。",
            )
        )
    else:
        assumptions.append(
            Assumption(
                code="unqueried_walk_gap_unknown",
                text="行程未给出这段路线，且地点坐标缺失；距离与耗时保持未知。",
            )
        )
    return RouteSegment(
        route_id=f"gap_{hashlib.sha1(f'{start and start.place_id}:{end and end.place_id}'.encode()).hexdigest()[:10]}",
        transport_leg_id=None,
        from_endpoint=start or DatasetEndpoint(name="未知起点"),
        to_endpoint=end or DatasetEndpoint(name="未知终点"),
        mode="walk",
        route_status="estimated" if distance is not None else "missing",
        duration_minutes=duration,
        distance_m=distance,
        distance_source="program_estimate" if distance is not None else "unknown",
        distance_method=method,
        fare_cny=None,
        price_type="unknown",
        price_basis=None,
        transfer_count=0,
        source_ids=[],
        retrieved_at=None,
        confidence="estimated" if distance is not None else "unknown",
        assumptions=assumptions,
    )


def _activity_from_visit(
    stop: Any, sources: _SourceCatalog, now: datetime
) -> Activity:
    source_ids, confidence, retrieved = sources.for_lineage(
        _attr(stop, "lineage", None), now=now
    )
    duration = _minutes(stop.planned_start, stop.planned_end)
    duration = duration if duration is not None else float(stop.duration_minutes)
    ticket, price_type, basis = _price_for(
        getattr(stop, "estimated_cost_cny", None),
        verified=confidence == "verified",
        basis_when_verified="published_price",
        basis_when_estimated="itinerary_estimate",
    )
    visit_type = str(getattr(stop, "visit_type", "") or "")
    return Activity(
        activity_id=stop.item_id,
        entity_type="visit_stop",
        name=stop.name,
        place_id=stop.place_id,
        address=getattr(stop, "address", None),
        latitude=getattr(stop, "latitude", None),
        longitude=getattr(stop, "longitude", None),
        visit_type=visit_type or None,
        start_at=_aware(stop.planned_start),
        end_at=_aware(stop.planned_end),
        duration_minutes=duration,
        ticket_cny=ticket,
        price_type=price_type,
        price_basis=basis,
        outdoor=True if visit_type == "nature" else None,
        source_ids=source_ids,
        retrieved_at=retrieved,
        confidence=confidence,
    )


def _activity_from_block(block: Any) -> Activity:
    duration = _minutes(block.planned_start, block.planned_end)
    if duration is None and getattr(block, "duration_minutes", None) is not None:
        duration = float(block.duration_minutes)
    return Activity(
        activity_id=block.item_id,
        entity_type="custom_block",
        name=block.title,
        start_at=_aware(block.planned_start),
        end_at=_aware(block.planned_end),
        duration_minutes=duration,
        price_type="unknown",
        confidence="unknown",
        assumptions=(
            []
            if duration is not None
            else [
                Assumption(
                    code="custom_block_duration_unknown",
                    text="自定义安排没有可用的起止时间或时长，活动时长保持未知。",
                )
            ]
        ),
    )


def _meal_from_stop(
    stop: Any, party_size: int, sources: _SourceCatalog, now: datetime
) -> Meal:
    source_ids, confidence, retrieved = sources.for_lineage(
        _attr(stop, "lineage", None), now=now
    )
    per_person = _money(getattr(stop, "average_spend_cny", None))
    party = party_size if party_size > 0 else None
    total = _money(per_person * party) if per_person is not None and party else _money(
        getattr(stop, "estimated_cost_cny", None)
    )
    if total is None and per_person is not None:
        price_type = "unknown"
        basis = "reference_per_person_party_unknown"
    elif per_person is not None:
        price_type = "estimated"
        basis = "reference_per_person"
    elif total is not None:
        price_type = "estimated"
        basis = "itinerary_estimate"
    else:
        price_type = "unknown"
        basis = None
    duration = _minutes(stop.planned_start, stop.planned_end)
    if duration is None and getattr(stop, "duration_minutes", None) is not None:
        duration = float(stop.duration_minutes)
    meal_type = str(getattr(stop, "meal_type", "other") or "other")
    if meal_type not in {"breakfast", "lunch", "dinner", "snack", "other"}:
        meal_type = "other"
    return Meal(
        meal_id=stop.item_id,
        meal_type=meal_type,  # type: ignore[arg-type]
        status="planned",
        restaurant_name=stop.name,
        place_id=stop.place_id,
        address=getattr(stop, "address", None),
        start_at=_aware(stop.planned_start),
        end_at=_aware(stop.planned_end),
        duration_minutes=duration,
        party_size=party,
        per_person_cny=per_person,
        total_cny=total,
        price_type=price_type,
        price_basis=basis,
        source_ids=source_ids,
        retrieved_at=retrieved,
        confidence=confidence,
        assumptions=(
            [
                Assumption(
                    code="dining_party_unknown",
                    text="已有人均消费，但同行人数未知，无法换算整桌金额。",
                )
            ]
            if per_person is not None and not party
            else []
        ),
    )


def _lodging_item(stay: Any, party_size: int, sources: _SourceCatalog, now: datetime) -> LodgingDatasetItem:
    source_ids, confidence, retrieved = sources.for_lineage(
        _attr(stay, "lineage", None), now=now
    )
    nightly = _money(getattr(stay, "nightly_price_cny", None))
    total = _money(getattr(stay, "total_price_cny", None))
    if total is None and nightly is not None:
        total = _money(nightly * stay.nights)
    price_kind = str(getattr(stay, "price_kind", "reference_estimate") or "reference_estimate")
    if price_kind == "live_quote":
        price_type, basis = ("actual_quote", "live_quote") if total is not None else ("unknown", None)
    elif total is not None:
        price_type, basis = "estimated", "reference_estimate"
    else:
        price_type, basis = "unknown", None
    availability = str(getattr(stay, "availability_status", "needs_confirmation") or "needs_confirmation")
    if availability not in {"confirmed", "needs_confirmation", "unavailable"}:
        availability = "unknown"
    assumptions: List[Assumption] = []
    if price_type != "actual_quote":
        assumptions.append(
            Assumption(
                code="lodging_not_live_quote",
                text="住宿价格是参考估算，未取得指定日期的实时报价；不代表有房或可直接预订。",
            )
        )
    assumptions.append(
        Assumption(
            code="lodging_rooms_unknown",
            text="行程未给出房间数，房型与房间数保持未知。",
        )
    )
    return LodgingDatasetItem(
        stay_id=stay.stay_id,
        name=stay.name,
        place_id=stay.place_id,
        address=getattr(stay, "address", None),
        check_in_date=stay.check_in_date,
        check_out_date=stay.check_out_date,
        nights=stay.nights,
        room_count=None,
        guest_count=party_size or None,
        nightly_cny=nightly,
        total_cny=total,
        price_type=price_type,
        price_basis=basis,
        availability_status=availability,  # type: ignore[arg-type]
        includes=[],
        source_ids=source_ids,
        retrieved_at=retrieved,
        confidence=confidence,
        assumptions=assumptions,
    )


def _day_weather(
    day: Any, bundle: DeliveryBundle, sources: _SourceCatalog, now: datetime
) -> Optional[DayWeather]:
    snapshot = getattr(bundle, "weather_snapshot", None)
    rows = getattr(snapshot, "days", []) or []
    match = next(
        (
            item
            for item in rows
            if getattr(item, "destination_id", None) == day.destination_id
            and getattr(item, "date", None) == day.date
        ),
        None,
    )
    if match is None:
        return None
    source_ids, confidence, retrieved = sources.for_fact_ids(
        getattr(match, "fact_assertion_ids", []) or [], now=now
    )
    data_kind = str(getattr(match, "data_kind", "unavailable") or "unavailable")
    if data_kind not in {"forecast", "seasonal_baseline", "observation"}:
        data_kind = "unavailable"
    forecast_end = next(
        (
            row.end_date
            for row in (getattr(snapshot, "coverage", []) or [])
            if getattr(row, "destination_id", None) == day.destination_id
            and getattr(row, "start_date", None)
            and row.start_date <= day.date <= row.end_date
        ),
        None,
    )
    return DayWeather(
        data_kind=data_kind,  # type: ignore[arg-type]
        forecast_end_date=forecast_end,
        condition_label=getattr(match, "condition_label", None),
        high_c=getattr(match, "high_c", None),
        low_c=getattr(match, "low_c", None),
        precipitation_mm=getattr(match, "precipitation_mm", None),
        precipitation_probability_pct=getattr(match, "precipitation_probability_pct", None),
        wind_speed_kph=getattr(match, "wind_speed_kph", None),
        condition_code=getattr(match, "condition_code", None),
        retrieved_at=retrieved,
        source_ids=source_ids,
        confidence=confidence if confidence != "unknown" else ("unverified" if data_kind != "unavailable" else "unknown"),
    )


def _metrics(
    activities: List[Activity],
    routes: List[RouteSegment],
    meals: List[Meal],
) -> Tuple[DayMetrics, List[str], List[str]]:
    warnings: List[str] = []
    estimated: List[str] = []
    durations = [item.duration_minutes for item in activities]
    activity_minutes = (
        round(sum(value for value in durations if value is not None), 1)
        if durations and all(value is not None for value in durations)
        else None
    )
    if activity_minutes is None and activities:
        warnings.append("有活动缺少时长，活动总时长保持未知。")

    leg_routes = [route for route in routes if route.transport_leg_id is not None]
    leg_durations = [route.duration_minutes for route in leg_routes]
    transport_minutes = (
        round(sum(value for value in leg_durations if value is not None), 1)
        if leg_durations and all(value is not None for value in leg_durations)
        else None
    )
    if transport_minutes is None and leg_routes:
        warnings.append("有交通段缺少耗时，交通总时长保持未知。")

    walk_routes = [route for route in routes if route.mode == "walk"]
    if not walk_routes:
        walking_m: Optional[float] = 0.0
    elif any(route.distance_m is None for route in walk_routes):
        walking_m = None
        warnings.append("有步行段缺少距离，步行总量保持未知。")
    else:
        walking_m = round(sum(route.distance_m or 0 for route in walk_routes), 1)
        if any(route.distance_source == "program_estimate" for route in walk_routes):
            estimated.append("walking_km")

    outdoor = 0.0
    outdoor_known = False
    for item in activities:
        if item.duration_minutes is None:
            continue
        if item.visit_type == "nature":
            outdoor += item.duration_minutes
            outdoor_known = True
        elif item.visit_type in {"attraction", "shopping"}:
            outdoor += item.duration_minutes * 0.5
            outdoor_known = True
    walk_minutes = [route.duration_minutes for route in walk_routes]
    if walk_minutes and all(value is not None for value in walk_minutes):
        outdoor += sum(value for value in walk_minutes if value is not None)
        outdoor_known = True
    outdoor_minutes = round(outdoor, 1) if outdoor_known else None
    if outdoor_minutes is not None:
        estimated.append("outdoor_minutes")

    spans = [
        (item.start_at, item.end_at)
        for item in [*activities, *meals]
        if item.start_at is not None and item.end_at is not None
    ]
    spans.extend(
        (route.departure_at, route.arrival_at)
        for route in leg_routes
        if route.departure_at is not None and route.arrival_at is not None
    )
    spans = [span for span in spans if _aware(span[0]) and _aware(span[1])]
    if spans:
        spans.sort(key=lambda span: span[0])
        rest = 0.0
        for previous, following in zip(spans, spans[1:]):
            gap = _minutes(previous[1], following[0])
            if gap is not None and gap > 0:
                rest += gap
        unqueried = [route for route in routes if route.transport_leg_id is None]
        if any(route.duration_minutes is None for route in unqueried):
            rest_minutes: Optional[float] = None
            warnings.append("未查询的步行段缺少耗时，无法从日程空隙中扣除，休息时长保持未知。")
        else:
            # Gaps between scheduled items are not all rest: an unqueried walk
            # consumes part of the gap.  Subtract its estimated duration.
            rest = max(0.0, rest - sum(route.duration_minutes or 0 for route in unqueried))
            rest_minutes = round(rest, 1)
            estimated.append("rest_minutes")
    else:
        rest_minutes = None

    metrics = DayMetrics(
        activity_minutes=activity_minutes,
        transport_minutes=transport_minutes,
        walking_m=walking_m,
        walking_km=round(walking_m / 1000, 3) if walking_m is not None else None,
        outdoor_minutes=outdoor_minutes,
        rest_minutes=rest_minutes,
        transfers=sum(route.transfer_count for route in leg_routes),
        estimated_fields=estimated,
    )
    return metrics, warnings, estimated


def _cost_items(
    itinerary: Any,
    lodgings: List[LodgingDatasetItem],
    party_size: int,
    sources: _SourceCatalog,
    now: datetime,
) -> List[CostItem]:
    items: List[CostItem] = []
    for leg in itinerary.transport_legs:
        route = _route_from_leg(leg, sources, now)
        items.append(
            CostItem(
                cost_id=f"cost_{leg.transport_leg_id}",
                category="transport",
                label=f"{leg.from_endpoint.name} → {leg.to_endpoint.name}",
                entity_type="transport_leg",
                entity_id=leg.transport_leg_id,
                amount_cny=route.fare_cny,
                low_cny=route.fare_cny,
                high_cny=route.fare_cny,
                unit_scope="per_group",
                quantity=None,
                unit_label="整段",
                price_type=route.price_type,
                price_basis=route.price_basis,
                source_ids=route.source_ids,
                retrieved_at=route.retrieved_at,
                confidence=route.confidence,
            )
        )
    for stop in itinerary.dining_stops:
        meal = _meal_from_stop(stop, party_size, sources, now)
        items.append(
            CostItem(
                cost_id=f"cost_{stop.item_id}",
                category="dining",
                label=stop.name,
                entity_type="dining_stop",
                entity_id=stop.item_id,
                amount_cny=meal.total_cny,
                low_cny=meal.total_cny,
                high_cny=meal.total_cny,
                unit_scope="per_group" if meal.total_cny is not None else "per_person",
                quantity=party_size or None,
                unit_label="人",
                price_type=meal.price_type,
                price_basis=meal.price_basis,
                source_ids=meal.source_ids,
                confidence=meal.confidence,
                assumptions=meal.assumptions,
            )
        )
    for stay in lodgings:
        items.append(
            CostItem(
                cost_id=f"cost_{stay.stay_id}",
                category="lodging",
                label=stay.name,
                entity_type="lodging_stay",
                entity_id=stay.stay_id,
                amount_cny=stay.total_cny,
                low_cny=stay.total_cny,
                high_cny=stay.total_cny,
                unit_scope="per_group",
                quantity=float(stay.nights),
                unit_label="晚",
                price_type=stay.price_type,
                price_basis=stay.price_basis,
                source_ids=stay.source_ids,
                retrieved_at=stay.retrieved_at,
                confidence=stay.confidence,
                assumptions=stay.assumptions,
            )
        )
    for stop in itinerary.visit_stops:
        activity = _activity_from_visit(stop, sources, now)
        items.append(
            CostItem(
                cost_id=f"cost_{stop.item_id}",
                category="ticket",
                label=stop.name,
                entity_type="visit_stop",
                entity_id=stop.item_id,
                amount_cny=activity.ticket_cny,
                low_cny=activity.ticket_cny,
                high_cny=activity.ticket_cny,
                unit_scope="per_item",
                quantity=None,
                unit_label="行程条目",
                price_type=activity.price_type,
                price_basis=activity.price_basis,
                source_ids=activity.source_ids,
                confidence=activity.confidence,
            )
        )
    return items


def build_trip_dataset(
    bundle: DeliveryBundle,
    identity: Any = None,
    *,
    now: Optional[datetime] = None,
    settings: Any = None,
) -> TripDataset:
    """Project one immutable bundle into the versioned dataset."""

    now = now or datetime.now(timezone.utc)
    workspace = bundle.workspace
    itinerary = workspace.itinerary
    trip = _trip_basics(bundle, identity)
    sources = _SourceCatalog(bundle)
    party_size = trip.party.total
    warnings: List[str] = []
    missing: List[str] = []
    estimated: List[str] = []

    visits = {item.item_id: item for item in itinerary.visit_stops}
    dining = {item.item_id: item for item in itinerary.dining_stops}
    blocks = {item.item_id: item for item in itinerary.custom_blocks}
    legs = {item.transport_leg_id: item for item in itinerary.transport_legs}
    lodgings = [
        _lodging_item(stay, party_size, sources, now)
        for stay in itinerary.lodging_stays
    ]
    lodging_by_id = {item.stay_id: item for item in lodgings}

    days: List[DayDataset] = []
    for index, plan in enumerate(sorted(itinerary.day_plans, key=lambda item: item.date), start=1):
        activities: List[Activity] = []
        meals: List[Meal] = []
        routes: List[RouteSegment] = []
        timeline_items: List[DayTimelineItem] = []

        def add_timeline(kind: str, identifier: str) -> None:
            timeline_items.append(
                DayTimelineItem(
                    order=len(timeline_items) + 1,
                    kind=kind,  # type: ignore[arg-type]
                    id=identifier,
                )
            )

        day_warnings: List[str] = []
        day_assumptions: List[Assumption] = []
        last_endpoint: Optional[DatasetEndpoint] = None
        route_since_place = True
        first_endpoint: Optional[DatasetEndpoint] = None
        lodging_stay_id = next(
            (
                stay.stay_id
                for stay in lodgings
                if stay.check_in_date <= plan.date < stay.check_out_date
            ),
            None,
        )

        for entry in plan.timeline:
            entity_id = entry.entity_id
            kind = _enum_value(entry.entity_type, "")
            if kind == "transport_leg" and entity_id in legs:
                route = _route_from_leg(legs[entity_id], sources, now)
                routes.append(route)
                add_timeline("route", route.route_id)
                last_endpoint = route.to_endpoint
                first_endpoint = first_endpoint or route.from_endpoint
                route_since_place = True
                if route.route_status == "missing":
                    day_warnings.append(f"交通段 {route.from_endpoint.name} → {route.to_endpoint.name} 路线未知。")
                if route.distance_m is None and route.mode != "walk":
                    missing.append(f"days[{index - 1}].routes[{len(routes) - 1}].distance_m")
                continue
            activity = None
            meal = None
            endpoint = None
            if kind == "visit_stop" and entity_id in visits:
                stop = visits[entity_id]
                activity = _activity_from_visit(stop, sources, now)
                endpoint = DatasetEndpoint(
                    name=stop.name,
                    place_id=stop.place_id,
                    latitude=getattr(stop, "latitude", None),
                    longitude=getattr(stop, "longitude", None),
                )
            elif kind == "custom_block" and entity_id in blocks:
                activity = _activity_from_block(blocks[entity_id])
                # A custom block has no place of its own: it neither creates a
                # route gap nor moves the day's current place.
                endpoint = None
            elif kind == "dining_stop" and entity_id in dining:
                stop = dining[entity_id]
                meal = _meal_from_stop(stop, party_size, sources, now)
                endpoint = DatasetEndpoint(
                    name=stop.name,
                    place_id=stop.place_id,
                    latitude=getattr(stop, "latitude", None),
                    longitude=getattr(stop, "longitude", None),
                )
            elif kind == "lodging_stay":
                if entity_id in lodging_by_id:
                    lodging_stay_id = entity_id
                    add_timeline("lodging", entity_id)
                continue
            else:
                continue
            if endpoint is not None:
                first_endpoint = first_endpoint or endpoint
                if last_endpoint is not None and not route_since_place:
                    gap = _gap_route(last_endpoint, endpoint)
                    routes.append(gap)
                    add_timeline("route", gap.route_id)
                    if gap.distance_m is None:
                        missing.append(f"days[{index - 1}].routes[{len(routes) - 1}].distance_m")
                    else:
                        estimated.append(f"days[{index - 1}].routes[{len(routes) - 1}].distance_m")
                    day_assumptions.extend(gap.assumptions)
            if activity is not None:
                activities.append(activity)
                add_timeline("activity", activity.activity_id)
            if meal is not None:
                meals.append(meal)
                add_timeline("meal", meal.meal_id)
            if endpoint is not None:
                last_endpoint = endpoint
                route_since_place = False

        present_meals = {item.meal_type: item for item in meals}
        for slot in _MEAL_SLOTS:
            if slot not in present_meals:
                meals.append(
                    Meal(
                        meal_id=f"not_planned:{slot}",
                        meal_type=slot,
                        status="not_planned",
                        price_type="unknown",
                        confidence="unknown",
                        assumptions=[
                            Assumption(
                                code=f"{slot}_not_planned",
                                text="行程未安排这一餐，费用与餐厅保持未知。",
                            )
                        ],
                    )
                )
        meals.sort(key=lambda item: (0 if item.start_at else 1, item.start_at or now))

        weather = _day_weather(plan, bundle, sources, now)
        if weather is None:
            day_warnings.append("这一天没有可用的天气快照，天气相关判断应保持未知。")
            missing.append(f"days[{index - 1}].weather")

        metrics, metric_warnings, metric_estimates = _metrics(activities, routes, meals)
        day_warnings.extend(metric_warnings)
        estimated.extend(f"days[{index - 1}].metrics.{field}" for field in metric_estimates)
        if metrics.walking_km is None:
            missing.append(f"days[{index - 1}].metrics.walking_km")
        if metrics.outdoor_minutes is None:
            missing.append(f"days[{index - 1}].metrics.outdoor_minutes")
        if metrics.rest_minutes is None:
            missing.append(f"days[{index - 1}].metrics.rest_minutes")
        if any(item.duration_minutes is None for item in activities):
            missing.append(f"days[{index - 1}].activities.duration_minutes")

        destination_name = ""
        if trip.destination_ids:
            try:
                position = trip.destination_ids.index(plan.destination_id)
                destination_name = trip.destination_names[position]
            except (ValueError, IndexError):
                destination_name = ""

        days.append(
            DayDataset(
                day_id=plan.day_id,
                day_index=index,
                date=plan.date,
                timezone=trip.timezone,
                destination_id=plan.destination_id,
                destination_name=destination_name,
                start_place=first_endpoint,
                end_place=last_endpoint,
                timeline=timeline_items,
                activities=activities,
                meals=meals,
                routes=routes,
                lodging_stay_id=lodging_stay_id,
                weather=weather,
                metrics=metrics,
                warnings=day_warnings,
                assumptions=day_assumptions,
            )
        )

    cost_items = _cost_items(itinerary, lodgings, party_size, sources, now)
    for item in cost_items:
        if item.price_type == "unknown":
            missing.append(f"costs.{item.cost_id}.amount_cny")
    if not cost_items:
        warnings.append("行程没有任何费用条目，总费用保持未知。")
    llm_total = getattr(
        getattr(itinerary, "cost_summary", None), "llm_estimated_total_cny", None
    )
    if llm_total is not None:
        warnings.append(
            f"模型估算总额 ¥{_money(llm_total)} 未计入数据集合计；它不是报价，也不是程序估算。"
        )

    dataset_id = "tds_" + hashlib.sha256(
        "|".join(
            [
                DATASET_SCHEMA_VERSION,
                bundle.manifest.bundle_id,
                str(bundle.manifest.workspace_revision),
                str(bundle.manifest.fact_data_revision),
                str(bundle.manifest.weather_data_revision),
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]
    compatibility = DatasetCompatibility(
        legacy_bundle_contract=DELIVERY_BUNDLE_CONTRACT_VERSION,
        legacy_workspace_contract=str(_attr(workspace, "contract_version", "") or ""),
        legacy_fact_contract=str(_attr(getattr(bundle, "fact_snapshot", None), "contract_version", "") or ""),
        legacy_weather_contract=str(_attr(getattr(bundle, "weather_snapshot", None), "contract_version", "") or ""),
        notes=[
            "本数据集是 Delivery Bundle 的只读投影，不改变原行程与导出。",
            "未知字段保持 null 并在 coverage.missing_fields 中列出。",
        ],
    )
    global_assumptions = [
        Assumption(
            code="no_model_numbers",
            text="数据集不采用模型生成的数字；数值只来自行程实体、事实来源或具名程序估算。",
        ),
        Assumption(
            code="costs_summed_by_backend",
            text="所有费用汇总由后端 Decimal 计算，调用方不应再次相加。",
        ),
        Assumption(
            code="walking_scope",
            text="步行统计只覆盖行程时间线中的步行段；往返住宿、临时绕行等未排程步行不计入。",
        ),
    ]
    return TripDataset(
        dataset_id=dataset_id,
        generated_at=now,
        compatibility=compatibility,
        trip=trip,
        days=days,
        lodgings=lodgings,
        costs=summarize_costs(cost_items),
        sources=sources.citations,
        data_sources=_data_sources(settings),
        coverage=DatasetCoverage(
            warnings=list(dict.fromkeys(warnings + [w for day in days for w in day.warnings])),
            missing_fields=list(dict.fromkeys(missing)),
            estimated_fields=list(dict.fromkeys(estimated)),
        ),
        assumptions=global_assumptions,
    )


__all__ = ["build_trip_dataset"]

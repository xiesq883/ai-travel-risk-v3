from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from travel_agent.entities.trip_dataset import TripDataset
from travel_agent.services.trip_dataset_builder import build_trip_dataset

NOW = datetime(2026, 10, 17, 4, tzinfo=timezone.utc)
TZ = timezone(timedelta(hours=8))


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def source(source_id, kind, provider, title, url):
    return NS(
        source_record_id=source_id,
        source_kind=kind,
        provider_name=provider,
        title=title,
        canonical_url=url,
        public_excerpt="公开页面摘要，仅作参考。",
        published_at=None,
        retrieved_at=NOW,
        lifecycle_status="active",
    )


def fact(fact_id, entity_type, entity_id, field_path, source_id, status="verified"):
    return NS(
        fact_assertion_id=fact_id,
        entity_ref=NS(entity_type=entity_type, entity_id=entity_id),
        field_path=field_path,
        status=status,
        expires_at=NOW + timedelta(hours=6) if status == "verified" else NOW - timedelta(hours=1),
        observed_at=NOW,
        source_links=[NS(source_record_id=source_id, relation="supports")],
    )


def lineage(fact_ids=(), source_ids=()):
    return NS(fact_assertion_ids=list(fact_ids), source_record_ids=list(source_ids))


def bundle_fixture():
    leg_rail = NS(
        transport_leg_id="leg-rail",
        transport_class="long_distance",
        selected_mode="high_speed_rail",
        from_endpoint=NS(name="武汉", place_id="12306:WHN", latitude=30.6098, longitude=114.4189),
        to_endpoint=NS(name="杭州东", place_id="12306:HGH", latitude=30.2938, longitude=120.2087),
        departure_at=at(18, 8),
        arrival_at=at(18, 12),
        duration_minutes=240,
        distance_meters=None,
        total_cost_cny=354.0,
        transfer_count=0,
        route_status="ready",
        segments=[
            NS(
                segment_id="seg-1",
                mode="high_speed_rail",
                from_endpoint=NS(name="武汉"),
                to_endpoint=NS(name="杭州东"),
                departure_at=at(18, 8),
                arrival_at=at(18, 12),
                duration_minutes=240,
                distance_meters=None,
                service_number="G1792",
                line_name=None,
                cost_cny=354.0,
            )
        ],
        lineage=lineage(["fact-fare"], ["source-12306"]),
    )
    leg_metro = NS(
        transport_leg_id="leg-metro",
        transport_class="public_transit",
        selected_mode="metro",
        from_endpoint=NS(name="杭州东", place_id="12306:HGH", latitude=30.2938, longitude=120.2087),
        to_endpoint=NS(name="雷峰塔", place_id="osm:way:1", latitude=30.2311, longitude=120.1489),
        departure_at=None,
        arrival_at=None,
        duration_minutes=25,
        distance_meters=None,
        total_cost_cny=None,
        transfer_count=0,
        route_status="ready",
        segments=[],
        lineage=lineage(),
    )
    leg_walk = NS(
        transport_leg_id="leg-walk",
        transport_class="flexible",
        selected_mode="walk",
        from_endpoint=NS(name="浙江省博物馆", place_id="osm:way:2", latitude=30.2530, longitude=120.1370),
        to_endpoint=NS(name="楼外楼", place_id="osm:node:3", latitude=30.2527, longitude=120.1361),
        departure_at=None,
        arrival_at=None,
        duration_minutes=15,
        distance_meters=None,
        total_cost_cny=None,
        transfer_count=0,
        route_status="ready",
        segments=[],
        lineage=lineage(),
    )
    visit_lake = NS(
        item_id="visit-lake",
        day_id="day-1",
        place_id="osm:way:1",
        name="雷峰塔",
        address="杭州市西湖区",
        latitude=30.2311,
        longitude=120.1489,
        planned_start=at(18, 15),
        planned_end=at(18, 16, 30),
        duration_minutes=90,
        estimated_cost_cny=40.0,
        visit_type="nature",
        lineage=lineage(["fact-ticket"], ["source-ticket"]),
    )
    visit_museum = NS(
        item_id="visit-museum",
        day_id="day-2",
        place_id="osm:way:2",
        name="浙江省博物馆",
        address="杭州市西湖区",
        latitude=30.2530,
        longitude=120.1370,
        planned_start=at(19, 9),
        planned_end=at(19, 10),
        duration_minutes=60,
        estimated_cost_cny=None,
        visit_type="culture",
        lineage=lineage(),
    )
    dining_lunch = NS(
        item_id="dining-lunch",
        day_id="day-1",
        place_id="osm:node:3",
        name="楼外楼",
        address="杭州市西湖区孤山路",
        latitude=30.2527,
        longitude=120.1361,
        planned_start=at(18, 18, 30),
        planned_end=at(18, 20),
        duration_minutes=90,
        estimated_cost_cny=None,
        meal_type="lunch",
        average_spend_cny=80.0,
        lineage=lineage(["fact-dining"], ["source-dianping"]),
    )
    dining_dinner = NS(
        item_id="dining-dinner",
        day_id="day-2",
        place_id="osm:node:4",
        name="杭州酒家",
        address="杭州市上城区延安路",
        latitude=None,
        longitude=None,
        planned_start=at(19, 18),
        planned_end=at(19, 19, 30),
        duration_minutes=90,
        estimated_cost_cny=None,
        meal_type="dinner",
        average_spend_cny=None,
        lineage=lineage(),
    )
    custom = NS(
        item_id="custom-1",
        day_id="day-2",
        title="自由活动",
        planned_start=at(19, 15),
        planned_end=at(19, 16),
        duration_minutes=60,
    )
    lodging = NS(
        stay_id="stay-1",
        place_id="osm:node:9",
        name="西湖边的酒店",
        address="杭州市西湖区",
        check_in_date=date(2026, 10, 18),
        check_out_date=date(2026, 10, 19),
        nights=1,
        nightly_price_cny=480.0,
        total_price_cny=480.0,
        price_kind="reference_estimate",
        availability_status="needs_confirmation",
        lineage=lineage(),
    )
    itinerary = NS(
        title="杭州两日文化行",
        destination_ids=["hangzhou"],
        day_plans=[
            NS(
                day_id="day-1",
                day=1,
                date=date(2026, 10, 18),
                destination_id="hangzhou",
                theme="西湖与雷峰塔",
                timeline=[
                    NS(entry_id="e1", entity_type="transport_leg", entity_id="leg-rail", projection_role="full"),
                    NS(entry_id="e2", entity_type="transport_leg", entity_id="leg-metro", projection_role="full"),
                    NS(entry_id="e3", entity_type="visit_stop", entity_id="visit-lake", projection_role="full"),
                    NS(entry_id="e4", entity_type="dining_stop", entity_id="dining-lunch", projection_role="full"),
                ],
            ),
            NS(
                day_id="day-2",
                day=2,
                date=date(2026, 10, 19),
                destination_id="hangzhou",
                theme="博物馆与老字号",
                timeline=[
                    NS(entry_id="e5", entity_type="visit_stop", entity_id="visit-museum", projection_role="full"),
                    NS(entry_id="e6", entity_type="transport_leg", entity_id="leg-walk", projection_role="full"),
                    NS(entry_id="e7", entity_type="dining_stop", entity_id="dining-dinner", projection_role="full"),
                    NS(entry_id="e8", entity_type="custom_block", entity_id="custom-1", projection_role="full"),
                ],
            ),
        ],
        visit_stops=[visit_lake, visit_museum],
        dining_stops=[dining_lunch, dining_dinner],
        lodging_stays=[lodging],
        transport_legs=[leg_rail, leg_metro, leg_walk],
        custom_blocks=[custom],
    )
    weather_day = NS(
        destination_id="hangzhou",
        date=date(2026, 10, 18),
        timezone="Asia/Shanghai",
        data_kind="forecast",
        condition_label="多云",
        high_c=24.0,
        low_c=16.0,
        precipitation_mm=0.0,
        precipitation_probability_pct=20.0,
        wind_speed_kph=9.0,
        condition_code=2,
        fact_assertion_ids=["fact-weather"],
    )
    return NS(
        manifest=NS(
            bundle_id="bundle-ds-1",
            run_id="trip-ds-1",
            generation_id="gen-1",
            workspace_revision=4,
            fact_data_revision=7,
            weather_data_revision=2,
            contract_versions={
                "workspace": "journeypilot.trip_workspace.v10",
                "facts": "journeypilot.fact_store_snapshot.v4",
                "weather": "journeypilot.weather_context_snapshot.v2",
            },
            created_at=NOW,
        ),
        workspace=NS(
            contract_version="journeypilot.trip_workspace.v10",
            run_id="trip-ds-1",
            generation_id="gen-1",
            itinerary=itinerary,
            intent_contract_snapshot=NS(requirements=[NS(text="每天步行不要太多")]),
        ),
        fact_snapshot=NS(
            contract_version="journeypilot.fact_store_snapshot.v4",
            source_records=[
                source("source-12306", "external_tool", "12306", "G1792 票价", "https://www.12306.cn/"),
                source("source-dianping", "external_web", "大众点评", "楼外楼人均", "https://www.dianping.com/"),
                source("source-ticket", "external_web", "景区官网", "雷峰塔门票", "https://example.com/ticket"),
                source("source-weather", "external_tool", "open-meteo", "杭州天气", "https://open-meteo.com/"),
            ],
            fact_assertions=[
                fact("fact-fare", "transport_leg", "leg-rail", "total_cost_cny", "source-12306"),
                fact("fact-dining", "dining_stop", "dining-lunch", "average_spend_cny", "source-dianping"),
                fact("fact-ticket", "visit_stop", "visit-lake", "estimated_cost_cny", "source-ticket", status="stale"),
                fact("fact-weather", "weather_day", "hangzhou:2026-10-18", "high_c", "source-weather"),
            ],
        ),
        weather_snapshot=NS(
            contract_version="journeypilot.weather_context_snapshot.v2",
            retrieved_at=NOW,
            days=[weather_day],
        ),
    )


def test_dataset_keeps_version_basics_and_traceable_sources():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    assert dataset.schema_version == "trip-dataset.v1"
    assert dataset.dataset_id.startswith("tds_")
    assert dataset.trip.party.total == 3
    assert dataset.trip.timezone == "Asia/Shanghai"
    assert dataset.trip.start_date == date(2026, 10, 18)
    assert dataset.trip.end_date == date(2026, 10, 19)
    assert dataset.trip.preferences.style == "culture"
    assert "每天步行不要太多" in dataset.trip.preferences.requirements
    assert {item.citation_id for item in dataset.sources} >= {
        "source-12306",
        "source-dianping",
        "source-ticket",
        "source-weather",
    }
    assert dataset.costs.computed_by == "backend"


def bundle_fixture_identity():
    return {
        "origin": {"name": "武汉", "place_id": "12306:WHN", "latitude": 30.6098, "longitude": 114.4189},
        "destinations": [{"name": "杭州", "place_id": "hangzhou"}],
        "start_date": date(2026, 10, 18),
        "end_date": date(2026, 10, 19),
        "party": {"adults": 2, "children": 1, "elderly_companions": False, "accessibility_required": False},
        "style": {"primary": "culture", "secondary_interests": ["美食"]},
    }


def test_daily_route_walking_and_rest_are_explicit_estimates():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    day = dataset.days[0]
    assert day.day_index == 1
    assert day.start_place.name == "武汉"
    assert day.end_place.name == "楼外楼"
    assert [route.mode for route in day.routes] == ["high_speed_rail", "metro", "walk"]
    assert day.routes[0].steps[0].service_number == "G1792"
    gap = day.routes[-1]
    assert gap.transport_leg_id is None
    assert gap.distance_source == "program_estimate"
    assert gap.distance_m is not None and gap.distance_m > 0
    assert gap.price_type == "unknown"
    assert day.metrics.walking_km is not None and day.metrics.walking_km > 0
    assert "walking_km" in day.metrics.estimated_fields
    assert day.metrics.outdoor_minutes is not None and day.metrics.outdoor_minutes > 0
    assert day.metrics.rest_minutes is not None
    assert any(a.code == "unqueried_walk_gap" for a in gap.assumptions)


def test_day_timeline_preserves_activity_and_route_order():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    day = dataset.days[0]
    assert [item.kind for item in day.timeline] == [
        "route",
        "route",
        "activity",
        "route",
        "meal",
    ]
    assert [item.order for item in day.timeline] == [1, 2, 3, 4, 5]
    assert day.timeline[3].id == day.routes[2].route_id


def test_meal_costs_use_party_size_and_unknown_meals_stay_null():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    lunch = next(item for item in dataset.days[0].meals if item.meal_type == "lunch")
    assert lunch.party_size == 3
    assert lunch.per_person_cny == 80.0
    assert lunch.total_cny == 240.0
    assert lunch.price_type == "estimated"
    breakfast = next(item for item in dataset.days[0].meals if item.meal_type == "breakfast")
    assert breakfast.status == "not_planned"
    assert breakfast.total_cny is None
    assert breakfast.price_type == "unknown"
    dinner = next(item for item in dataset.days[1].meals if item.meal_type == "dinner")
    assert dinner.status == "planned" and dinner.total_cny is None


def test_lodging_reference_price_never_claims_confirmed_availability():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    stay = dataset.lodgings[0]
    assert stay.price_type == "estimated"
    assert stay.availability_status == "needs_confirmation"
    assert stay.room_count is None
    assert stay.total_cny == 480.0
    assert any(a.code == "lodging_not_live_quote" for a in stay.assumptions)


def test_missing_weather_and_unpriced_items_are_unknown_not_zero():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    assert dataset.days[0].weather is not None
    assert dataset.days[0].weather.data_kind == "forecast"
    assert dataset.days[1].weather is None
    assert any("weather" in field for field in dataset.coverage.missing_fields)
    metro = next(item for item in dataset.costs.items if item.cost_id == "cost_leg-metro")
    assert metro.amount_cny is None
    assert metro.price_type == "unknown"
    assert dataset.costs.unknown_item_count >= 1
    assert dataset.costs.complete is False


def test_backend_totals_match_itemized_costs():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    priced = [item for item in dataset.costs.items if item.price_type != "unknown"]
    assert len(priced) == dataset.costs.priced_item_count
    expected = round(sum(item.amount_cny or 0 for item in priced), 2)
    assert dataset.costs.total.point_cny == expected
    assert dataset.costs.transport.point_cny == 354.0
    assert dataset.costs.dining.point_cny == 240.0
    assert dataset.costs.lodging.point_cny == 480.0


def test_dataset_json_round_trip_and_unknown_fields_rejected():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    payload = dataset.model_dump(mode="json")
    assert TripDataset.model_validate(payload) == dataset
    payload["schema_version"] = "trip-dataset.v2"
    with pytest.raises(ValidationError):
        TripDataset.model_validate(payload)
    payload = deepcopy(dataset.model_dump(mode="json"))
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        TripDataset.model_validate(payload)


def test_dataset_never_copies_credentials_into_payload():
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    text = dataset.model_dump_json()
    assert "sk-" not in text
    assert "Authorization" not in text
    assert "api_key=" not in text.lower()


def test_missing_lodging_price_and_route_distance_stay_unknown():
    bundle = bundle_fixture()
    stay = bundle.workspace.itinerary.lodging_stays[0]
    stay.nightly_price_cny = None
    stay.total_price_cny = None
    walk = bundle.workspace.itinerary.transport_legs[2]
    walk.duration_minutes = None
    walk.distance_meters = None

    dataset = build_trip_dataset(bundle, bundle_fixture_identity(), now=NOW, settings=None)

    lodging = dataset.lodgings[0]
    assert lodging.price_type == "unknown"
    assert lodging.total_cny is None
    assert lodging.availability_status != "confirmed"
    assert dataset.days[1].metrics.walking_km is None
    assert any("walking_km" in field for field in dataset.coverage.missing_fields)


def test_legacy_bundle_without_weather_or_facts_degrades_to_unknown():
    bundle = bundle_fixture()
    bundle.weather_snapshot = None
    bundle.fact_snapshot = NS(
        contract_version="",
        source_records=[],
        fact_assertions=[],
    )

    dataset = build_trip_dataset(bundle, bundle_fixture_identity(), now=NOW, settings=None)

    assert all(day.weather is None for day in dataset.days)
    assert all(item.source_ids == [] for item in dataset.costs.items)
    assert dataset.sources == []
    assert all(
        item.price_type in {"estimated", "unknown"} for item in dataset.costs.items
    )
    assert any("weather" in field for field in dataset.coverage.missing_fields)


def test_legacy_entities_without_lineage_field_are_read_as_unknown():
    bundle = bundle_fixture()
    for leg in bundle.workspace.itinerary.transport_legs:
        del leg.lineage
    for stop in bundle.workspace.itinerary.visit_stops:
        del stop.lineage
    for stop in bundle.workspace.itinerary.dining_stops:
        del stop.lineage
    del bundle.workspace.itinerary.lodging_stays[0].lineage

    dataset = build_trip_dataset(bundle, bundle_fixture_identity(), now=NOW, settings=None)

    assert dataset.days[0].routes[0].source_ids == []
    assert dataset.days[0].routes[0].confidence == "unknown"
    assert dataset.days[0].activities[0].confidence == "unknown"
    assert dataset.days[0].meals[0].price_type == "estimated"


def test_build_never_opens_a_network_socket(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("dataset build must stay offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    dataset = build_trip_dataset(bundle_fixture(), bundle_fixture_identity(), now=NOW, settings=None)
    assert dataset.days


def test_json_schema_exposes_required_contract_fields():
    schema = TripDataset.model_json_schema()
    assert {
        "schema_version",
        "dataset_id",
        "trip",
        "days",
        "costs",
        "sources",
        "coverage",
    } <= set(schema["properties"])
    assert {
        "dataset_id",
        "generated_at",
        "compatibility",
        "trip",
        "days",
        "costs",
    } <= set(schema["required"])
    day_schema = schema["$defs"]["DayDataset"]
    assert {"day_id", "date", "activities", "meals", "routes", "metrics"} <= set(
        day_schema["properties"]
    )
    assert {"day_id", "date", "day_index"} <= set(day_schema["required"])
    assert "trip-dataset.v1" in str(schema)


def test_dataset_reports_local_amap_key_as_configured(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    settings = NS(
        mcp_servers={
            "amap-maps": NS(
                env={},
                disabled=True,
                min_interval_seconds=0,
            )
        }
    )
    dataset = build_trip_dataset(
        bundle_fixture(),
        bundle_fixture_identity(),
        now=NOW,
        settings=settings,
    )
    amap = next(item for item in dataset.data_sources if item.source_id == "amap-maps")
    assert amap.configured is True
    assert "AMAP_WEB_SERVICE_KEY" in amap.required_env

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_trip_dataset import NOW, bundle_fixture, bundle_fixture_identity

from travel_agent.entities.trip_dataset import (
    CostItem,
    TripDataset,
    summarize_costs,
)
from travel_agent.services.travel_risk_engine import TravelRiskEngine
from travel_agent.services.trip_dataset_builder import build_trip_dataset
from travel_agent.services.trip_dataset_risk_adapter import risk_input_from_dataset


def dataset_fixture():
    return build_trip_dataset(
        bundle_fixture(),
        bundle_fixture_identity(),
        now=NOW,
        settings=None,
    )


def fully_priced(dataset: TripDataset) -> TripDataset:
    payload = dataset.model_dump(mode="json")
    for item in payload["costs"]["items"]:
        if item["price_type"] == "unknown":
            item.update(
                amount_cny=100.0,
                low_cny=100.0,
                high_cny=100.0,
                price_type="estimated",
                price_basis="itinerary_estimate",
            )
    items = [CostItem.model_validate(item) for item in payload["costs"]["items"]]
    payload["costs"] = summarize_costs(items).model_dump(mode="json")
    return TripDataset.model_validate(payload)


def test_import_maps_days_costs_and_provenance_without_mutation():
    dataset = dataset_fixture()
    before = dataset.model_dump(mode="json")

    request, summary = risk_input_from_dataset(dataset, budget_cap_cny=6000)

    assert request.title == dataset.trip.title
    assert request.budget_cap_cny == 6000
    assert len(request.days) == len(dataset.days)
    assert request.costs_complete is False
    assert summary.cost_coverage == "partial"
    assert summary.unknown_cost_count == dataset.costs.unknown_item_count
    first = request.days[0]
    assert first.walking_km == dataset.days[0].metrics.walking_km
    assert first.walking_km_estimated is True
    assert first.rest_minutes == dataset.days[0].metrics.rest_minutes
    assert first.rest_minutes_estimated is True
    assert first.transport_coverage == "estimated"
    assert first.transport_complete is False
    assert first.weather.condition_code == 2
    assert dataset.model_dump(mode="json") == before


def test_cost_sum_is_not_double_counted():
    dataset = dataset_fixture()
    request, _ = risk_input_from_dataset(dataset, budget_cap_cny=6000)

    known = [cost for cost in request.costs if cost.amount_cny is not None]
    assert len(known) == dataset.costs.priced_item_count
    assert round(sum(cost.amount_cny or 0 for cost in known), 2) == dataset.costs.total.point_cny
    unknown = [cost for cost in request.costs if cost.amount_cny is None]
    assert unknown and all(cost.basis == "unknown" for cost in unknown)


def test_only_budget_is_needed_for_a_complete_cost_dataset():
    dataset = fully_priced(dataset_fixture())
    request, summary = risk_input_from_dataset(dataset, budget_cap_cny=5000)

    assert request.costs_complete is True
    assert summary.cost_coverage == "complete"
    report = TravelRiskEngine().assess(
        request,
        input_origin="journeypilot",
        bundle_id=dataset.trip.bundle_id,
    )
    budget = next(item for item in report.dimensions if item.category == "budget")
    assert budget.level == "low"
    assert "budget_cap_cny" not in budget.missing_data


def test_budget_over_cap_is_high_without_per_day_input():
    dataset = fully_priced(dataset_fixture())
    request, _ = risk_input_from_dataset(dataset, budget_cap_cny=1000)
    report = TravelRiskEngine().assess(request, input_origin="journeypilot")
    budget = next(item for item in report.dimensions if item.category == "budget")
    assert budget.level == "high"


def test_estimated_values_are_flagged_and_keep_dimension_partial():
    dataset = dataset_fixture()
    request, _ = risk_input_from_dataset(dataset, budget_cap_cny=6000)
    report = TravelRiskEngine().assess(request, input_origin="journeypilot")
    fatigue = next(item for item in report.dimensions if item.category == "fatigue")
    assert fatigue.estimated_data
    assert fatigue.coverage == "partial"
    transport = next(item for item in report.dimensions if item.category == "transport")
    assert any("估算" in row for row in transport.estimated_data)


def test_missing_weather_stays_unknown_and_is_explained():
    dataset = dataset_fixture()
    request, _ = risk_input_from_dataset(dataset, budget_cap_cny=6000)
    report = TravelRiskEngine().assess(request, input_origin="journeypilot")
    weather = next(item for item in report.dimensions if item.category == "weather")
    assert weather.level == "unknown"
    assert weather.missing_data
    assert any("预报" in item or "天气" in item for item in weather.missing_data)


def test_schema_version_is_checked():
    dataset = dataset_fixture()
    payload = dataset.model_dump(mode="json")
    payload["schema_version"] = "trip-dataset.v2"
    with pytest.raises(Exception):
        TripDataset.model_validate(payload)

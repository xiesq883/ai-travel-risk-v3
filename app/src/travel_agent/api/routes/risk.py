"""Risk analysis is read-only and requires no LLM or paid provider calls."""
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field

from ...builders import get_components
from ...entities.risk_dataset_import import DatasetImportSummary
from ...entities.travel_risk import (
    RiskAssessment,
    RiskAssessmentInput,
    RiskLimits,
    RiskModel,
    RiskOptimizationResult,
)
from ...entities.trip_dataset import TripDataset
from ...infrastructure.delivery_bundle_store import BundleContractSuperseded
from ...services.trip_dataset_builder import build_trip_dataset
from ...services.trip_dataset_risk_adapter import risk_input_from_dataset
from ...services.travel_risk_adapter import risk_input_from_bundle
from ...services.travel_risk_engine import TravelRiskEngine
from ...services.travel_risk_optimizer import TravelRiskOptimizer
from .trip_runs import _get_authorized_run, _raise_bundle_contract_superseded

router = APIRouter(prefix="/api/risk", tags=["travel-risk"])


class TripRiskReview(RiskModel):
    input: RiskAssessmentInput
    assessment: RiskAssessment


class DatasetImportResponse(RiskModel):
    dataset: TripDataset
    input: RiskAssessmentInput
    import_summary: DatasetImportSummary


class DatasetAssessRequest(RiskModel):
    budget_cap_cny: float | None = Field(default=None, gt=0, le=1e10)
    limits: RiskLimits = Field(default_factory=RiskLimits)


class DatasetImportRequest(DatasetAssessRequest):
    dataset: TripDataset


class DatasetRiskReview(RiskModel):
    input: RiskAssessmentInput
    assessment: RiskAssessment
    import_summary: DatasetImportSummary


async def _dataset_for_run(run_id: str, session_id: str | None):
    run = await _get_authorized_run(run_id, session_id=session_id)
    try:
        bundle = await get_components().delivery_bundle_store.get_current(run_id)
    except BundleContractSuperseded as exc:
        _raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    if bundle is None:
        raise HTTPException(
            status_code=404,
            detail="这趟行程尚无已完成的方案，无法导入结构化数据集。",
        )
    dataset = build_trip_dataset(
        bundle,
        getattr(run, "controlled_trip_identity", None),
    )
    return bundle, dataset


@router.post("/assess", response_model=RiskAssessment)
async def assess_risk(
    request: RiskAssessmentInput,
    input_origin: Literal["manual", "journeypilot"] = Query(default="manual"),
    bundle_id: str | None = Query(default=None),
):
    return TravelRiskEngine().assess(request, input_origin=input_origin, bundle_id=bundle_id)


@router.post("/optimize", response_model=RiskOptimizationResult)
async def optimize_risk(
    request: RiskAssessmentInput,
    input_origin: Literal["manual", "journeypilot"] = Query(default="manual"),
    bundle_id: str | None = Query(default=None),
):
    """生成一次可审阅的优化草稿，并用同一规则重新评估。"""
    return TravelRiskOptimizer().optimize(
        request,
        input_origin=input_origin,
        bundle_id=bundle_id,
    )


@router.get("/trips/{run_id}", response_model=TripRiskReview)
async def assess_trip_risk(run_id: str, session_id: str | None = Query(default=None)):
    await _get_authorized_run(run_id, session_id=session_id)
    try:
        bundle = await get_components().delivery_bundle_store.get_current(run_id)
    except BundleContractSuperseded as exc:
        _raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    if bundle is None:
        raise HTTPException(status_code=404, detail="这趟行程尚无已完成的方案，请先完成规划或手动录入。")
    request = risk_input_from_bundle(bundle)
    return TripRiskReview(input=request, assessment=TravelRiskEngine().assess(request, input_origin="journeypilot", bundle_id=bundle.manifest.bundle_id))


@router.get("/example", response_model=RiskAssessmentInput)
async def risk_example():
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    days = []
    for i in range(5):
        date = (now + timedelta(days=i + 1)).date()
        days.append({
            "day_id": f"day-{i + 1}", "date": date, "destination": ["昆明", "大理", "大理", "丽江", "丽江"][i],
            "outdoor_minutes": [120, 240, 180, 300, 90][i], "active_minutes": [360, 660, 420, 540, 300][i],
            "walking_km": [4, 12, 6, 9, 3][i], "rest_minutes": [60, 15, 60, 30, 60][i],
            "weather": {"data_kind": "forecast", "observed_at": now, "precipitation_mm": [0, 25, 2, 1, 0][i], "precipitation_probability_pct": [10, 95, 45, 20, 10][i], "high_c": 24, "low_c": 14, "wind_speed_kph": 10, "condition_code": 65 if i == 1 else 2, "source_label": "演示数据，非实时预报"},
            "transport_complete": True,
            "transports": [{"item_id": f"route-{i}", "name": "当日交通（演示）", "route_status": "ready", "duration_minutes": 180 if i == 1 else 60, "available_minutes": 120 if i == 1 else 90}],
            "connections": [{"name": "换乘（演示）", "available_minutes": 20, "required_minutes": 60}] if i == 1 else [],
        })
    return RiskAssessmentInput.model_validate({
        "title": "云南 5 日 · 风险引擎演示", "is_example": True,
        "budget_cap_cny": 6000, "costs_complete": True,
        "costs": [{"item_id": "transport", "name": "全体交通", "amount_cny": 2200, "upper_cny": 2600}, {"item_id": "hotel", "name": "全部住宿", "amount_cny": 1800}, {"item_id": "food", "name": "全体餐饮", "amount_cny": 1200}, {"item_id": "tickets", "name": "门票与其他", "amount_cny": 1000}], "days": days,
    })


@router.get("/trips/{run_id}/dataset/import", response_model=DatasetImportResponse)
async def import_trip_dataset(
    run_id: str, session_id: str | None = Query(default=None)
):
    """读取当前 Bundle 的结构化数据集，不发起评估、不改动行程。"""
    _, dataset = await _dataset_for_run(run_id, session_id)
    request, summary = risk_input_from_dataset(dataset)
    return DatasetImportResponse(
        dataset=dataset,
        input=request,
        import_summary=summary,
    )


@router.post("/trips/{run_id}/dataset/assess", response_model=DatasetRiskReview)
async def assess_trip_dataset(
    run_id: str,
    body: DatasetAssessRequest,
    session_id: str | None = Query(default=None),
):
    """用数据集导入结果评估；预算上限是唯一的金额输入。"""
    bundle, dataset = await _dataset_for_run(run_id, session_id)
    request, summary = risk_input_from_dataset(
        dataset,
        budget_cap_cny=body.budget_cap_cny,
        limits=body.limits,
    )
    assessment = TravelRiskEngine().assess(
        request,
        input_origin="journeypilot",
        bundle_id=bundle.manifest.bundle_id,
    )
    return DatasetRiskReview(
        input=request,
        assessment=assessment,
        import_summary=summary,
    )


@router.post("/dataset/assess", response_model=DatasetRiskReview)
async def assess_imported_dataset(body: DatasetImportRequest):
    """评估一份离线导入的 trip-dataset.v1（例如导出的 JSON 文件）。"""
    request, summary = risk_input_from_dataset(
        body.dataset,
        budget_cap_cny=body.budget_cap_cny,
        limits=body.limits,
    )
    assessment = TravelRiskEngine().assess(
        request,
        input_origin="journeypilot",
        bundle_id=body.dataset.trip.bundle_id,
    )
    return DatasetRiskReview(
        input=request,
        assessment=assessment,
        import_summary=summary,
    )


@router.post("/dataset/import", response_model=DatasetImportResponse)
async def inspect_imported_dataset(body: DatasetImportRequest):
    """预览一份离线 trip-dataset.v1，不发起评估。"""
    request, summary = risk_input_from_dataset(
        body.dataset,
        budget_cap_cny=body.budget_cap_cny,
        limits=body.limits,
    )
    return DatasetImportResponse(
        dataset=body.dataset,
        input=request,
        import_summary=summary,
    )


@router.get("/dataset/example", response_model=TripDataset)
async def dataset_example():
    """返回仓库内的合成示例，供页面演示；不代表任何真实报价。"""
    path = (
        Path(__file__).resolve().parents[4]
        / "docs"
        / "examples"
        / "trip-dataset.v1.sample.json"
    )
    if not path.is_file():
        raise HTTPException(status_code=404, detail="示例数据集不存在")
    return TripDataset.model_validate_json(path.read_text(encoding="utf-8"))

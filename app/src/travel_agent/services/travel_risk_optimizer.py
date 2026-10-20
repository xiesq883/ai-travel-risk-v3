"""Deterministic, reviewable plan adjustments for the risk assessment loop."""

from __future__ import annotations

from math import ceil
import re

from ..entities.travel_risk import (
    RiskAssessmentInput,
    RiskOptimizationProposal,
    RiskOptimizationResult,
)
from .travel_risk_engine import TravelRiskEngine


class TravelRiskOptimizer:
    """Build a proposed plan, then re-run the same risk engine on it.

    The optimizer never edits the caller's input. Changes that can be expressed as
    schedule quantities are applied to a draft; changes that would invent a price,
    route fact, or missing measurement stay as explicit review items.
    """

    def __init__(self, engine: TravelRiskEngine | None = None) -> None:
        self.engine = engine or TravelRiskEngine()

    def optimize(
        self,
        request: RiskAssessmentInput,
        *,
        assessed_at=None,
        input_origin="manual",
        bundle_id=None,
    ) -> RiskOptimizationResult:
        before = self.engine.assess(
            request,
            assessed_at=assessed_at,
            input_origin=input_origin,
            bundle_id=bundle_id,
        )
        candidate = request.model_copy(deep=True)
        proposals: list[RiskOptimizationProposal] = []
        applied_by_field: dict[str, RiskOptimizationProposal] = {}
        pending_keys: set[str] = set()

        def day_for(day_id):
            return next((day for day in candidate.days if day.day_id == day_id), None)

        def source_value(path):
            return _read_path(request, path)

        def apply_numeric(
            *,
            category,
            rule_id,
            day_id,
            field,
            title,
            reason,
            target,
            unit,
            increase=False,
        ):
            if target is None:
                return
            old = source_value(field)
            if not isinstance(old, (int, float)) or (target <= old if increase else target >= old):
                return
            existing = applied_by_field.get(field)
            if existing is not None:
                if existing.after is not None and target >= existing.after:
                    return
                existing.after = target
                existing.reason = f"{existing.reason}；同时处理 {reason}"
                _write_path(candidate, field, target)
                return
            proposal = RiskOptimizationProposal(
                proposal_id=f"opt-{len(proposals) + 1}",
                category=category,
                rule_id=rule_id,
                day_id=day_id,
                field=field,
                title=title,
                reason=reason,
                before=old,
                after=target,
                unit=unit,
                status="applied",
            )
            proposals.append(proposal)
            applied_by_field[field] = proposal
            _write_path(candidate, field, target)

        def add_pending(*, category, rule_id, day_id, field, title, reason, before_value=None, unit=""):
            key = f"{category}:{field}:{day_id or ''}:{rule_id or ''}:{reason}"
            if key in pending_keys:
                return
            pending_keys.add(key)
            proposals.append(
                RiskOptimizationProposal(
                    proposal_id=f"opt-{len(proposals) + 1}",
                    category=category,
                    rule_id=rule_id,
                    day_id=day_id,
                    field=field,
                    title=title,
                    reason=reason,
                    before=before_value,
                    status="needs_confirmation",
                    requires_confirmation=True,
                    unit=unit,
                )
            )

        for dimension in before.dimensions:
            for finding in dimension.findings:
                if finding.level not in {"high", "medium"}:
                    continue
                day = day_for(finding.day_id) if finding.day_id else None
                if dimension.category == "weather" and day is not None:
                    if day.outdoor_minutes is None:
                        continue
                    target = 0 if finding.level == "high" else round(day.outdoor_minutes * 0.5, 2)
                    apply_numeric(
                        category="weather",
                        rule_id=finding.rule_id,
                        day_id=day.day_id,
                        field=f"days.{day.day_id}.outdoor_minutes",
                        title=(
                            "把受影响户外安排改为室内或备选"
                            if finding.level == "high"
                            else "缩短受天气影响的户外安排"
                        ),
                        reason=finding.suggestion,
                        target=target,
                        unit="分钟",
                    )
                elif dimension.category == "fatigue" and day is not None:
                    if finding.rule_id == "fatigue.walking_km":
                        apply_numeric(
                            category="fatigue",
                            rule_id=finding.rule_id,
                            day_id=day.day_id,
                            field=f"days.{day.day_id}.walking_km",
                            title="把步行距离压到每日偏好上限",
                            reason=finding.suggestion,
                            target=candidate.limits.max_daily_walking_km,
                            unit="km",
                        )
                    elif finding.rule_id == "fatigue.active_minutes":
                        apply_numeric(
                            category="fatigue",
                            rule_id=finding.rule_id,
                            day_id=day.day_id,
                            field=f"days.{day.day_id}.active_minutes",
                            title="把活动加交通时长压到每日偏好上限",
                            reason=finding.suggestion,
                            target=candidate.limits.max_daily_active_hours * 60,
                            unit="分钟",
                        )
                    elif finding.rule_id == "fatigue.rest":
                        current = day.rest_minutes
                        target = candidate.limits.min_daily_rest_minutes
                        if current is None:
                            add_pending(
                                category="fatigue",
                                rule_id=finding.rule_id,
                                day_id=day.day_id,
                                field=f"days.{day.day_id}.rest_minutes",
                                title="补入明确的休息时段",
                                reason=finding.suggestion,
                                before_value=None,
                                unit="分钟",
                            )
                        else:
                            apply_numeric(
                                category="fatigue",
                                rule_id=finding.rule_id,
                                day_id=day.day_id,
                                field=f"days.{day.day_id}.rest_minutes",
                                title="把专门休息补到每日最低要求",
                                reason=finding.suggestion,
                                target=target,
                                unit="分钟",
                                increase=True,
                            )
                elif dimension.category == "transport" and day is not None:
                    if finding.rule_id == "transport.window":
                        leg_id = next(iter(finding.entity_ids), None)
                        leg = next((item for item in day.transports if item.item_id == leg_id), None)
                        if leg and leg.duration_minutes is not None and leg.available_minutes is not None:
                            target = ceil(leg.duration_minutes * 1.25)
                            apply_numeric(
                                category="transport",
                                rule_id=finding.rule_id,
                                day_id=day.day_id,
                                field=f"days.{day.day_id}.transports.{day.transports.index(leg)}.available_minutes",
                                title="为交通安排增加 25% 时间缓冲",
                                reason=f"{finding.suggestion} 优化草稿只调整时间窗口，路线本身仍需核对。",
                                target=target,
                                unit="分钟",
                                increase=True,
                            )
                    elif finding.rule_id == "transport.connection":
                        index = _connection_index(finding, day.day_id)
                        if index is not None and index < len(day.connections):
                            connection = day.connections[index]
                            apply_numeric(
                                category="transport",
                                rule_id=finding.rule_id,
                                day_id=day.day_id,
                                field=f"days.{day.day_id}.connections.{index}.available_minutes",
                                title="把衔接间隔增加到最小要求的 125%",
                                reason=f"{finding.suggestion} 优化草稿只增加规划余量，不能替代承运方要求。",
                                target=ceil(connection.required_minutes * 1.25),
                                unit="分钟",
                                increase=True,
                            )
                elif dimension.category == "budget":
                    add_pending(
                        category="budget",
                        rule_id=finding.rule_id,
                        day_id=None,
                        field="costs",
                        title="确认削减或替换较大支出",
                        reason=f"{finding.suggestion} 系统不会凭空改写价格，请补入折后报价或选择替代项目后再评估。",
                        before_value=dimension.metrics.get("recorded_max_cny"),
                        unit="元",
                    )

            if dimension.missing_data:
                for missing in dimension.missing_data:
                    add_pending(
                        category=dimension.category,
                        rule_id=None,
                        day_id=None,
                        field="missing_data",
                        title="补齐待核实资料",
                        reason=missing,
                    )

        after = self.engine.assess(
            candidate,
            assessed_at=before.assessed_at,
            input_origin=input_origin,
            bundle_id=bundle_id,
        )
        applied_count = sum(p.status == "applied" for p in proposals)
        pending_count = sum(p.status == "needs_confirmation" for p in proposals)
        if not proposals:
            summary = "当前规则没有生成需要修改的项目，可以直接再次评估或继续补充资料。"
        else:
            summary = f"已生成 {applied_count} 项优化草稿并重新评估；另有 {pending_count} 项需要你确认后补充。"
        return RiskOptimizationResult(
            original_input=request,
            optimized_input=candidate,
            before=before,
            after=after,
            proposals=proposals,
            applied_count=applied_count,
            pending_count=pending_count,
            summary=summary,
        )


def _read_path(request: RiskAssessmentInput, path: str):
    parts = path.split(".")
    if not parts or parts[0] != "days":
        return None
    day = next((item for item in request.days if item.day_id == parts[1]), None)
    if day is None:
        return None
    if len(parts) == 3:
        return getattr(day, parts[2], None)
    if parts[2] == "transports" and len(parts) == 5:
        index = int(parts[3])
        return getattr(day.transports[index], parts[4], None)
    if parts[2] == "connections" and len(parts) == 5:
        index = int(parts[3])
        return getattr(day.connections[index], parts[4], None)
    return None


def _write_path(request: RiskAssessmentInput, path: str, value):
    parts = path.split(".")
    day = next(item for item in request.days if item.day_id == parts[1])
    if len(parts) == 3:
        setattr(day, parts[2], value)
    elif parts[2] == "transports" and len(parts) == 5:
        setattr(day.transports[int(parts[3])], parts[4], value)
    elif parts[2] == "connections" and len(parts) == 5:
        setattr(day.connections[int(parts[3])], parts[4], value)


def _connection_index(finding, day_id: str) -> int | None:
    prefix = f"days.{day_id}.connections."
    for evidence in finding.explanation.data:
        if evidence.field.startswith(prefix) and evidence.field.endswith(".available_minutes"):
            match = re.search(r"\.connections\.(\d+)\.available_minutes$", evidence.field)
            if match:
                return int(match.group(1))
    return None

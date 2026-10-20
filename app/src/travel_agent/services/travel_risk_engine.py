"""Deterministic, evidence-labelled weather/budget/transport/fatigue assessment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ..entities.delivery_bundle import WeatherSensitivity
from ..entities.travel_risk import (
    RiskAssessment,
    RiskAssessmentInput,
    RiskCalculation,
    RiskDimensionResult,
    RiskEvidence,
    RiskExplanation,
    RiskFinding,
)
from .weather_impact_engine import (
    OUTDOOR_WEATHER_THRESHOLDS,
    SNOW_CODES,
    THUNDERSTORM_CODES,
    WeatherImpactEngine,
    WeatherMeasures,
)

_RANK = {"unknown": -1, "low": 0, "medium": 1, "high": 2}
_LEVEL_LABEL = {
    "unknown": "待核实",
    "low": "未触发主要阈值",
    "medium": "建议调整",
    "high": "优先调整",
}


def _evidence(
    field, label, value, unit="", *, source=None, sources=None, observed_at=None
):
    return RiskEvidence(
        field=field,
        label=label,
        value=value,
        unit=unit,
        source_label=source or "录入或导入的方案数据，未经本次评估外部核验",
        source_ids=list(dict.fromkeys(sources or [])),
        observed_at=observed_at,
    )


def _calc(expression, result, unit=""):
    return RiskCalculation(expression=expression, result=result, unit=unit)


def _weather_trace(day, condition, level, now):
    weather = day.weather
    fields = {
        "rain": [
            ("precipitation_mm", "降水量", "mm"),
            ("precipitation_probability_pct", "降水概率", "%"),
        ],
        "heat": [("high_c", "最高温", "℃")],
        "cold": [("low_c", "最低温", "℃")],
        "wind": [("wind_speed_kph", "风速", "km/h")],
        "thunderstorm": [("condition_code", "天气现象代码", "WMO")],
        "snow": [("condition_code", "天气现象代码", "WMO")],
    }[condition]
    data = [
        _evidence(
            f"days.{day.day_id}.outdoor_minutes",
            "户外活动",
            day.outdoor_minutes,
            "分钟",
        )
    ]
    data += [
        _evidence(
            f"days.{day.day_id}.weather.{field}",
            label,
            getattr(weather, field),
            unit,
            source=weather.source_label,
            sources=weather.source_ids,
            observed_at=weather.observed_at,
        )
        for field, label, unit in fields
    ]
    data += [
        _evidence(f"days.{day.day_id}.date", "行程日期", day.date.isoformat()),
        _evidence("assessed_at", "评估时间", now.isoformat(), source="评估系统时钟"),
    ]
    age = (now - weather.observed_at).total_seconds() / 3600
    calculation = [_calc(f"预报年龄 = 评估时间 − 采集时间 = {age}", age, "小时")]
    index = {"high": 0, "medium": 1, "low": 2}[level]
    if condition == "rain":
        amount = OUTDOOR_WEATHER_THRESHOLDS["rain"][index]
        probability = OUTDOOR_WEATHER_THRESHOLDS["rain_probability"][index]
        op = ">" if level == "low" else "≥"
        for field, _, unit in fields:
            value = getattr(weather, field)
            bound = amount if field == "precipitation_mm" else probability
            operator = op if field == "precipitation_mm" else "≥"
            matched = value is not None and (
                value > bound if operator == ">" else value >= bound
            )
            calculation.append(
                _calc(
                    f"{value if value is not None else '未知'} {unit} {operator} {bound} {unit}",
                    "未知，未按 0 处理"
                    if value is None
                    else "命中"
                    if matched
                    else "未命中",
                )
            )
        amounts, probabilities = (
            OUTDOOR_WEATHER_THRESHOLDS["rain"],
            OUTDOOR_WEATHER_THRESHOLDS["rain_probability"],
        )
        threshold = f"按最高命中等级：高 ≥{amounts[0]} mm 或 ≥{probabilities[0]}%；中 ≥{amounts[1]} mm 或 ≥{probabilities[1]}%；低 >{amounts[2]} mm 或 ≥{probabilities[2]}%。"
        meaning = "有户外安排，降水量或降水概率达到该级阈值，可能影响户外游览与移动；等级不代表发生事故的概率。"
    elif condition in {"thunderstorm", "snow"}:
        codes = sorted(
            THUNDERSTORM_CODES if condition == "thunderstorm" else SNOW_CODES
        )
        calculation.append(
            _calc(
                f"天气代码 {weather.condition_code} ∈ {codes}，且户外时长 > 0", "命中"
            )
        )
        threshold = f"户外天气代码属于 {codes} 时为高风险。"
        meaning = "预报含雷暴或降雪，暴露在户外的活动需要优先调整；应复核官方公告。"
    else:
        bound = OUTDOOR_WEATHER_THRESHOLDS[condition][index]
        value = getattr(weather, fields[0][0])
        operator = "≤" if condition == "cold" else "≥"
        calculation.append(
            _calc(f"{value} {fields[0][2]} {operator} {bound} {fields[0][2]}", "命中")
        )
        bounds = OUTDOOR_WEATHER_THRESHOLDS[condition]
        threshold = f"按最高命中等级：高 {operator}{bounds[0]}；中 {operator}{bounds[1]}；低 {operator}{bounds[2]}，单位 {fields[0][2]}。"
        meaning = "当天存在户外活动，温度或风速达到该级阈值，可能增加不适和行程执行难度；应调整暴露时间。"
    return dict(
        data=data, calculation=calculation, threshold=threshold, meaning=meaning
    )


def _result(
    category,
    label,
    findings,
    missing,
    known,
    metrics=None,
    context=None,
    checks=None,
    estimated=None,
):
    missing = list(dict.fromkeys(missing))
    estimated = list(dict.fromkeys(estimated or []))
    coverage = (
        "complete"
        if not missing and not estimated
        else "partial"
        if known
        else "missing"
    )
    level = max(
        (f.level for f in findings if f.level != "unknown"),
        key=_RANK.get,
        default="low",
    )
    if missing and level == "low":
        level = "unknown"
    evidence = (
        list(context or [])
        + [
            _evidence(
                f"{category}.finding.{i}", f.title, f.level, source=f"规则 {f.rule_id}"
            )
            for i, f in enumerate(findings)
        ]
        + [
            _evidence(f"{category}.missing.{i}", text, None, source="资料完整性检查")
            for i, text in enumerate(missing)
        ]
        + [
            _evidence(
                f"{category}.estimated.{i}",
                text,
                None,
                source="程序估算，不是原始行程实测值",
            )
            for i, text in enumerate(estimated)
        ]
    )
    if not evidence:
        evidence = [_evidence(f"{category}.known", "已检查的有效数据项", known, "项")]
    policies = {
        "weather": f"户外降水 ≥{OUTDOOR_WEATHER_THRESHOLDS['rain'][0]} mm 或概率 ≥{OUTDOOR_WEATHER_THRESHOLDS['rain_probability'][0]}% 为高，≥{OUTDOOR_WEATHER_THRESHOLDS['rain'][1]} mm 或 ≥{OUTDOOR_WEATHER_THRESHOLDS['rain_probability'][1]}% 为中；较小降水也保留低级提醒。温度、风速、雷暴和降雪一并核对。仅采用有效预报。",
        "budget": "费用上界 >100% 预算为高；≥90% 且 ≤100% 为中；<90% 且资料完整才为低。",
        "transport": "时长超窗口为高；衔接间隔低于最小要求为高，达到最小要求但不足其 125% 为中。",
        "fatigue": "步行或活动时长 >偏好上限为中，>125% 上限为高；休息 <最低偏好为中。等于阈值不向上升档。",
    }
    explanation = RiskExplanation(
        data=evidence,
        calculation=list(checks or [])
        + [
            _calc(
                "已触发规则按高 > 中 > 低取最高等级；无触发项时先记为低",
                max((f.level for f in findings), key=_RANK.get, default="low"),
            ),
            _calc(
                f"待补资料 {len(missing)} 项；若有缺项且当前仅为低，则改为待核实",
                level,
            ),
        ],
        rule=policies[category]
        + " 高/中风险保留；资料不足不能据此给出低风险。规则等级不是概率。",
        risk_level=level,
        explanation=(
            "当前资料不足以排除风险；请补充或刷新列出的数据后再评估。"
            if level == "unknown"
            else "已知数据命中下方规则，按其中最高等级汇总。"
            if findings
            else "按当前完整输入未触发风险阈值；这不保证实际旅行没有风险。"
        )
        + (
            " 仍有缺项，其他风险可能尚未识别。"
            if missing and level != "unknown"
            else ""
        ),
    )
    return RiskDimensionResult(
        category=category,
        label=label,
        level=level,
        coverage=coverage,
        summary=_LEVEL_LABEL[level]
        + ("，仍有数据待补充" if missing and level != "unknown" else "")
        + ("，部分数据为估算" if estimated else ""),
        explanation=explanation,
        metrics=metrics or {},
        findings=findings,
        missing_data=missing,
        estimated_data=estimated,
    )


def _finding(
    rule,
    level,
    title,
    reason,
    suggestion,
    day=None,
    entities=None,
    sources=None,
    *,
    data,
    calculation,
    threshold,
    meaning,
):
    return RiskFinding(
        rule_id=rule,
        level=level,
        title=title,
        reason=reason,
        suggestion=suggestion,
        explanation=RiskExplanation(
            data=data,
            calculation=calculation,
            rule=threshold,
            risk_level=level,
            explanation=meaning,
        ),
        day_id=day.day_id if day else None,
        entity_ids=list(
            dict.fromkeys(
                entities if entities is not None else day.entity_ids if day else []
            )
        ),
        source_ids=list(dict.fromkeys(sources or [])),
    )


class TravelRiskEngine:
    """Versioned heuristics; risk levels are not probabilities or guarantees."""

    def assess(
        self,
        request: RiskAssessmentInput,
        *,
        assessed_at=None,
        input_origin="manual",
        bundle_id=None,
    ) -> RiskAssessment:
        now = assessed_at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("评估时间必须包含时区")
        dimensions = [
            self._weather(request, now),
            self._budget(request),
            self._transport(request),
            self._fatigue(request),
        ]
        for dimension in dimensions:
            for chain in [
                dimension.explanation,
                *(f.explanation for f in dimension.findings),
            ]:
                for item in chain.data:
                    if request.is_example and not item.source_label.startswith(
                        "演示数据"
                    ):
                        item.source_label = (
                            "演示数据（非实时核验） · " + item.source_label
                        )
        complete = all(d.coverage == "complete" for d in dimensions)
        level = max((d.level for d in dimensions), key=_RANK.get)
        if not complete and level == "low":
            level = "unknown"
        summary = {
            "high": "先处理高风险项，再决定是否采用这个方案。",
            "medium": "建议调整标出的环节，并复核后再决定。",
            "low": "按当前输入未触发主要阈值；出发前仍需复核。",
            "unknown": "信息还不足，暂时无法判断这个方案是否可靠。",
        }[level]
        if not complete and level != "unknown":
            summary += " 部分信息缺失，其他风险仍待核实。"
        return RiskAssessment(
            assessed_at=now,
            title=request.title,
            is_example=request.is_example,
            input_origin=input_origin,
            bundle_id=bundle_id,
            overall_level=level,
            data_complete=complete,
            summary=summary,
            dimensions=dimensions,
            assumptions=[
                "只评估天气、预算、交通、体力四项；规则等级不是事故概率或安全保证。",
                "预算统一按整趟旅行、全部同行人的人民币总额计算；估算、报价和已付金额分别标记。",
                "预算使用录入的金额区间，达到上限 90% 提醒；缺项不会按 0 元处理。",
                "天气仅采用 24 小时内采集、覆盖对应日期的预报，自采集日期起最多 7 天；季节资料不当作预报。户外降水 ≥20 mm 或概率 ≥90% 为高，≥5 mm 或概率 ≥65% 为中。",
                "户外最高温 ≥40℃ / ≥35℃、最低温 ≤−10℃ / ≤0℃、风速 ≥45 / ≥30 km/h，分别对应高 / 中风险；雷暴和降雪对户外活动标为高风险。",
                f"体力按自定义上限比较：每天步行 {request.limits.max_daily_walking_km} km、活动加交通 {request.limits.max_daily_active_hours} 小时、休息至少 {request.limits.min_daily_rest_minutes} 分钟；超上限 25% 标为高风险。",
                "交通缓冲是规划余量，不能替代承运方的最短换乘要求；缺路线或时长时保留待核实。",
            ],
        )

    def _weather(self, request, now):
        findings, missing, known, estimated = [], [], 0, []
        context, checks = [], []
        evaluator = WeatherImpactEngine()
        sensitivity = WeatherSensitivity(
            exposure="outdoor",
            rain_sensitivity="high",
            heat_sensitivity="high",
            cold_sensitivity="high",
            wind_sensitivity="high",
            requires_clear_visibility=False,
        )
        names = {
            "rain": "降雨",
            "heat": "高温",
            "cold": "低温",
            "wind": "大风",
            "thunderstorm": "雷暴",
            "snow": "降雪",
            "visibility": "能见度",
        }
        suggestions = {
            "rain": "把受影响的户外活动改到室内，或调整日期并预留雨具和交通余量。",
            "heat": "把户外活动移到较凉时段，缩短连续户外时间并增加休息。",
            "cold": "减少长时间户外停留，核对保暖条件和室内备选。",
            "wind": "调整暴露在风中的活动，并复核场所和交通的最新公告。",
            "thunderstorm": "优先替换户外活动，并复核官方天气与场所公告。",
            "snow": "调整户外安排，并复核道路和场所开放情况。",
        }
        for day in request.days:
            label = f"{day.date} {day.destination}".strip()
            if day.outdoor_minutes is None:
                missing.append(f"{label}：户外活动时长未填写")
            weather = day.weather
            context.extend(
                [
                    _evidence(
                        f"days.{day.day_id}.date", "行程日期", day.date.isoformat()
                    ),
                    _evidence(
                        f"days.{day.day_id}.weather.data_kind",
                        f"{label} 资料类型",
                        weather.data_kind,
                        source=weather.source_label,
                        sources=weather.source_ids,
                        observed_at=weather.observed_at,
                    ),
                    _evidence(
                        f"days.{day.day_id}.weather.observed_at",
                        f"{label} 采集时间",
                        weather.observed_at.isoformat()
                        if weather.observed_at
                        else None,
                        source=weather.source_label,
                    ),
                    _evidence(
                        f"days.{day.day_id}.weather.forecast_end_date",
                        "预报声明截止日",
                        weather.forecast_end_date.isoformat()
                        if weather.forecast_end_date
                        else None,
                        source=weather.source_label,
                    ),
                    _evidence(
                        f"days.{day.day_id}.outdoor_minutes",
                        f"{label} 户外时长",
                        day.outdoor_minutes,
                        "分钟",
                        source=(
                            "程序估算，不是原始行程实测值"
                            if day.outdoor_minutes_estimated
                            else "导入的行程数据，未经本次评估外部核验"
                        ),
                    ),
                ]
            )
            if day.outdoor_minutes is not None and day.outdoor_minutes_estimated:
                estimated.append(f"{label}：户外时长为程序估算")
            if weather.observed_at:
                checks.extend(
                    [
                        _calc(
                            f"{label} 采集年龄 = {now.isoformat()} − {weather.observed_at.isoformat()}",
                            (now - weather.observed_at).total_seconds() / 3600,
                            "小时",
                        ),
                        _calc(
                            "可用截止日 = min(声明截止日或采集日+6天，采集日+6天)",
                            min(
                                weather.forecast_end_date
                                or weather.observed_at.date() + timedelta(days=6),
                                weather.observed_at.date() + timedelta(days=6),
                            ).isoformat(),
                        ),
                    ]
                )
            local_today = (
                now.astimezone(weather.observed_at.tzinfo).date()
                if weather.observed_at
                else now.date()
            )
            invalid = None
            if weather.data_kind == "unavailable":
                invalid = "没有可用的对应日期预报"
            elif weather.data_kind != "forecast":
                invalid = "缺少对应日期预报（季节资料不能预测这一天）"
            elif not weather.observed_at:
                invalid = "预报采集时间未知"
            elif weather.observed_at > now + timedelta(minutes=5):
                invalid = "预报采集时间晚于评估时间，请核对时间"
            elif now - weather.observed_at > timedelta(hours=24):
                invalid = "预报已超过 24 小时，需要刷新"
            elif day.date < local_today:
                invalid = "日期已经过去，不能用当前预报判断"
            elif day.date > min(
                weather.forecast_end_date
                or weather.observed_at.date() + timedelta(days=6),
                weather.observed_at.date() + timedelta(days=6),
            ):
                invalid = "日期超出本版可用的 7 天预报窗口"
            if invalid:
                missing.append(f"{label}：{invalid}")
                checks.append(_calc(f"{label} 预报有效性检查", f"不可采用：{invalid}"))
                continue
            checks.append(
                _calc(
                    f"{label}：forecast 类型、采集年龄 ≤24 小时、未来偏差 ≤5 分钟、日期在采集日起至多 7 天且不超过预报截止日",
                    "通过",
                )
            )
            if day.outdoor_minutes == 0:
                known += 1
                checks.append(
                    _calc(f"{label} 户外时长 = 0，跳过户外天气阈值", "未触发")
                )
                continue
            for field, title, unit in (
                ("precipitation_mm", "降水量", "mm"),
                ("precipitation_probability_pct", "降水概率", "%"),
                ("high_c", "最高温", "℃"),
                ("low_c", "最低温", "℃"),
                ("wind_speed_kph", "风速", "km/h"),
                ("condition_code", "天气现象代码", "WMO"),
            ):
                context.append(
                    _evidence(
                        f"days.{day.day_id}.weather.{field}",
                        f"{label} {title}",
                        getattr(weather, field),
                        unit,
                        source=weather.source_label,
                        sources=weather.source_ids,
                        observed_at=weather.observed_at,
                    )
                )
                if getattr(weather, field) is None:
                    missing.append(f"{label}：缺少{title}")
            known += int(
                any(
                    getattr(weather, f) is not None
                    for f in ("precipitation_mm", "high_c", "condition_code")
                )
            )
            if day.outdoor_minutes is None:
                continue
            measures = WeatherMeasures(
                high_c=weather.high_c,
                low_c=weather.low_c,
                precipitation_mm=weather.precipitation_mm,
                precipitation_probability_pct=weather.precipitation_probability_pct,
                wind_speed_kph=weather.wind_speed_kph,
                condition_code=weather.condition_code,
            )
            levels = evaluator.condition_levels(measures, sensitivity)
            checks.append(
                _calc(
                    f"{label}：户外时长 >0 时，用共享天气规则逐项比较降雨、温度、风速与天气代码",
                    "；".join(f"{names[c]}={level}" for c, level in levels)
                    or "已知数值未触发；缺失字段仍待核实",
                )
            )
            for condition, level in levels:
                findings.append(
                    _finding(
                        f"weather.{condition}",
                        level,
                        f"{label}：户外活动受{names[condition]}影响",
                        f"户外 {day.outdoor_minutes / 60} 小时；降水 {weather.precipitation_mm if weather.precipitation_mm is not None else '未知'} mm、降水概率 {weather.precipitation_probability_pct if weather.precipitation_probability_pct is not None else '未知'}%、温度 {weather.low_c if weather.low_c is not None else '未知'}–{weather.high_c if weather.high_c is not None else '未知'}℃、风速 {weather.wind_speed_kph if weather.wind_speed_kph is not None else '未知'} km/h。数据来源：{weather.source_label}。",
                        "可保留原安排，准备应对天气变化的物品，并在出发前复核。"
                        if level == "low"
                        else suggestions.get(condition, "调整活动并核对最新天气。"),
                        day,
                        sources=weather.source_ids,
                        **_weather_trace(day, condition, level, now),
                    )
                )
        return _result(
            "weather",
            "天气",
            findings,
            missing,
            known,
            {"days": len(request.days), "forecast_days_assessed": known},
            context,
            checks,
            estimated=estimated,
        )

    def _budget(self, request):
        missing, findings = [], []
        priced = [c for c in request.costs if c.amount_cny is not None]
        lower = sum((Decimal(str(c.amount_cny)) for c in priced), Decimal(0))
        upper = sum(
            (
                Decimal(str(c.upper_cny if c.upper_cny is not None else c.amount_cny))
                for c in priced
            ),
            Decimal(0),
        )
        cap = (
            Decimal(str(request.budget_cap_cny))
            if request.budget_cap_cny is not None
            else None
        )
        if cap is None:
            missing.append("未填写整趟旅行、全部同行人的预算上限")
        if not request.costs_complete:
            missing.append(
                "费用尚未覆盖整趟旅行，请补齐交通、住宿、餐饮、门票等实际需要的费用"
            )
        if not request.costs:
            missing.append("没有费用明细；免费项目也需要明确填为 0 元")
        for cost in request.costs:
            if cost.amount_cny is None:
                missing.append(f"{cost.name}：金额未知")
        ratio = upper / cap if cap else None
        context = [
            _evidence(
                "budget_cap_cny", "整趟全部同行人预算上限", request.budget_cap_cny, "元"
            ),
            _evidence("costs_complete", "费用已覆盖整趟旅行", request.costs_complete),
        ]
        for c in request.costs:
            context.extend(
                [
                    _evidence(
                        f"costs.{c.item_id}.amount_cny",
                        f"{c.name} 金额下界",
                        c.amount_cny,
                        "元",
                        source="录入或导入的"
                        + {
                            "estimate": "估算",
                            "quote": "报价",
                            "paid": "已付",
                            "unknown": "未知金额",
                        }.get(c.basis, "未知金额")
                        + "，未经本次评估外部核验",
                        sources=c.source_ids,
                    ),
                    _evidence(
                        f"costs.{c.item_id}.upper_cny",
                        f"{c.name} 金额上界（空值时使用该项金额）",
                        c.upper_cny,
                        "元",
                        source="录入或导入的"
                        + {
                            "estimate": "估算",
                            "quote": "报价",
                            "paid": "已付",
                            "unknown": "未知金额",
                        }.get(c.basis, "未知金额")
                        + "，未经本次评估外部核验",
                        sources=c.source_ids,
                    ),
                ]
            )
        checks = [
            _calc(
                "已知费用下界合计 = " + " + ".join(str(c.amount_cny) for c in priced)
                if priced
                else "没有已知费用，无法计算下界合计",
                float(lower) if priced else None,
                "元",
            ),
            _calc(
                "已知费用上界合计 = "
                + " + ".join(
                    str(c.upper_cny if c.upper_cny is not None else c.amount_cny)
                    for c in priced
                )
                if priced
                else "没有已知费用，无法计算上界合计",
                float(upper) if priced else None,
                "元",
            ),
            _calc(
                f"上界占预算 = {upper} ÷ {cap} × 100"
                if cap and priced
                else "预算或费用缺失，不能计算占比",
                float(ratio * 100) if cap and priced else None,
                "%",
            ),
            _calc(
                f"预算余量 = {cap} − {upper}"
                if cap and priced
                else "预算或费用缺失，不能计算余量",
                float(cap - upper) if cap and priced else None,
                "元",
            ),
        ]
        if cap and priced and ratio >= Decimal("0.9"):
            level = "high" if upper > cap else "medium"
            reason = f"已录入费用合计 ¥{lower:.2f}–¥{upper:.2f}，预算上限 ¥{cap:.2f}。"
            if lower > cap:
                title = "已录入费用已超过预算上限"
            elif upper > cap:
                title = "费用区间上界超过预算"
            else:
                title = "预算余量不超过 10%"
            if missing:
                reason += " 尚有费用缺项，最终支出可能更高。"
            findings.append(
                _finding(
                    "budget.cap",
                    level,
                    title,
                    reason,
                    "优先调整较大支出，并补齐缺失费用；保留应对价格变化的预算余量。",
                    entities=[c.item_id for c in priced],
                    sources=[s for c in priced for s in c.source_ids],
                    data=context,
                    calculation=checks,
                    threshold="按费用区间上界比较：>100% 为高，≥90% 且 ≤100% 为中；<90% 且资料完整才为低。",
                    meaning=(
                        "即使按费用下界，已录入支出也超预算。"
                        if lower > cap
                        else "费用上界超预算，存在超支可能；不表示已实际花费该金额。"
                        if upper > cap
                        else "费用已接近预算，剩余空间不足以吸收较大价格变化。"
                    )
                    + (" 尚有缺项，当前合计不能作为最终总价。" if missing else ""),
                )
            )
        return _result(
            "budget",
            "预算",
            findings,
            missing,
            len(priced),
            {
                "recorded_min_cny": float(lower.quantize(Decimal("0.01")))
                if priced
                else None,
                "recorded_max_cny": float(upper.quantize(Decimal("0.01")))
                if priced
                else None,
                "budget_cap_cny": request.budget_cap_cny,
                "remaining_from_upper_cny": float(cap - upper)
                if cap is not None and priced
                else None,
                "estimated_items": sum(c.basis == "estimate" for c in priced),
                "quoted_items": sum(c.basis == "quote" for c in priced),
                "paid_items": sum(c.basis == "paid" for c in priced),
            },
            context,
            checks,
        )

    def _transport(self, request):
        findings, missing, known, estimated = [], [], 0, []
        context, checks = [], []
        for day in request.days:
            label = f"{day.date} {day.destination}".strip()
            coverage = day.transport_coverage
            complete = (
                day.transport_complete
                if coverage is None
                else coverage in {"verified", "none_required"}
            )
            context.append(
                _evidence(
                    f"days.{day.day_id}.transport_coverage",
                    f"{label} 交通资料状态",
                    coverage or day.transport_complete,
                )
            )
            if coverage == "none_required" and not day.transports:
                known += 1  # explicit no-transport day
            elif coverage == "unknown":
                missing.append(f"{label}：交通资料未说明是否完整")
            elif coverage == "missing":
                missing.append(f"{label}：存在未查到的路线")
            elif coverage == "estimated":
                estimated.append(f"{label}：路线为估算，尚未核实")
            elif not complete:
                missing.append(f"{label}：交通衔接尚未完整核对")
            elif not day.transports and coverage is None:
                known += 1  # legacy explicit no-transport day
            for leg in day.transports:
                data = [
                    _evidence(
                        f"transports.{leg.item_id}.duration_minutes",
                        f"{leg.name} 所需时长",
                        leg.duration_minutes,
                        "分钟",
                        sources=leg.source_ids,
                    ),
                    _evidence(
                        f"transports.{leg.item_id}.available_minutes",
                        "可用时间窗口",
                        leg.available_minutes,
                        "分钟",
                    ),
                    _evidence(
                        f"transports.{leg.item_id}.route_status",
                        "路线状态",
                        leg.route_status,
                        sources=leg.source_ids,
                    ),
                ]
                context.extend(data)
                calculation = [
                    _calc(
                        f"时间余量 = {leg.available_minutes} − {leg.duration_minutes}",
                        leg.available_minutes - leg.duration_minutes
                        if leg.available_minutes is not None
                        and leg.duration_minutes is not None
                        else None,
                        "分钟",
                    )
                ]
                checks.extend(calculation)
                if leg.route_status != "ready":
                    missing.append(
                        f"{label} {leg.name}：路线{'仅为估算' if leg.route_status == 'estimated' else '尚未查到'}"
                    )
                if leg.duration_minutes is None:
                    missing.append(f"{label} {leg.name}：交通时长未知")
                else:
                    known += 1
                if leg.available_minutes is None:
                    missing.append(f"{label} {leg.name}：未提供可用时间窗口")
                if (
                    leg.duration_minutes is not None
                    and leg.available_minutes is not None
                    and leg.duration_minutes > leg.available_minutes
                ):
                    findings.append(
                        _finding(
                            "transport.window",
                            "high",
                            f"{label}：{leg.name}时间放不下",
                            f"需要 {leg.duration_minutes} 分钟，安排仅留 {leg.available_minutes} 分钟。",
                            "延后下一项活动、提前出发，或选择更短的路线。",
                            day,
                            [leg.item_id],
                            leg.source_ids,
                            data=data,
                            calculation=calculation,
                            threshold="时间余量 <0 分钟为高风险；余量 ≥0 且路线与时长完整才可排除这项冲突。",
                            meaning=f"现有安排至少缺 {leg.duration_minutes - leg.available_minutes} 分钟，可能赶不上下一项。"
                            + (
                                " 路线尚未核实，此缺口按当前估算计算。"
                                if leg.route_status != "ready"
                                else ""
                            ),
                        )
                    )
            for connection_index, connection in enumerate(day.connections):
                known += 1
                gap, required = (
                    connection.available_minutes,
                    connection.required_minutes,
                )
                data = [
                    _evidence(
                        f"days.{day.day_id}.connections.{connection_index}.available_minutes",
                        f"{connection.name} 可用间隔",
                        gap,
                        "分钟",
                    ),
                    _evidence(
                        f"days.{day.day_id}.connections.{connection_index}.required_minutes",
                        "所需最小间隔",
                        required,
                        "分钟",
                        source="录入或导入的规划要求；并非承运方保证",
                    ),
                ]
                context.extend(data)
                calculation = [
                    _calc(
                        f"相对最小间隔的余量 = {gap} − {required}",
                        gap - required,
                        "分钟",
                    ),
                    _calc(f"提醒阈值 = {required} × 1.25", required * 1.25, "分钟"),
                ]
                checks.extend(calculation)
                if gap < required * 1.25:
                    findings.append(
                        _finding(
                            "transport.connection",
                            "high" if gap < required else "medium",
                            f"{label}：{connection.name}衔接偏紧",
                            f"可用间隔 {gap} 分钟，当前规划要求至少 {required} 分钟。"
                            + ("时间顺序已发生重叠。" if gap < 0 else ""),
                            "增加换乘或活动衔接时间，并核对承运方要求、进站和候车耗时。",
                            day,
                            connection.entity_ids,
                            data=data,
                            calculation=calculation,
                            threshold=f"间隔 <{required} 分钟为高；≥{required} 且 <{required * 1.25} 分钟为中；达到 125% 才不触发缓冲提醒。",
                            meaning=f"距离规划最小间隔还差 {required - gap} 分钟，存在衔接失败的可能。"
                            if gap < required
                            else f"虽达到规划最小间隔，但距离额外 25% 缓冲还差 {required * 1.25 - gap} 分钟，延误余量较小。",
                        )
                    )
        if not checks:
            checks.append(
                _calc(
                    "逐日检查交通是否完整；明确无需交通的日期可通过，未确认的日期待核实",
                    "已核对" if not missing else "待核实",
                )
            )
        return _result(
            "transport",
            "交通",
            findings,
            missing,
            known,
            {
                "legs": sum(len(d.transports) for d in request.days),
                "connections": sum(len(d.connections) for d in request.days),
                "estimated_days": sum(
                    1 for d in request.days if d.transport_coverage == "estimated"
                ),
            },
            context,
            checks,
            estimated=estimated,
        )

    def _fatigue(self, request):
        findings, missing, known, estimated = [], [], 0, []
        context, checks = [], []
        limits = request.limits
        for day in request.days:
            label = f"{day.date} {day.destination}".strip()
            for field, title, limit, unit, divisor in (
                ("walking_km", "步行距离", limits.max_daily_walking_km, "km", 1),
                (
                    "active_minutes",
                    "活动加交通时长",
                    limits.max_daily_active_hours,
                    "小时",
                    60,
                ),
            ):
                raw = getattr(day, field)
                is_estimated = bool(getattr(day, f"{field}_estimated", False))
                data = [
                    _evidence(
                        f"days.{day.day_id}.{field}",
                        f"{label} {title}",
                        raw,
                        "分钟" if divisor == 60 else unit,
                        source=(
                            "程序估算，不是原始行程实测值"
                            if is_estimated
                            else "导入的行程数据，未经本次评估外部核验"
                        ),
                    ),
                    _evidence(
                        f"limits.{'max_daily_walking_km' if field == 'walking_km' else 'max_daily_active_hours'}",
                        "你设置的每日上限",
                        limit,
                        unit,
                        source="旅行者偏好；并非医学适宜性判断",
                    ),
                ]
                context.extend(data)
                if raw is None:
                    missing.append(f"{label}：{title}未知")
                    continue
                known += 1
                if is_estimated:
                    estimated.append(f"{label}：{title}为程序估算")
                value = raw / divisor
                calculation = [
                    _calc(f"当天量 = {raw} ÷ {divisor}", value, unit),
                    _calc(f"超限量 = {value} − {limit}", value - limit, unit),
                    _calc(
                        f"占偏好上限 = {value} ÷ {limit} × 100",
                        value / limit * 100,
                        "%",
                    ),
                ]
                checks.extend(calculation)
                if value > limit:
                    findings.append(
                        _finding(
                            f"fatigue.{field}",
                            "high" if value > limit * 1.25 else "medium",
                            f"{label}：{title}超过偏好上限",
                            f"当天 {value} {unit}，你设置的上限为 {limit} {unit}。",
                            "删减一个活动、缩短步行，或把部分活动移到其他日期。",
                            day,
                            data=data,
                            calculation=calculation,
                            threshold=f">{limit} {unit} 为中；>{limit * 1.25} {unit}（上限的 125%）为高；等于阈值不向上升档。",
                            meaning=f"当天{title}比你设置的上限多 {value - limit} {unit}，可能难以按偏好完成；阈值应随同行人实际承受能力调整。",
                        )
                    )
            rest_data = [
                _evidence(
                    f"days.{day.day_id}.rest_minutes",
                    f"{label} 明确休息时长",
                    day.rest_minutes,
                    "分钟",
                    source=(
                        "程序估算，不是原始行程实测值"
                        if day.rest_minutes_estimated
                        else "导入的行程数据，未经本次评估外部核验"
                    ),
                ),
                _evidence(
                    "limits.min_daily_rest_minutes",
                    "你设置的最低休息时长",
                    limits.min_daily_rest_minutes,
                    "分钟",
                    source="旅行者偏好",
                ),
            ]
            context.extend(rest_data)
            rest_calculation = [
                _calc(
                    f"休息余量 = {day.rest_minutes} − {limits.min_daily_rest_minutes}",
                    day.rest_minutes - limits.min_daily_rest_minutes
                    if day.rest_minutes is not None
                    else None,
                    "分钟",
                )
            ]
            checks.extend(rest_calculation)
            if day.rest_minutes is None:
                if limits.min_daily_rest_minutes > 0:
                    missing.append(f"{label}：明确安排的休息时长未知")
            else:
                known += 1
                if day.rest_minutes_estimated:
                    estimated.append(f"{label}：休息时长为程序估算")
                if day.rest_minutes < limits.min_daily_rest_minutes:
                    findings.append(
                        _finding(
                            "fatigue.rest",
                            "medium",
                            f"{label}：休息安排不足",
                            f"明确休息 {day.rest_minutes} 分钟，期望至少 {limits.min_daily_rest_minutes} 分钟。",
                            "加入专门的休息时间，并相应减少活动；用餐与空白时间不自动算作休息。",
                            day,
                            data=rest_data,
                            calculation=rest_calculation,
                            threshold="休息余量 <0 分钟为中风险；等于最低休息时长不触发提醒。",
                            meaning=f"比你的休息偏好少 {limits.min_daily_rest_minutes - day.rest_minutes} 分钟，恢复时间可能不足；未把用餐和空白时段自动计入休息。",
                        )
                    )
        return _result(
            "fatigue",
            "体力",
            findings,
            missing,
            known,
            {
                "max_walking_km": limits.max_daily_walking_km,
                "max_active_hours": limits.max_daily_active_hours,
                "min_rest_minutes": limits.min_daily_rest_minutes,
            },
            context,
            checks,
            estimated=estimated,
        )

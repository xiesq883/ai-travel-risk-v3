# Four-dimension travel risk engine v2

Open `/?view=risk` for **风险评估**. The initial scope is exactly weather, budget, transport and fatigue. Assessment is deterministic and read-only: it makes no model or provider calls and needs no model key. The demo is explicitly fictional.

## Contracts

`entities/travel_risk.py` defines validated inputs and findings. `services/travel_risk_engine.py` implements `travel-risk.v2`; `services/travel_risk_adapter.py` reads the current immutable trip bundle. Numeric weather rules are shared with `weather_impact_engine.py`. `WeatherMeasures` carries manual weather values without inventing place coordinates or external facts; the existing planning gate still requires real fact lineage.

Each of the four dimensions returns a level (`high`, `medium`, `low`, `unknown`), coverage (`complete`, `partial`, `missing`), findings, metrics and missing inputs. Findings include the rule, reason, suggestion, day, original entity references and available source references. There is no aggregate numerical score or claimed probability.

High/medium findings remain visible when other data are missing. Incomplete data otherwise produces `unknown`; it cannot produce a low overall result. No missing field is silently converted to zero.

## Explanation chains (stage 3)

Every finding and dimension now contains a required `explanation` with four steps:

1. `data`: original values, units, logical input field references, source labels, original source IDs and observation times where available. Paths use stable day/cost/transport IDs, rather than claiming to be JSON array pointers. Manual values, imported estimates and demo values are explicitly labelled; the assessment never claims to have independently verified them.
2. `calculation`: substituted expressions and machine-readable results. Budget sums use Decimal before comparing the unrounded total against the cap. Transport shows time margin and the 125% buffer threshold; fatigue shows minutes-to-hours conversion, excess and percentage of the custom limit; weather shows forecast age and the exact triggering comparison, including each side of the rain OR condition.
3. `rule` + `risk_level`: the actual threshold and its resulting level. Shared weather constants feed both execution and explanations. This version adds traceability, without adding risk dimensions or changing the initial thresholds.
4. `explanation`: deterministic meaning and likely impact, alongside the existing actionable `suggestion`. No model is asked to invent reasoning after the decision.

Dimension chains explain aggregation (highest known level), completeness and blocked checks. An expired forecast reports its age and why it was rejected; unknown inputs remain null. Low results also retain checked data, arithmetic and rules. Individual findings are shown as four numbered cards, with expandable provenance; the full dimension trace is expandable to keep the report readable. Narrow screens stack the cards. JSON export preserves input, engine version, timestamp, bundle ID and every chain.

`travel-risk.v2` is an API output schema change: explanation fields are required. Reassess old exports to obtain chains. No stored trip data or database migration is changed.

## Initial rules

These are explicit planning heuristics. Threshold changes should update the engine version and boundary tests.

| Dimension | Initial rules |
| --- | --- |
| Weather | Only corresponding-date forecasts collected within 24 hours; reject observations more than 5 minutes in the future. At most seven calendar dates starting with the observation date, additionally bounded by any explicit forecast end. Past dates, seasonal baselines, unknown exposure and missing weather fields remain unverified. Zero outdoor time skips numeric outdoor-weather checks but still needs usable forecast context. |
| Budget | All CNY amounts use whole-trip, whole-party scope. Sum ranges with Decimal; upper total > cap is high, upper total >=90% of cap is medium. Incomplete costs below those thresholds are unknown. Label estimates, quotes and paid items separately. Explicit free items use 0; no items or missing prices remain unknown. |
| Transport | Duration exceeding the available window is high. Connection gap below the supplied minimum is high, below 125% of that minimum is medium. Negative gaps flag overlaps. Unknown routes, durations, windows or incomplete route coverage stay unverified. No-transport days require explicit confirmation. |
| Fatigue | Compare walking and activity-plus-transport time with traveler preferences: above the limit is medium, above 125% is high. Too little deliberate rest is medium. Defaults are 8 km, 8 hours and 45 minutes per day; all three are editable. Unknown rest differs from explicit zero; meals and unscheduled gaps do not automatically count as rest. |

Shared outdoor weather thresholds: rain >=20 mm or probability >=90% is high; >=5 mm or >=65% is medium. High/medium heat thresholds are >=40/35°C, cold <=−10/0°C, wind >=45/30 km/h. Thunderstorm and snow codes trigger high outdoor impact. The shared engine retains lower-severity triggers. This initial screen does not add hourly precision or official alert ingestion.

## Existing trips

The endpoint applies the existing trip-access check before reading the current bundle and identifies the exact bundle ID in the report. It never rewrites the stored itinerary, facts or projections.

- Import the itinerary cost summary once; never sum it again with individual components. Preserve missing costs and coverage. Imported aggregate prices remain estimates.
- Reuse weather observations and active, verified, unexpired facts. Missing, expired or withdrawn evidence cannot become verified data.
- Reuse explicit route segments, durations and scheduled windows. Compare timestamps using offsets; missing/naive timestamps remain unknown. Initial transfer-buffer preferences are 120 minutes for flights, 60 for rail and 30 otherwise; these are not carrier minimum-connection guarantees.
- Flag schedule overlaps with original entity references. Count overnight transport on its departure day, without repeating it at arrival.
- Sum recorded visit and transport durations. Unclassified custom blocks leave the aggregate unknown. Outdoor exposure, on-site walking and deliberate rest remain unknown because the original bundle lacks complete measurements; the traveler can supply them.

Editing inputs clears the previous report. Changing date/destination also clears corresponding weather and transport. Demo input keeps its demo label after editing. Manual input and reports are held in page memory; the UI can export both as JSON. Reimport to assess a newer trip version.

The page's **导入并评估** action retains the current daily-intensity preferences and fills only missing walking, activity-plus-transport, and rest values from those preferences (hours are converted to minutes). Missing outdoor exposure defaults to 3 hours (180 minutes), also used for new manual days. Missing transport windows default to the corresponding required travel duration; entering a duration for a manual route also fills an empty window. Existing values, including explicit zero, are preserved. Every imported day defaults to transport coverage checked; individual route status remains unchanged. These editable planning defaults affect only the page's risk input, never the stored itinerary. The page reassesses the filled input and retains its JourneyPilot origin and bundle ID, including after edits and reassessment. New manual input and demo input reset that origin.

## API

| Route | Result |
| --- | --- |
| `GET /api/risk/example` | Dynamically dated, explicitly fictional five-day Yunnan input |
| `POST /api/risk/assess?input_origin=...&bundle_id=...` | Assessment of normalized input; optional provenance query values are carried to the report |
| `POST /api/risk/optimize?input_origin=...&bundle_id=...` | Preserve the original input, create a reviewable optimization draft, and reassess it with the same engine; optional provenance query values are carried to both reports |
| `GET /api/risk/trips/{run_id}?session_id=...` | Normalized input and assessment of the current authorized bundle |

Invalid data returns HTTP 422. A trip without a completed bundle returns 404; access errors use existing trip rules. No database migration is added.

## Validation and limits

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_travel_risk_engine.py tests/test_travel_risk_adapter.py tests/test_temporal_tool_policy.py --basetemp=../work/pytest-risk-manual -q
cd frontend
npm.cmd run check
```

Tests cover missing/zero distinctions, costs/ranges, forecast age/horizon and midnight boundaries, weather thresholds, custom fatigue limits, negative/tight connections, validation, no mutation, original weather-gate lineage, adapter double-counting, evidence expiry and trip-access ordering. Browser QA checks blank inputs, demo assessment, clearing stale results on edit, and JSON export.

The first version does not predict traffic disruption, fetch live prices, make clinical fitness judgments, or automatically change an itinerary. Full generated-trip integration still needs a completed JourneyPilot trip; the demo and manual path work independently of the model key.

## Optimization loop (stage 4)

The risk page now supports `原方案 → 找出风险 → 修改方案 → 再评估`. `TravelRiskOptimizer` first creates the normal assessment, copies the validated input, applies only explicit schedule changes to a draft, and runs the same engine again. The original input is returned unchanged alongside the draft, before report and after report.

The draft can reduce outdoor minutes, walking distance and activity-plus-transport minutes to the traveler's stated limits, add the stated minimum rest, and add a 25% buffer to a known transport window or connection. These changes are proposals for review; applying them in the page only changes the in-memory risk input and never rewrites a stored itinerary.

Budget changes, route verification, and missing measurements remain `needs_confirmation` proposals. The optimizer does not invent a discount, a new route, or a rest measurement. After the traveler confirms or edits those fields, the normal **评估这个方案** action starts the next loop iteration.

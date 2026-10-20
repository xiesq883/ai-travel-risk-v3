# Trip Dataset v1

`trip-dataset.v1` 是「生成旅途」输出给下游（风险评估、费用核对、人工复核）的
逐日结构化数据集。它是不可变 Delivery Bundle 的**只读投影**：

- 不调用模型，不发起网络请求，不改变已保存的行程。
- 所有金额、时长、距离只来自行程实体、事实来源，或带 `assumptions` 的程序估算。
- 缺失值保持 `null`，不会用 0 或模型猜测填补。
- 独立风险评估模块的业务逻辑不在此阶段修改。

## 入口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/trip-runs/{run_id}/dataset?version=v1` | 返回 JSON 数据集 |
| GET | `/api/trip-runs/{run_id}/dataset/export?version=v1` | 下载同名 JSON 文件 |

支持的版本：`v1`、`1`、`latest`、`trip-dataset.v1`。其他版本返回 400
`unsupported_dataset_version`，不会静默回落到别的结构。

响应头：

- `X-JourneyPilot-Dataset-Schema`
- `X-JourneyPilot-Dataset-Id`
- 导出时另带 Bundle ID 与三个 revision，便于核对数据来自哪一版。

## 顶层结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | string | 固定 `trip-dataset.v1` |
| `dataset_id` | string | 由 schema + bundle + revisions 计算的稳定 ID |
| `generated_at` | datetime | 生成时间（UTC） |
| `compatibility` | object | 旧 Bundle/Workspace/Fact/Weather 契约版本 |
| `trip` | object | 行程基本信息与同行人 |
| `days` | array | 每个自然日一条，按日期升序 |
| `lodgings` | array | 整趟住宿条目（可能跨天） |
| `costs` | object | 费用明细与后端汇总 |
| `sources` | array | 可追溯来源 |
| `data_sources` | array | 外部能力配置状态（不代表调用成功） |
| `coverage` | object | 缺失/估算字段与警告 |
| `assumptions` | array | 全局估算约定 |

## trip（行程基本信息）

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `run_id` / `bundle_id` / `itinerary_id` | string | 否 | 运行、Bundle 与行程标识 |
| `workspace_revision` / `fact_data_revision` / `weather_data_revision` | int | 否 | 数据版本 |
| `title` | string | 否 | 行程标题 |
| `origin` | object | 是 | 出发地（name/place_id/坐标） |
| `destination_ids` | string[] | 否（可为空数组） | 目的地稳定 ID |
| `destination_names` | string[] | 否（可为空数组） | 目的地名称 |
| `start_date` / `end_date` | date | 否 | 以实际物化日为准 |
| `timezone` | string | 是 | 仅当所有天气日时区一致时给出 |
| `party` | object | 否 | `adults`、`children`、`elderly_companions`、`accessibility_required` |
| `preferences` | object | 否 | `style`、`interests`、`requirements` |

## days（每日路线）

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `day_id` / `day_index` / `date` | string/int/date | 否 | `day_index` 从 1 连续 |
| `destination_id` / `destination_name` | string | 否 | 目的地 |
| `start_place` / `end_place` | object | 是 | 当天首尾地点 |
| `timeline` | array | 否 | 按顺序记录 activity/meal/route/lodging 引用 |
| `activities` | array | 否 | 景点、体验、自定义安排 |
| `meals` | array | 否 | 早/午/晚固定三槽 + 实际存在的加餐 |
| `routes` | array | 否 | 交通段与未查询的步行段 |
| `lodging_stay_id` | string | 是 | 当晚住宿（住宿日期覆盖该日时） |
| `weather` | object | 是 | 当天天气快照 |
| `metrics` | object | 否 | 活动/交通/步行/户外/休息 |
| `warnings` | string[] | 否 | 本日降级说明 |
| `assumptions` | array | 否 | 本日估算假设 |

### Activity

`activity_id`、`entity_type`（visit_stop/custom_block）、`name`、`place_id`、`address`、
坐标、`visit_type`、`start_at`/`end_at`、`duration_minutes`、`ticket_cny`、
`price_type`、`price_basis`、`outdoor`、`source_ids`、`retrieved_at`、`confidence`、
`assumptions`。

### Meal

`meal_id`、`meal_type`（breakfast/lunch/dinner/snack/other）、`status`
（planned/not_planned/unknown）、餐厅名称/地点/地址、起止时间、`party_size`、
`per_person_cny`、`total_cny`、`price_type`、`price_basis`、来源、`retrieved_at`、
置信度、假设。

未安排的餐次仍输出条目，但 `status="not_planned"`、金额为 `null`。

### RouteSegment

起点、终点、`mode`、`route_status`（ready/estimated/missing）、计划起止时间、
`duration_minutes`、`distance_m`、`distance_source`、`distance_method`、
`fare_cny`、`price_type`、`price_basis`、`transfer_count`、`steps`、来源、置信度、假设。

`steps` 保留上游分段（线路名、车次、起止站、分段耗时与票价）；旧 Bundle 没有
分段时为空数组，此时 `transfer_count` 仍是可用信息。

行程时间线中两个相邻地点之间没有交通实体时，生成一条 `mode="walk"` 的补全段：

- 有坐标：直线距离 × 1.3 道路绕行系数，按 4.8 km/h 折算耗时；
- 无坐标：距离与耗时都为 `null`，`route_status="missing"`。

### metrics（体力数据）

| 字段 | 说明 |
| --- | --- |
| `activity_minutes` | 活动时长合计；任一活动缺时长则为 `null` |
| `transport_minutes` | 交通段耗时合计；任一交通段缺耗时则为 `null` |
| `walking_m` / `walking_km` | 步行段距离合计；任一步行段缺距离则为 `null` |
| `outdoor_minutes` | 户外暴露估算，见下 |
| `rest_minutes` | 已排程项目之间正间隔之和 |
| `transfers` | 换乘次数 |
| `estimated_fields` | 哪些指标是程序估算 |

步行统计只覆盖行程时间线中的步行段；往返住宿、临时绕行等未排程步行不计入，
消费方不应把它当成全天步数。

户外暴露估算规则（`program_estimate`）：

- `visit_type="nature"` 计全部时长；
- `attraction` / `shopping` 计一半；
- 加上步行段耗时。

这是规划启发式，不是天气暴露测量；消费方必须读取 `estimated_fields`。

### weather（天气）

`data_kind`、`forecast_end_date`、`condition_label`、`high_c`、`low_c`、
`precipitation_mm`、`precipitation_probability_pct`、`wind_speed_kph`、`condition_code`、
`retrieved_at`、`source_ids`、`confidence`。

`retrieved_at` 是预报采集时间，风险评估用它判断 24 小时新鲜度；
`forecast_end_date` 是上游声明的可用截止日，缺失时读取方不得假设无限有效期。

## lodgings（住宿）

| 字段 | 说明 |
| --- | --- |
| `stay_id` / `name` / `place_id` / `address` | 身份 |
| `check_in_date` / `check_out_date` / `nights` | 日期与晚数（不变量：差值等于晚数） |
| `room_count` | 行程未给出时保持 `null` |
| `guest_count` | 同行人数 |
| `nightly_cny` / `total_cny` | 每晚/整段金额 |
| `price_type` | `actual_quote` 仅当 `price_kind="live_quote"` |
| `availability_status` | `confirmed` 仅允许与实际报价同时出现 |
| `includes` | 费用包含范围（当前未提供则为空数组） |
| `source_ids` / `retrieved_at` / `confidence` / `assumptions` | 溯源 |

参考估算的住宿永远不能标记为 `confirmed`。

## costs（费用明细）

每个 `CostItem` 包含：

`cost_id`、`category`（transport/dining/lodging/ticket/other）、`label`、
`entity_type`/`entity_id`、`amount_cny`、`low_cny`、`high_cny`、`currency="CNY"`、
`unit_scope`、`quantity`、`unit_label`、`price_type`、`price_basis`、来源、检索时间、
置信度、假设。

汇总字段：`transport`、`dining`、`lodging`、`ticket`、`other`、`total`，均为
`AmountRange`（low/high/point），另有 `priced_item_count`、`unknown_item_count`、
`complete`、`computed_by="backend"`。

规则：

1. 汇总只由后端 `Decimal` 计算；调用方不得再次相加。
2. 未知金额条目照样保留，计入 `unknown_item_count`，不进入合计。
3. `complete=true` 仅当存在费用条目且没有任何未知条目。
4. `price_type` 与金额必须同时存在或同时为空。
5. 行程实体内由模型给出的 `llm_estimated_total_cny` **不进入**任何金额字段或合计；
   它既不是报价也不是程序估算。若前端要展示，必须单独标为「模型估算」。

### price_type 与 price_basis

| price_type | 含义 | 典型 basis |
| --- | --- | --- |
| `actual_quote` | 有可核对的实际价格 | `live_quote`、`published_fare`、`published_price` |
| `estimated` | 参考价/行程估算 | `reference_estimate`、`reference_per_person`、`itinerary_estimate` |
| `unknown` | 无金额 | `null` |

`actual_quote` + `published_fare` 表示公布票价，不等于可预订库存或最终成交价。

## sources（来源）

`citation_id`、`source_record_id`、`source_type`
（official_api/third_party_api/public_web/program_estimate/unknown）、`provider`、
`title`、`url`、`retrieved_at`、`published_at`、`excerpt`、`confidence`、
`fact_assertion_ids`。

`confidence` 由事实状态与来源生命周期决定，不由模型声明：

- 事实 `verified`、未过期、来源 `active` → `verified`；
- 有来源但事实过期/未验证 → `unverified`；
- 无来源 → `unknown`；
- 程序估算 → 值级 `estimated`，并在 `assumptions` 写明方法。

## data_sources（能力状态）

每项：`source_id`、`name`、`kind`、`configured`、`capabilities`、`required_env`、`note`。

`configured=true` 只表示配置存在，不表示本次调用成功。缺 Key 的能力明确为
`configured=false`，不影响其他字段生成。

## 兼容性

- 当前只发布 v1；未知版本请求直接返回 400。
- 结构使用 `extra="forbid"`：多出字段会被拒绝，避免上游悄悄改变语义。
- 新增字段必须升版本；读取方按 `schema_version` 分支。
- `compatibility` 记录来源 Bundle/Workspace/Fact/Weather 契约版本，便于跨版本审计。
- 原 PDF 导出与 Bundle 读取保持不变；数据集是新增导出，不替换旧格式。

## 导入风险评估

建议映射（风险评估模块本身不需要修改）：

| 数据集字段 | RiskAssessmentInput |
| --- | --- |
| `trip.title` | `title` |
| `days[].date` | `RiskDay.date` |
| `days[].metrics.active_minutes` | `active_minutes`（活动 + 交通；缺失为 null） |
| `days[].metrics.walking_km` | `walking_km` |
| `days[].metrics.rest_minutes` | `rest_minutes` |
| `days[].routes[]` | `RiskTransport`（duration/available 由起止时间计算） |
| `days[].weather` | `RiskWeather` |
| `costs.items[]` | `RiskCost`（actual/estimated 保留原 price_type 语义） |
| `costs.total.point_cny` | 整趟预估总额 |

风险页面当前仍以自己的导入器读取 Bundle；本阶段不改页面。后续接入时按
`schema_version="trip-dataset.v1"` 走独立适配层。

## 样例

- `docs/examples/trip-dataset.v1.sample.json`（合成数据，非真实报价）
- `docs/examples/trip-dataset.v1.schema.json`（JSON Schema）

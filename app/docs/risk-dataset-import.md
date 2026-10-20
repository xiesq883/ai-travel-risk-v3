# 风险评估：结构化行程自动导入

本阶段把 `trip-dataset.v1` 接入独立的风险评估模块。用户只需要填写
**整趟旅行、全部同行人的总预算上限**，其余路线、餐次、住宿、活动时长、
费用和天气由系统读取。

## 1. 入口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/risk/trips/{run_id}/dataset/import` | 从当前 Bundle 生成并预览数据集 |
| POST | `/api/risk/trips/{run_id}/dataset/assess` | 带预算评估已生成行程 |
| POST | `/api/risk/dataset/import` | 预览离线导入的 JSON 数据集 |
| POST | `/api/risk/dataset/assess` | 评估离线导入的 JSON 数据集 |
| GET | `/api/risk/dataset/example` | 返回合成演示数据集（页面明确标注“演示数据”） |

原有 `/api/risk/assess`、`/api/risk/optimize`、`/api/risk/trips/{run_id}`
保持不变，用于旧格式和手动录入。

## 2. 导入数据映射

| Trip Dataset | RiskAssessmentInput | 规则 |
| --- | --- | --- |
| `trip.title` | `title` | 原样保留 |
| `trip.bundle_id` | 评估结果 `bundle_id` | 不丢失来源标识 |
| 用户输入 | `budget_cap_cny` | 唯一金额输入 |
| `days[].day_id/date/destination_name` | `RiskDay` | 日期与目的地 |
| `days[].metrics.outdoor_minutes` | `outdoor_minutes` | 保留 `outdoor_minutes_estimated` |
| `days[].metrics.activity_minutes + transport_minutes` | `active_minutes` | 任一缺失则为 `null`，不估算相加 |
| `days[].metrics.walking_km` | `walking_km` | 保留 `walking_km_estimated` |
| `days[].metrics.rest_minutes` | `rest_minutes` | 保留 `rest_minutes_estimated` |
| `days[].routes[]` | `RiskTransport` | 仅交通实体；步行补全段不冒充交通 |
| `days[].routes[].steps[]` | `RiskConnection` | 分段间间隔，按 30/60/120 分钟要求 |
| `days[].weather` | `RiskWeather` | `retrieved_at` → `observed_at`；`forecast_end_date` 保留 |
| `costs.items[]` | `RiskCost` | 每项只映射一次；`actual_quote→quote`、`estimated→estimate`、`unknown→unknown` |
| `costs.complete` | `costs_complete` | 未知费用不被当成 0 |
| `days[].routes` 状态 | `transport_coverage` | `verified / estimated / missing / none_required / unknown` |

## 3. 默认值与可信度

禁止的旧行为已经移除：

- 不再把 `max_daily_walking_km` 填成当天实际步行；
- 不再把 `max_daily_active_hours` 填成当天活动时长；
- 不再把最低休息时长填成实际休息；
- 不再默认勾选“交通已核对”；
- 不再把参考价标成已确认报价。

数据集里没有的值保持 `null`；程序估算值带 `estimated_fields` 标记，
风险评估维度会把这些字段放进 `estimated_data`，并将覆盖度降为 `partial`。

## 4. 四项风险的变化

### 天气

- 读取 `data_kind`、`retrieved_at`、`forecast_end_date` 与逐日数值。
- 继续执行 24 小时新鲜度、未来时间偏差、7 天窗口和预报截止日检查。
- 户外时长为估算时，天气结论标注“部分数据为估算”。

### 预算

- 预计总费用来自 `costs.total`（后端 Decimal 汇总）。
- 用户预算只用于比较，不参与费用合计。
- 未知费用保留为 `unknown` 条目，`costs_complete=false`；
  此时即使预算充足，预算维度也不能直接给出低风险。

### 交通

- `transport_coverage` 区分已核实、估算、缺失、明确无需交通、未说明。
- `transport_complete` 仅作为旧格式兼容字段，不再由前端默认置真。
- 路线时长为估算时，维度标记 `partial` 并列出估算项。

### 体力

- 优先使用导入的实际计划值；估算值保留来源标记。
- 缺失步行、活动时长或休息时保持未知，不用偏好上限补齐。
- 估算值参与阈值比较，但结果明确标注“基于估算”。

## 5. 页面

- 顶部显示导入状态、天数、目的地、Bundle 和数据集 ID。
- 主要输入只有“总预算上限”。
- 逐日明细折叠展示路线、餐饮、住宿、活动、天气和来源。
- 估算字段显示“估算”，缺失字段显示“未知”。
- 评估后只列出影响结论的缺项，不要求逐日重填。
- 演示数据有醒目标记。

旧的逐日编辑页 `RiskAssessmentPage.tsx` 保留用于兼容，不再作为默认入口；
其中危险的默认填充逻辑已移除。

## 6. 测试

- `tests/test_trip_dataset_risk_import.py`：映射、费用不重复、只填预算、估算标记、缺失天气。
- `tests/test_risk_dataset_api.py`：预览、评估、离线 JSON、权限检查。
- `tests/test_travel_risk_engine.py`：原有四项规则回归。
- 前端：类型检查、Vitest、生产构建。

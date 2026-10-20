# 旅游外部数据接入规范

本文件约束新增数据源、缓存、来源记录与降级行为。与 `docs/trip-dataset.v1.md`
配套使用：数据集里的每个非空值都必须能追溯到这里定义的来源类型。

## 1. 已接入能力

| source_id | 类型 | 能力 | 凭证 | 默认状态 |
| --- | --- | --- | --- | --- |
| `open-meteo` | MCP 工具 | 当前天气、逐日预报 | 无 | 启用 |
| `12306-train` | MCP 工具 | 列车时刻、公布票价 | 无 | 启用 |
| `currency-exchange-mcp` | MCP 工具 | 汇率 | 无 | 启用 |
| `duckduckgo-search` | MCP 工具 | 网页搜索 | 无 | 启用 |
| `fetch` | MCP 工具 | 网页抓取 | 无 | 启用 |
| `nominatim` | 内置工具 | 地点身份/地理编码 | 无 | 启用（限速） |
| `route_search` | 内置工具 | 公交/步行/驾车/骑行路线 | 无（国内依赖高德） | 启用 |
| `amap-maps` | MCP 工具 | 国内 POI、路线、公交票价 | `AMAP_MAPS_API_KEY` | 默认禁用 |
| `tavily-search` | MCP 工具 | 搜索/抽取 | `TAVILY_API_KEY` | 默认禁用 |
| `brave-search` | MCP 工具 | 搜索 | `BRAVE_API_KEY` | 默认禁用 |
| `firecrawl` | MCP 工具 | 抓取/抽取 | `FIRECRAWL_API_KEY` | 默认禁用 |
| `duffel-flights` | MCP 工具 | 航班搜索/报价 | `DUFFEL_API_KEY_LIVE` | 默认禁用 |
| 酒店实时报价 | 未接入 | 房态/实时价格 | — | 不可用 |

`data_sources` 字段会把这些状态原样写进数据集。`configured=true` 只代表配置存在，
不代表本次查询成功。

## 2. 配置方式

- 便携版读取 `app/config.portable.yaml`；开发版读取 `app/config.yaml`。
- 密钥通过 `.env` 或环境变量注入，例如：

```text
AMAP_MAPS_API_KEY=...
TAVILY_API_KEY=...
```

- 启用某个 MCP 服务时，把 `mcp.servers.<name>.disabled` 改为 `false` 并重启。
- 不得把密钥写入 `config.yaml`、源码、测试、日志或交付包。

## 3. 来源类型

| source_type | 判定 |
| --- | --- |
| `official_api` | 运营方官方接口（如 12306 公布票价） |
| `third_party_api` | 第三方 API/工具（Open-Meteo、高德、Transitous、Nominatim） |
| `public_web` | 公开网页检索结果 |
| `program_estimate` | 本项目的确定性估算（球面距离、时长折算等） |
| `unknown` | 无来源或来源不可用 |

## 4. 置信度

只看事实与来源，不看模型措辞：

1. `FactAssertion.status == "verified"`；
2. `expires_at` 未过期；
3. 所有 `source_links` 指向 `lifecycle_status == "active"` 的来源；

三条同时满足才是 `verified`。否则 `unverified` / `unknown`。程序估算单独标
`estimated`，不能升级为 `verified`。

## 5. 缓存与时限

| 项目 | 默认值 |
| --- | --- |
| 路线缓存 TTL | 300 秒（`provider_snapshot_cache.route_ttl_seconds`） |
| 地点身份 TTL | 7 天 |
| 路径规划 HTTP 超时 | 20 秒（`routing.timeout_seconds`） |
| 地理编码 HTTP 超时 | 10 秒 |
| 地理编码最小间隔 | 1.1 秒 |
| MCP 初始化超时 | 45 秒（`MCP_INIT_TIMEOUT_SECONDS`） |
| MCP 单次调用超时 | 60 秒（`MCP_CALL_TIMEOUT_SECONDS`） |

缓存不可用（Redis 断开）时直接走真实查询，不把缓存故障当数据结论。

## 6. 失败降级

| 情况 | 处理 |
| --- | --- |
| 未配置 Key | 对应能力 `configured=false`，字段为 `null` / `unknown` |
| 查询超时 | 记录失败，不重试超过预算；字段保持未知 |
| 成功但无结果 | 不重试、不换工具，返回空结果并说明 |
| 酒店无实时报价 | `price_type="estimated"`，`availability_status != "confirmed"` |
| 天气缺报 | `day.weather=null`，在 `coverage.missing_fields` 列出 |
| 路线缺距离 | `distance_m=null`；不得用 0 补齐 |
| 步行数据缺失 | 可用「时长 × 4.8 km/h」估算，但必须标 `program_estimate` 和假设 |

## 7. 价格规则

- `actual_quote` 只给真正的实时报价或官方公布票价，并写清 `price_basis`。
- 网页人均、参考房价、模型估算一律 `estimated`。
- 未知金额保持 `null`，并计入 `unknown_item_count`。
- 所有合计由后端 `Decimal` 完成；前端/模型不得再次相加。
- 没有酒店实时接口时，禁止声称「已确认有房」「可直接预订」。

## 8. 安全

- 数据集只输出结构化字段与公开来源摘录，不输出 Key、请求头、内部提示词。
- 来源 URL 只允许 http/https，且不得内嵌用户名/密码。
- 交付包不得包含 `.env`、`.state`、聊天记录或用户数据库。

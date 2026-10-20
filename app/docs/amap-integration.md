# 高德地图 Web 服务接入

## 当前状态

| 项目 | 状态 |
| --- | --- |
| 高德 POI 搜索 | 已实现（本地服务 + Codex 工具） |
| 地址 → 坐标 | 已实现 |
| 坐标 → 地址 | 已实现 |
| 步行/公交/驾车/骑行路线 | 复用现有 `amap_route_search`，已实现 |
| 生成旅途联动 | 工具已加入 destination/accommodation/transport 白名单；CN 餐饮确定性落地支持本地工具回退 |
| 单元测试 | 已通过（MockTransport，无真实联网） |
| 真实 API 验收 | 已通过（2026-10-18，本机 Web 服务 Key） |
| 酒店实时报价 | 未接入，POI 不代表房价 |

## Key 配置

支持两个变量名，优先 `AMAP_WEB_SERVICE_KEY`：

```text
AMAP_WEB_SERVICE_KEY=...
```

兼容旧名：`AMAP_MAPS_API_KEY`。两者只设置一个，不要同时写不同值。

安全方式：

```powershell
& "runtime\python\python.exe" scripts\configure_amap.py
```

或手动编辑本机 `app/.env`。`.env` 已被 `.gitignore` 排除；不要写入
`.env.example`、源码、前端、日志或测试。

配置后重启服务，再运行：

```powershell
& "runtime\python\python.exe" scripts\verify_amap.py
```

该脚本只打印归一化结果，不打印 Key。

## 后端模块

| 模块 | 职责 |
| --- | --- |
| `services/amap_client.py` | Key 读取、别名、错误类型、共享限流键 |
| `services/amap_place_search.py` | POI 搜索、地理编码、逆地理编码 |
| `services/amap_route_search.py` | 步行/公交/驾车/骑行路线（已有） |
| `services/global_route_search.py` | 中国坐标框内自动选高德，其余走 Transitous |
| `tools/builtin_tools.py` | 暴露 `amap_place_search`、`amap_geocode`、`amap_regeocode` |
| `agents/utils.py` | 将工具加入目的地/住宿/交通研究员白名单 |

## 坐标与单位

- 项目内部：WGS-84。
- 高德请求/响应：GCJ-02。
- 服务边界统一转换；不要把 GCJ-02 坐标直接写入行程。
- 距离：米；耗时：分钟；公交费用：仅在接口返回 `cost` 时写入。

## 归一化结果

POI：

```json
{
  "place_id": "amap:B001",
  "name": "雷峰塔",
  "address": "西湖区南山路",
  "latitude": 30.2311,
  "longitude": 120.1489,
  "city": "杭州市",
  "district": "西湖区",
  "adcode": "330106",
  "provider": "amap",
  "provider_place_type": "110202",
  "provider_country_code": "CN",
  "coordinate_system": "WGS84",
  "confidence_status": "provider_returned",
  "source_url": "https://lbs.amap.com/api/webservice/guide/api/search",
  "retrieved_at": "..."
}
```

路线复用 `global_route_search` 的 `routes[0]`，并新增：

- `fare_type="published_transit_fare"`：高德返回公交票价时；
- `currency="CNY"`：仅在票价存在时；
- 无票价时保持 `null`，不得写成 0。

## 错误处理

| 情况 | 返回 |
| --- | --- |
| 未配置 Key | `error_code=not_configured` |
| 超时 | `error_code=timeout` |
| Key 无效/平台不匹配/权限不足/限流 | `error_code=provider_refused` |
| 服务不可用/无效响应 | `error_code=unavailable` |
| 参数错误 | `error_code=invalid_params` |
| 成功但无结果 | `success=true, places=[], message=no_result` |

工具失败不会抛到模型上下文；模型看到结构化失败后应降级，不得伪造地点。

## 生成旅途联动

1. 目的地研究：中国大陆地点用 `amap_place_search` 获取稳定 POI、地址和 WGS-84 坐标；
   海外继续使用 `global_place_search`。
2. 住宿研究：优先使用高德 POI 确认酒店身份；房价仍需另取报价，POI 不是报价。
3. 交通研究：统一用 `global_route_search`；中国坐标框内由高德返回路线、距离、耗时和
   可用的公交票价。
4. 结构化输出：POI/路线结果进入候选与 `TransportLeg`，再投影为 `trip-dataset.v1`；
   来源、查询时间、`price_type` 与 `confidence` 保留。

## 测试

```powershell
& "runtime\python\python.exe" -m pytest tests/test_amap_place_search.py tests/test_amap_route_search.py tests/test_amap_generation_integration.py -q
```

覆盖：POI 解析、空结果、地理编码、逆地理编码、步行/公交/驾车解析、缺票价、
无效 Key、超时、未配置 Key、餐饮身份映射。

## 真实联网验收结果

2026-10-18 使用本机 `AMAP_WEB_SERVICE_KEY` 执行，Key 未写入仓库或日志：

| 项目 | 结果 |
| --- | --- |
| POI 搜索 | 杭州“雷峰塔”返回 3 条真实 POI |
| POI 搜索 | 杭州“灵隐寺”返回 `amap:B023B02842` 等 3 条 |
| 地理编码 | 灵隐寺地址解析成功，adcode `330106` |
| 逆地理编码 | 返回“浙江省杭州市西湖区西湖街道杭州西湖风景名胜区雷峰塔景区” |
| 步行路线 | 雷峰塔 → 灵隐寺：6199 m / 83 分钟 / 无票价 |
| 公交路线 | 同起终点：6627 m / 52 分钟 / ¥2，`published_transit_fare` |

真实调用通过 `global_route_search` 工具路径完成，provider 为 `amap`。Mock 测试仍单独保留，
不会把模拟结果写成真实结果。

## 已知限制

- 未接入酒店实时房价/房态；
- 公交票价可能缺失或只覆盖部分城市/线路；
- 驾车耗时是高德预计值，不是未来路况保证；
- MCP 高德服务与本地服务共享同一个 Key 与限流；不要同时配置冲突的 Key；
- 真实 Key 的 IP/域名白名单、服务权限需按高德控制台实际错误处理。

# 相对原 GitHub 项目的改动

原项目：<https://github.com/Lagom-TA/JourneyPilot.git>  
对比基线：`main` 分支提交 `20a79d5`（fix(deployment): persist backups and
archive formal runtime verification）  
对比对象：本整合包内的 `app/` 源码树  
对比日期：2026-10-18

对比时排除了纯产物与本地运行数据：`node_modules`、`.venv`、`__pycache__`、
`.pytest_cache`、`.ruff_cache`、`static/`、`data/`、`.env`、`config.yaml`。
因此下面的统计描述的是**源码、前端、文档和测试**的差异。

文件级结果：**新增 46 个、修改 35 个、删除 6 个**。完整清单见
`CHANGED-FILES.md`。

---

## 一、新增：生成旅途的结构化数据契约

原来的行程主要是给人看的文本/页面结构；现在每次生成都会同时产出一份
`trip-dataset.v1` 结构化数据，供风险评估直接导入。

- `src/travel_agent/entities/trip_dataset.py`
- `src/travel_agent/services/trip_dataset_builder.py`
- `src/travel_agent/api/routes/trip_dataset.py`
- `docs/trip-dataset.v1.md`
- `docs/examples/trip-dataset.v1.schema.json`
- `docs/examples/trip-dataset.v1.sample.json`

数据覆盖：行程基本信息、逐日路线、餐饮、住宿、活动与体力、费用明细、
数据来源与可信度、未知/估算状态。费用由后端汇总，模型不负责加总。
新格式带 `schema_version` 和 `compatibility`，旧版本行程通过适配器读取。

## 二、新增：风险评估自动导入与四项风险引擎

新增独立的“风险评估”模块，和“生成旅途”保持两个页面、两个领域服务：

- 后端
  - `src/travel_agent/entities/travel_risk.py`
  - `src/travel_agent/entities/risk_dataset_import.py`
  - `src/travel_agent/services/travel_risk_engine.py`
  - `src/travel_agent/services/travel_risk_adapter.py`
  - `src/travel_agent/services/travel_risk_optimizer.py`
  - `src/travel_agent/services/trip_dataset_risk_adapter.py`
  - `src/travel_agent/api/routes/risk.py`
- 前端
  - `frontend/src/components/pages/RiskAssessmentPage.tsx`
  - `frontend/src/components/pages/RiskDatasetPage.tsx`
  - `frontend/src/components/risk/RiskExplanationChain.tsx`
  - `frontend/src/components/risk/RiskOptimizationLoop.tsx`
  - `frontend/src/types/risk.ts`
- 文档
  - `docs/risk-dataset-import.md`
  - `docs/risk-engine.md`

导入后自动读取路线、餐饮、住宿、活动时长、休息、交通和费用；用户原则上
只需要填写“总预算上限”。四项风险（天气/预算/交通/体力）都保留证据链、
缺失数据和估算标记。

## 三、新增：高德地图数据接入

- `src/travel_agent/services/amap_client.py`
- `src/travel_agent/services/amap_place_search.py`
- `src/travel_agent/services/amap_route_search.py`
- `scripts/configure_amap.py`
- `scripts/verify_amap.py`
- `docs/amap-integration.md`
- `.agents/skills/amap-travel-data-integration/SKILL.md`
- `.agents/skills/amap-travel-data-integration/references/api-contract.md`

能力：中国大陆 POI、地理编码/逆地理编码、步行/公交/驾车路线、可获取的
公交票价和距离。未配置 Key 时保持未配置状态，不伪造查询结果。

## 四、新增：DeepSeek 工具调用与外部数据接入规范

- `docs/development/deepseek-tool-calling.md`
- `docs/development/travel-data-integration.md`

规范了工具参数校验、执行、结果回传、异常处理、调用终止条件，以及外部
数据源的来源记录、可信度、缓存、超时和失败降级。Skill 只作为开发指导，
真正的联网查询由后端执行。

## 五、行程生成质量修复（2026-10-18）

这一组是针对真实运行中“每天只排到中午”“景点太少”“四天行程反复失败”
做的修复，全部有回归测试：

### 1. 候选供给按行程天数计算

- `src/travel_agent/agents/destination_researcher/prompts.py`
- `src/travel_agent/agents/destination_researcher/node.py`

研究包必须按“每个非交通日两个 Visit”准备候选：三天至少 6 个，四天至少
8 个。此前提示词里唯一的数字是“三天至少 6 个”，四天行程会把它当成目标
停在 6 个，返程日下午无点可排。

### 2. 研究包候选上限从 4 提到 12

- `src/travel_agent/agents/research_packet_output.py`

旧上限 4 正好等于“每天一个景点”，模型想排第五个也会被 JSON Schema 拒绝。
现在 12 覆盖四天 ×（2 景点 + 1 餐），三天 6 景点 + 3 餐也留有余量。

### 3. 禁止泛化品类查询污染候选池

- `src/travel_agent/agents/research_packet_output.py`

`museum in 杭州` 这类查询会被 Nominatim 用 OSM 标签随机填充，结果里会出现
道路、辅道、社区纪念馆、单间私人收藏。现在服务端会把这些来源的选项从
可选集合中丢弃，只保留具体地标名的查询结果；这是确定性过滤，不依赖模型
自觉。

### 4. 市内接驳补研不再按接驳条数放大

- `src/travel_agent/agents/orchestrator/candidate_gate.py`

一轮补研本来就会查询**全部**接驳，但预算曾按接驳条数计算。四天行程 10 段
接驳 = 10 轮，每轮约 1 分钟，直接在 10 分钟组合窗口内耗尽，报
`composition_window_exhausted`。现在一轮覆盖全部、最多两轮，失败后按
明确的“未核实路线”降级交付。

### 5. 保留高德路线的换乘链

- `src/travel_agent/tools/governance.py`

工具结果净化器原来把所有字典截断到 12 个键，高德路线正好有 15 个键，
`segments` 被丢掉，路线因而无法准入。现在路线字典按自己的 schema 保留
20 个键，`segments` 仍单独限制 12 段。

### 6. 行程时长按“天数”而不是“每天条目数”判断

- `src/travel_agent/services/intent_verification.py`

`三天行程` 曾被误判成“每天最多三条安排”。一天排满（两个景点、两段交通、
午晚餐）有六七个条目，越丰富越会被判违约。现在行程级时长比较总天数，
域内“每天最多 N 个”仍保持原语义。

### 7. 完整一天改为软偏好，长途缺失不阻塞

- `src/travel_agent/agents/itinerary_planner/node.py`
- `src/travel_agent/agents/orchestrator/delivery_quality_gate.py`

候选充足时优先上午景点、午餐、下午第二个景点、晚上晚餐；营业时间、体力、
天气或真实到达时刻不允许时允许缩短，不再用固定时段模板硬塞。没有长途
交通候选时继续生成，并把长途交通记录为待核实，而不是整趟失败。

### 8. 启动器避开被 ACL 破坏的 Redis 目录

- `launcher.py`

旧数据目录 `.state/redis` 在异常/沙箱运行后可能带上拒绝写入的 ACL，
Redis 无法写 AOF，整个应用启动失败。启动器现在使用全新的
`.state/redis-store`，首次启动自动创建。

## 六、前端改动

- `frontend/src/App.tsx`
- `frontend/src/components/sidebar/SidebarNav.tsx`
- `frontend/src/context/AppContext.tsx`
- `frontend/src/lib/api.ts`

新增“风险评估”导航与页面，接入数据集导入、四项风险结果、解释链和优化
前后对比；生成旅途和风险评估仍然是两个独立入口。

## 七、便携运行与配置

- 新增 `windows_entry.py`、`app/config.portable.yaml`
- `launcher.py`：首次启动初始化数据库、Redis、API，自动选择空闲端口，
  生成 `.state/install.json` 和本机 `app/config.yaml`
- `start.cmd` / `stop.cmd` / `restart.cmd` / `status.cmd` /
  `configure-api.cmd`
- `README-FIRST.txt`

包内自带 Python 3.11、Node、PostgreSQL 18 + pgvector、Redis 和本地
CPU 向量模型，队友不需要安装开发环境。

## 八、测试与验证

- 新增 12 个测试文件，覆盖数据集、风险引擎、风险导入、高德 POI/路线、
  工具结果契约和生成-风险联动
- 修改 6 个既有测试文件，补充本次质量修复的回归用例
- 最近一次全量：`746 passed, 1 failed`。失败项是
  `test_slow_normalization_calls_share_one_operation_budget`，它依赖
  0.02/0.035 秒的调度间隙，属于既有的计时竞态；同一测试在上一轮全量中
  是通过的，与本次改动文件无关
- Ruff 检查：改动文件全部通过

真实运行样例（2026-10-18）：

- 三天武汉→杭州：`trip_8ed77de68201470a`，6 个景点、每天午餐+晚餐、
  结束时间 18:30–19:00
- 四天武汉→杭州：`trip_18e7325e190e4a14`，候选 8 个代表性景点，
  行程使用 6 个（抵达/返程日为交通日），12 段路线中 8 段为高德/12306
  实测

## 九、删除/精简

便携包相对原仓库删除了纯开发/CI 资产：

- `.gitleaks.toml`
- `PRODUCT.md`
- `harness_handoff_2026-10-08.md`
- `harness_review_2026-10-08.md`
- `open.sh`
- `run.sh`

同时**不打包**：`app/.env`、`app/config.yaml`、`.state/`、
`app/data/usage/`、`app/frontend/node_modules/`、各类缓存和日志。
首次启动会重新生成配置和空数据库。

---

## 十、如何自行复现文件差异

```bash
git clone https://github.com/Lagom-TA/JourneyPilot.git upstream
cd upstream
git checkout 20a79d5
git archive --format=zip -o ../upstream.zip HEAD
```

解压 `upstream.zip`，与整合包内 `app/` 对比，排除：

```
node_modules  .venv  __pycache__  .pytest_cache  .ruff_cache
static  data  .env  config.yaml
```

即可得到与本包 `CHANGED-FILES.md` 相同范围的差异。

# DeepSeek 工具调用开发规范

本文件是项目级开发规范。仓库当前没有 `.codex/skills` / `.agents/skills` 目录，
因此不新增一套 Skill 运行时；规范以文档形式随代码维护。若以后引入项目级
Skills，可直接把本文件内容迁移为 `deepseek-tool-calling/SKILL.md`。

## 1. 现状（本阶段审计结论）

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 模型客户端 | `src/travel_agent/models/router.py` | 统一 `ainvoke` / `ainvoke_with_tools` / 流式 |
| Provider 能力声明 | `config/providers.py` + `configs/providers/*.yaml` | `supports_json_schema`、`supports_json_object` 等 |
| DeepSeek preset | `configs/providers/deepseek.yaml` | `supports_json_schema: false`，走 `json_object` + prompt 内 schema |
| 工具注册 | `src/travel_agent/tools/registry.py` | 名称、JSON Schema、executor、manifest |
| 工具治理 | `src/travel_agent/tools/gateway.py` | 调用前后审计、权限与结果封装 |
| MCP 连接 | `src/travel_agent/tools/mcp_manager.py` | 初始化 45s、单次调用 60s 超时；失败释放租约 |
| Agent 工具白名单 | `src/travel_agent/agents/utils.py` | destination/transport/accommodation 各自限定 server 与工具 |

DeepSeek 官方 endpoint 当前**不支持** `response_format={"type":"json_schema"}`。
不要因为「模型叫 DeepSeek」就假设它支持严格 schema；以 `ProviderCapabilities`
的实际声明为准。未声明支持时，路由器会降级为 `json_object` 并在提示中写明 schema。

## 2. 新增工具必须遵守

1. **先注册，再调用**：`ToolRegistry.register(name, description, parameters_schema, executor, manifest=...)`。
2. **参数校验在 executor 入口完成**：类型、范围、枚举、必填项；不要依赖模型自觉。
3. **返回值必须可判定**：失败/超时/无结果/成功四态明确，不允许用空列表冒充成功。
4. **结果带来源**：provider、URL 或数据源 ID、检索时间、原始摘要；不得只回一段无出处的自然语言。
5. **不把网页片段解析成「已核实价格」**：价格必须来自结构化字段或明确标注的参考价。
6. **不记录密钥**：参数、异常、审计日志中都不得出现 API Key。

## 3. 调用终止条件

工具循环必须同时受以下边界约束：

- Run 预算：`run_budget.max_tool_calls`、重试次数、token/费用上限；
- 时间：`run_deadline` 与 `await_model_operation` 的超时；
- 重试：指数退避，`max_retries + 1` 次后停止；
- 结果：`EMPTY_SUCCESS`（provider 明确无命中）不重试、不换工具；
- 轮次：同一意图重复调用同一工具且参数无变化时停止。

参考实现：`agents/utils.py` 的 `classify_tool_result` 与重试循环。

## 4. 与结构化输出的关系

- 模型负责「提出候选实体/叙述理由」，**不负责最终金额加总**。
- 任何进入 `trip-dataset.v1` 的字段都必须经过 Pydantic 校验。
- 模型输出若包含数字，只能作为 `program_estimate` 或 `itinerary_estimate`，
  且必须带 `assumptions`；不得写入 `actual_quote`。
- 数据集构建器 `services/trip_dataset_builder.py` 不调用模型、不联网。

## 5. 测试要求

新增工具至少覆盖：

1. 正常结果；
2. 上游报错；
3. 超时；
4. 成功但零结果；
5. 参数非法；
6. 审计记录中包含来源与状态。

没有真实 Key 时使用假 MCP 客户端或 monkeypatch；测试中不得发起真实付费调用。

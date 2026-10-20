# AI 旅行风险决策助手 · V3

基于 [Lagom-TA/JourneyPilot](https://github.com/Lagom-TA/JourneyPilot) 扩展的 AI 旅行规划与风险评估项目。本仓库保存 2026-10-18 Windows V3 整合包中的应用源码、前端构建产物、测试和说明。

## 功能

- 生成逐日旅行方案，组织景点、餐饮、住宿、交通及其来源。
- 通过 `trip-dataset.v1` 结构化行程导入风险评估，支持 JSON 文件导入。
- 评估天气、预算、交通、体力四项风险，展示计算规则、证据和缺失数据。
- 提供优化草稿与优化前后对比；缺失资料保留待核实状态。
- 提供高德地点及路线接入，具体能力取决于配置和外部服务可用性。

风险评估采用确定性规则，不代表事故概率预测。住宿、餐饮和交通报价可能不完整，已知费用小计不能当作整趟总预算。

## 目录

| 路径 | 内容 |
| --- | --- |
| `app/src/travel_agent/` | 后端、规划流程、数据契约和风险引擎 |
| `app/frontend/` | React 前端源码 |
| `app/static/` | V3 已构建网页 |
| `app/tests/` | 自动化测试 |
| `app/docs/` | 架构、接口与数据契约 |
| `launcher.py`、`*.cmd` | Windows 免安装包启动器 |
| `GUIDE-zh.md` | Windows 完整整合包使用说明 |
| `CHANGELOG-vs-upstream-zh.md` | 相对原项目的改动说明 |
| `CHANGED-FILES.md` | 相对原项目的文件级差异清单 |

## 运行说明

**源码仓库与 Windows 免安装包包含的运行环境不同。** 本仓库不包含 `runtime/`、`node_modules/`、模型缓存、个人配置或数据库。仅下载 GitHub 源码后，不能直接双击 `start.cmd` 启动；该启动器需要完整免安装包的内置运行环境。

完整 Windows V3 免安装包见 [Releases / v3.0.0](https://github.com/xiesq883/ai-travel-risk-v3/releases/tag/v3.0.0)。使用流程见 [GUIDE-zh.md](GUIDE-zh.md)：解压、运行 `start.cmd`、填写自己的模型 API 配置，然后打开风险页。私有仓库的下载者需要具备仓库访问权限。

源码开发请在 `app/` 中准备 Python 3.11、Node/npm、PostgreSQL/pgvector 和 Redis，依据 [应用说明](app/README.zh-CN.md)、[配置文档](app/docs/configuration.md) 及示例配置安装依赖和配置服务。Python 依赖由 `pyproject.toml` 和 `uv.lock` 管理；前端依赖由 `app/frontend/package-lock.json` 管理。API 启动前需要执行数据库迁移。

API Key 只保存在本机环境变量或未跟踪的 `.env` 中，请勿提交。示例中的模型名称、外部服务权限和价格需按自己的实际账号配置。

## 版本来源

- 输入整合包：`AI旅行风险决策助手-Windows64-20261018-V3.zip`
- 整合包 SHA-256：`DC1E9ECDCDDB20D2F5AD61F6F837AB482EDE73E4AF451FF2B31123D371D59EF2`
- 上游对比基线：`20a79d5`（详见随包改动说明）
- 应用源文件保持 V3 包内容；整理时仅增加仓库首页、根目录许可和 Git 忽略配置，排除运行时、依赖及操作系统缓存。

## 许可

保留原项目 MIT 许可，见 [LICENSE](LICENSE)。第三方组件说明见 [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt)。

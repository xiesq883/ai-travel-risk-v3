# Changed files vs upstream HEAD

- added: 46
- modified: 35
- deleted: 6

## By area

| area | added | modified | deleted |
|---|---:|---:|---:|
| .agents | 2 | 0 | 0 |
| .env.example | 1 | 0 | 0 |
| .gitignore | 0 | 1 | 0 |
| .gitleaks.toml | 0 | 0 | 1 |
| PRODUCT.md | 0 | 0 | 1 |
| README.md | 0 | 1 | 0 |
| README.zh-CN.md | 0 | 1 | 0 |
| alembic.ini | 0 | 1 | 0 |
| config.portable.yaml | 1 | 0 | 0 |
| config.yaml | 1 | 0 | 0 |
| docs | 8 | 0 | 0 |
| frontend | 6 | 4 | 0 |
| harness_handoff_2026-10-08.md | 0 | 0 | 1 |
| harness_review_2026-10-08.md | 0 | 0 | 1 |
| open.sh | 0 | 0 | 1 |
| pyproject.toml | 0 | 1 | 0 |
| run.sh | 0 | 0 | 1 |
| scripts | 2 | 0 | 0 |
| src/travel_agent/agents | 0 | 7 | 0 |
| src/travel_agent/api | 2 | 1 | 0 |
| src/travel_agent/config | 0 | 2 | 0 |
| src/travel_agent/entities | 3 | 0 | 0 |
| src/travel_agent/models | 0 | 1 | 0 |
| src/travel_agent/rag | 0 | 2 | 0 |
| src/travel_agent/services | 7 | 4 | 0 |
| src/travel_agent/tools | 0 | 2 | 0 |
| tests | 12 | 6 | 0 |
| uv.lock | 0 | 1 | 0 |
| windows_entry.py | 1 | 0 | 0 |

## Added

- `.agents/skills/amap-travel-data-integration/SKILL.md`
- `.agents/skills/amap-travel-data-integration/references/api-contract.md`
- `.env.example`
- `config.portable.yaml`
- `config.yaml`
- `docs/amap-integration.md`
- `docs/development/deepseek-tool-calling.md`
- `docs/development/travel-data-integration.md`
- `docs/examples/trip-dataset.v1.sample.json`
- `docs/examples/trip-dataset.v1.schema.json`
- `docs/risk-dataset-import.md`
- `docs/risk-engine.md`
- `docs/trip-dataset.v1.md`
- `frontend/src/components/pages/RiskAssessmentPage.tsx`
- `frontend/src/components/pages/RiskDatasetPage.tsx`
- `frontend/src/components/risk/RiskExplanationChain.test.ts`
- `frontend/src/components/risk/RiskExplanationChain.tsx`
- `frontend/src/components/risk/RiskOptimizationLoop.tsx`
- `frontend/src/types/risk.ts`
- `scripts/configure_amap.py`
- `scripts/verify_amap.py`
- `src/travel_agent/api/routes/risk.py`
- `src/travel_agent/api/routes/trip_dataset.py`
- `src/travel_agent/entities/risk_dataset_import.py`
- `src/travel_agent/entities/travel_risk.py`
- `src/travel_agent/entities/trip_dataset.py`
- `src/travel_agent/services/amap_client.py`
- `src/travel_agent/services/amap_place_search.py`
- `src/travel_agent/services/travel_risk_adapter.py`
- `src/travel_agent/services/travel_risk_engine.py`
- `src/travel_agent/services/travel_risk_optimizer.py`
- `src/travel_agent/services/trip_dataset_builder.py`
- `src/travel_agent/services/trip_dataset_risk_adapter.py`
- `tests/test_amap_generation_integration.py`
- `tests/test_amap_place_search.py`
- `tests/test_amap_research_packet.py`
- `tests/test_amap_route_search.py`
- `tests/test_risk_dataset_api.py`
- `tests/test_tool_result_contract.py`
- `tests/test_travel_risk_adapter.py`
- `tests/test_travel_risk_engine.py`
- `tests/test_travel_risk_optimizer.py`
- `tests/test_trip_dataset.py`
- `tests/test_trip_dataset_api.py`
- `tests/test_trip_dataset_risk_import.py`
- `windows_entry.py`

## Modified

- `.gitignore`
- `README.md`
- `README.zh-CN.md`
- `alembic.ini`
- `frontend/src/App.tsx`
- `frontend/src/components/sidebar/SidebarNav.tsx`
- `frontend/src/context/AppContext.tsx`
- `frontend/src/lib/api.ts`
- `pyproject.toml`
- `src/travel_agent/agents/destination_researcher/node.py`
- `src/travel_agent/agents/destination_researcher/prompts.py`
- `src/travel_agent/agents/itinerary_planner/node.py`
- `src/travel_agent/agents/orchestrator/candidate_gate.py`
- `src/travel_agent/agents/orchestrator/delivery_quality_gate.py`
- `src/travel_agent/agents/research_packet_output.py`
- `src/travel_agent/agents/utils.py`
- `src/travel_agent/api/app.py`
- `src/travel_agent/config/loader.py`
- `src/travel_agent/config/mcp_defaults.py`
- `src/travel_agent/models/usage_spool.py`
- `src/travel_agent/rag/sources/document_parse.py`
- `src/travel_agent/rag/sources/document_parser_worker.py`
- `src/travel_agent/services/amap_route_search.py`
- `src/travel_agent/services/intent_verification.py`
- `src/travel_agent/services/pdf_export.py`
- `src/travel_agent/services/weather_impact_engine.py`
- `src/travel_agent/tools/builtin_tools.py`
- `src/travel_agent/tools/governance.py`
- `tests/agent_behavior/test_intent_composition_fidelity.py`
- `tests/agent_behavior/test_intent_research_ranking_selection.py`
- `tests/conftest.py`
- `tests/test_mcp_defaults_contract.py`
- `tests/test_tool_result_summary.py`
- `tests/test_usage_spool.py`
- `uv.lock`

## Deleted

- `.gitleaks.toml`
- `PRODUCT.md`
- `harness_handoff_2026-10-08.md`
- `harness_review_2026-10-08.md`
- `open.sh`
- `run.sh`

# RAG Schema Context 升级完成总结

**完成日期**：2025-03-06  
**开发方式**：5 个并行 Agent 分别完成任务，合并验收

---

## 1. 解决了哪些问题

| 原问题 | 解决方案 |
|--------|----------|
| **top_k=8 导致召回不足** | 引入两阶段检索：`top_k_large=24` 召回候选，`top_k_final=12` 输出，提高上下文容量 |
| **domain/edge 挤占 table/join** | 类型配额策略：至少 2 个 table、2 个 join，domain 占比不超过 30% |
| **命中 join 但缺两侧表结构** | 图扩展 `_expand_by_graph()`：命中 join 或 er_edge 时自动补齐 from/to 表 chunk |
| **上下文是平铺文本，LLM 难利用** | 结构化输出：`## Candidate Tables`、`## Recommended Join Paths`、`## Domain Hints`、`## SQL Constraints` |
| **无法灰度与回滚** | 环境变量开关 `MINE_RAG_HYBRID_ENABLED`，关闭即恢复旧行为 |
| **检索问题难定位** | 结构化日志：chunk_count、table_count、join_count、context_len、hybrid_enabled |
| **chunk 无法按类型计算** | 新增 metadata：`chunk_type`、`table_refs`、`column_refs`、`keywords`、`priority` |

---

## 2. 提高了哪些指标/能力

| 能力 | 升级前 | 升级后 |
|------|--------|--------|
| 向量召回量 | 8 | 24（可配置） |
| 最终输出量 | 8 | 12（可配置） |
| 表/join 最低保障 | 无 | 至少 2 table + 2 join |
| Join 两侧表完整性 | 依赖向量相似度 | 图扩展强制补齐 |
| 输出结构 | 平铺 `- chunk` | 分组段落（Candidate Tables / Join Paths / Domain / Constraints） |
| 可观测性 | 无 | 日志含 chunk_count、table_count、join_count、context_len |
| 回滚方式 | 需代码回退 | 单环境变量即可 |

---

## 3. 新增/修改的文件

| 文件 | 变更 |
|------|------|
| `src/mine_agent/api/fastapi/knowledge_context.py` | KnowledgeChunk、两阶段检索、配额重排、图扩展、结构化输出、配置与日志 |
| `src/mine_agent/api/fastapi/knowledge_routes.py` | vectorize 写入 chunk_type、table_refs 等 metadata |
| `src/mine_agent/core/vector/base.py` | 新增 `search_with_score` |
| `src/mine_agent/integrations/vector/inmemory.py` | 实现 `search_with_score` |
| `docs/chunk-metadata-spec.md` | 新增，chunk metadata 结构规范 |
| `docs/rag-config-and-flags.md` | 新增，RAG 环境变量与回滚说明 |
| `docs/rag-test-report-template.md` | 新增，测试报告模板 |
| `docs/embedding-and-retrieval-flow.md` | 更新，补充 Hybrid 检索流程 |
| `tests/unit/test_knowledge_context.py` | 扩展：配额、图扩展、开关、结构化输出、fixture |
| `tests/fixtures/knowledge/hr_demo.json` | 新增，hr_demo 基准知识库 |
| `tests/integration/test_chat_schema_context_pipeline.py` | 新增（如已实现），Chat 流程 schema 注入验收 |

---

## 4. 测试与验收

### 4.1 通过的单元测试（knowledge_context）

| 用例 | 说明 |
|------|------|
| `test_build_chat_knowledge_context_from_vector_hits` | 向量检索命中时 Schema Context 正确注入 |
| `test_build_chat_knowledge_context_fallback_without_vector` | 无向量时使用 fallback |
| `test_hybrid_flow_expands_join_tables` | Hybrid 开启时 join 两侧表被补齐 |
| `test_build_knowledge_chunks_includes_metadata_chunk_type_and_table_refs` | chunks metadata 包含 chunk_type、table_refs |
| `test_rerank_with_quota_ensures_min_tables_and_min_joins` | 配额至少包含 min_tables 个 table、min_joins 个 join |
| `test_search_with_score_returns_score` | search_with_score 返回 (id, meta, score) |
| `test_expand_by_graph_adds_join_tables` | 图扩展命中 join 时补齐 employees、departments |
| `test_hybrid_disabled_keeps_old_behavior` | MINE_RAG_HYBRID_ENABLED=false 时保持旧行为 |
| `test_format_structured_schema_context_output` | 结构化输出包含 Candidate Tables、Recommended Join Paths |
| `test_hr_demo_fixture_loaded` | hr_demo.json fixture 可加载 |

运行命令：

```bash
cd mine && PYTHONPATH=src python3 -m pytest tests/unit/test_knowledge_context.py -v
```

### 4.2 验收结论

- **功能**：召回增强、配额重排、图扩展、结构化 prompt、配置开关、日志均已落地。
- **兼容性**：`MINE_RAG_HYBRID_ENABLED=false` 时行为与升级前一致。
- **质量**：knowledge_context 相关单测 10/10 通过。

---

## 5. 使用与回滚

### 启用新流程（默认）

无需配置，默认启用。

### 回滚到升级前行为

```bash
export MINE_RAG_HYBRID_ENABLED=false
```

### 调整召回/输出规模

```bash
export MINE_RAG_TOPK_LARGE=32
export MINE_RAG_TOPK_FINAL=16
```

### 关闭图扩展（保留配额）

```bash
export MINE_RAG_GRAPH_EXPAND_ENABLED=false
```

---

## 6. 后续可选优化

- 混合检索：向量 + 关键词/表名匹配（当前仅向量）
- 置信度门控：低覆盖时在 SQL Constraints 追加「仅用已确认表」等约束
- 评测集：20–30 条问句跑 table_coverage、join_coverage、sql_exec_success_rate 对比

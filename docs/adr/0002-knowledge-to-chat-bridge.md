# ADR 0002: 知识库与 Chat 的衔接缺失分析

## 背景

用户流程：

1. **连接配置**：创建 demo、hr_demo 等数据库连接
2. **Schema 抽取**：选为抽取 → 执行抽取 → 异步增强（LLM 推断 join_paths、er_graph）
3. **ER 图 / JSON**：编辑并保存 Schema-Aware 知识库
4. **向量化**：将知识库 chunk 后 embedding，存入 VectorStore（`knowledge:{source_id}`）
5. **Chat 问答**：期望根据问题 + 知识库生成 NL2SQL

## 当前实现 vs 期望

| 环节 | 期望 | 当前实现 | 状态 |
|------|------|----------|------|
| 连接 | 使用已创建连接执行 SQL | `DataSourceRouter` + `MINE_DATASOURCES` / 动态 config | ✅ 已实现 |
| source_id | Chat 指定使用哪个数据源 | `metadata.source_id` → `preferred_source_id` → `query_data` 默认 | ✅ 已实现 |
| 知识库内容 | 表、列、join 关系等 | 保存到 `~/.mine/knowledge/{source_id}.json` | ✅ 已实现 |
| 向量化 | 语义检索用 | 存入 `vector_store` namespace `knowledge:{source_id}` | ✅ 已实现 |
| **Chat 上下文** | **根据问题检索知识库，注入 prompt，生成 SQL** | **Orchestrator 未使用 vector_store** | ❌ **缺失** |

## 问题本质

`Orchestrator._build_system_prompt()` 只注入：

```
You are a data analyst assistant. Use query_data with source_id='xxx'.
Do not run table/schema exploration. Prefer a single query...
```

**没有**：表名、列名、join 关系、DDL 等 Schema 信息。LLM 在「盲写」SQL，无法准确引用实际表结构。

向量化后的知识库存在 `app.state.vector_store`，但 Chat 流程从未：

- 根据用户问题做向量检索
- 将检索到的 schema 内容注入 system prompt

## 正确流程（应按此实现）

```
用户问题 "查一下各部门人数"
  ↓
1. 根据 preferred_source_id (如 hr_demo) 确定 namespace: knowledge:hr_demo
2. 用 embedding 服务将问题向量化
3. vector_store.search(namespace, query_vector, top_k=10)
4. 拼接检索到的 chunk 文本（表结构、join 描述等）
5. system_prompt += "\n## Schema Context\n" + retrieved_text
6. LLM 基于该上下文生成 SQL
7. query_data 使用 hr_demo 连接执行
```

## 与 vanna-nl2sql-core-logic-summary 的对应

文档中已明确：

- **LlmContextEnhancer**：在 system prompt 中注入上下文
- **SchemaProvider**：从数据源/知识库获取 schema
- **向量检索**：根据问题语义检索 ddl/documentation（类似 Legacy RAG）

mine 当前无 LlmContextEnhancer，也未在 chat 前从 vector_store 检索。

## 建议实现

1. **LlmContextEnhancer 接口**：`enhance(system_prompt, user_message, source_id) -> str`
2. **KnowledgeEnhancer 实现**：
   - 若有 `source_id`，从 `load_knowledge(source_id)` 取 JSON
   - 用用户问题向量检索 `vector_store.search("knowledge:{source_id}", query_vec, top_k=8)`
   - 将 knowledge JSON 中相关 tables/join_paths 摘要 + 检索 chunk 拼接为 schema context
   - 若无可检索内容，直接使用 knowledge JSON 的 tables 描述作为 fallback
3. **Orchestrator 集成**：在 `chat()` 中，构建 `LlmRequest` 前调用 enhancer，将增强后的 prompt 传给 LLM

## 总结

**是的，执行向量化后，Chat 理应使用：**

1. 已创建的连接（demo/hr_demo）—— 已使用 ✅  
2. Schema-Aware 知识库 —— **未使用** ❌  

当前缺失的是「知识库 → Chat」的桥接：在生成 SQL 前，从向量库/知识文件中取出相关 schema，注入到 LLM 的 prompt 中。

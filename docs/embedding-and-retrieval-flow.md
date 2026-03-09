# 知识库 Embedding 与 Chat 检索流程

## 1. 向量化了哪些信息

`build_knowledge_chunks()` 将知识库 JSON 切分为文本 chunk，经 embedding 后存入 VectorStore。当前共 **4 类** chunk：

| 类型 | chunk_id | 来源 | 文本示例 |
|------|----------|------|----------|
| **表信息** | `table:{表名}` | `tables[]` | `Table: employees. 员工表. Columns: employee_id(NUMBER): 员工ID, name(VARCHAR2): 姓名` |
| **分组/域** | `domain:{组名}` | `er_graph.nodes[].group` | `Domain: Order Management. Tables: orders, order_items, shipments.` |
| **Join 路径** | `join:{i}` | `join_paths[]` | `employees.dept_id 关联 departments.id，表示部门归属` |
| **ER 边** | `er_edge:{i}` | `er_graph.edges[]`（且未在 join_paths 中重复的） | `employees dept_id -> departments id` |

> **说明**：分组信息来自 Schema 抽取的「异步增强」流程，当 `use_grouping=true` 且表数 > 3 时，LLM 会按业务模块分组，分组名写入 `er_graph.nodes[].group`。

---

## 2. 用户提问时的相似性查询流程

当用户发起 Chat 请求时，`build_chat_knowledge_context()` 会执行以下逻辑：

```
用户问题 "查各部门人数"
         ↓
┌────────────────────────────────────────────────────────────────────────┐
│ 1. 确定 namespace：knowledge:{source_id}（如 knowledge:hr_demo）      │
│ 2. 用户问题 embedding：embedding_service.embed([user_message])         │
│ 3. 向量检索：vector_store.search(namespace, query_vector, top_k=8)   │
│ 4. 取 top_k 个最相似的 chunk，按 metadata["text"] 取文本               │
└────────────────────────────────────────────────────────────────────────┘
         ↓
  snippets = [检索到的 chunk 文本列表]
         ↓
  去重、截断至 top_k，格式化为 system prompt 中的 Schema Context
```

**核心实现**（`knowledge_context.py`）：

```python
query_vecs = await embedding_service.embed([user_message])
query_vec = query_vecs[0]
neighbors = vector_store.search(namespace=f"knowledge:{sid}", vector=query_vec, top_k=8)
for chunk_id, meta in neighbors:
    text = meta.get("text", "")
    snippets.append(text)
```

**相似性计算**：由 VectorStore 实现（如 InMemory、Qdrant 等）执行余弦相似度或内积，返回与 `user_message` 向量最相似的 `top_k` 个 chunk。

---

## 3. 无检索结果时的降级逻辑

当向量检索**未命中**或**出错**时，按以下顺序降级：

| 层级 | 条件 | 行为 |
|------|------|------|
| **L1** | `embedding_service` 或 `vector_store` 为 None | 不执行向量检索，直接进入 L2 |
| **L1** | `user_message` 为空 | 不执行向量检索 |
| **L1** | 向量检索异常（如 API 失败） | `except` 捕获后静默，进入 L2 |
| **L1** | 向量检索返回空（namespace 无数据或 top_k=0） | snippets 为空，进入 L2 |
| **L2** | snippets 为空 | 取 `chunks[:top_k]` 的前 8 个 chunk 文本（按 build 顺序） |
| **L3** | chunks 为空 | 调用 `build_schema_fallback_context()`，从 knowledge JSON 生成简要摘要 |
| **L4** | fallback 也为空 | 返回空字符串，不注入 Schema Context |

**L2 说明**：L2 不依赖向量，按表、分组、join、er_edge 的固定顺序取前 8 个 chunk，相当于「默认给前 8 个」。

**L3 说明**：`build_schema_fallback_context()` 输出格式类似：

```
- employees: employee_id, name, dept_id
- departments: id, name
- join: employees.dept_id -> departments.id
```

---

## 4. 完整流程概览

```
                    ┌─────────────────────────────────────┐
                    │  load_knowledge(source_id)          │
                    │  chunks = build_knowledge_chunks()   │
                    └─────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │ embedding_service & vector_store  │
                    │ 是否可用？user_message 非空？     │
                    └─────────────────┬─────────────────┘
                        是 ↙              ↘ 否
        ┌──────────────────────┐    ┌──────────────────────┐
        │ embed(user_message)  │    │ snippets = []         │
        │ vector_store.search  │    └──────────┬───────────┘
        │ → neighbors (top_k)  │               │
        │ → snippets           │               │
        └──────────┬───────────┘               │
                   │                           │
                   └───────────┬───────────────┘
                               │ snippets 为空？
                   ┌───────────┴───────────┐
                   是 ↙                     ↘ 否
        ┌──────────────────────┐    ┌──────────────────────┐
        │ snippets = chunks     │    │ 去重，格式化输出     │
        │        [:top_k]       │    │ "## Schema Context   │
        └──────────┬────────────┘    │  (retrieved...)\n"   │
                   │                 └──────────────────────┘
                   │ snippets 仍为空？
        ┌──────────┴──────────┐
        是 ↙                   ↘ 否
┌────────────────────┐   ┌────────────────────┐
│ build_schema_      │   │ 去重，格式化输出   │
│ fallback_context() │   └────────────────────┘
└────────────────────┘
```

---

## 5. 升级后的 Hybrid 检索流程（MINE_RAG_HYBRID_ENABLED=true）

当 `MINE_RAG_HYBRID_ENABLED=true`（默认）时，使用增强检索流程：

```
用户问题 "查各部门人数"
         ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. 向量召回：search_with_score(namespace, query_vec, top_k=24)             │
│ 2. 配额重排：_rerank_with_quota() 确保至少 2 个 table、2 个 join           │
│ 3. 图扩展：_expand_by_graph() 命中 join 时补齐 employees、departments      │
│ 4. 结构化输出：_format_structured_schema_context()                         │
│    - ## Candidate Tables                                                    │
│    - ## Recommended Join Paths                                               │
│    - ## Domain Hints                                                         │
│    - ## SQL Constraints                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

**配置**：见 [docs/rag-config-and-flags.md](rag-config-and-flags.md)  
**Metadata 规范**：见 [docs/chunk-metadata-spec.md](chunk-metadata-spec.md)  
**回滚**：`MINE_RAG_HYBRID_ENABLED=false` 即可恢复旧行为（top_k=8）。

---

## 6. 相关文件

| 文件 | 职责 |
|------|------|
| `knowledge_context.py` | `build_knowledge_chunks`, `build_chat_knowledge_context`, `_retrieve_candidates`, `_rerank_with_quota`, `_expand_by_graph`, `_format_structured_schema_context` |
| `knowledge_routes.py` | `vectorize_knowledge`（chunk → embed → 写入 VectorStore，含 metadata） |
| `app.py` | Chat 请求时调用 `build_chat_knowledge_context`，将 schema_context 传给 Orchestrator |
| `core/vector/base.py` | `VectorStore.search_with_score` |
| `integrations/vector/inmemory.py` | `InMemoryVectorStore.search_with_score` |

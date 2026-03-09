# Chunk Metadata 结构规范

本文档描述 RAG 知识库 chunk 的 metadata 结构，用于 embedding/vectorize 后的检索与重排。

---

## 1. 结构概览

`build_knowledge_chunks()` 将知识库 JSON 切分为 `KnowledgeChunk`，每个 chunk 包含：

- **chunk_id**: 唯一标识，格式 `{type}:{id}`
- **text**: 用于 embedding 的文本
- **metadata**: 结构化元数据字典

---

## 2. metadata 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk_type` | `str` | 类型：`table` \| `domain` \| `join` \| `er_edge` \| `summary` |
| `table_refs` | `List[str]` | 涉及的表名列表 |
| `column_refs` | `List[str]` | 涉及的列名列表 |
| `keywords` | `List[str]` | 业务关键词（如 domain 名） |
| `priority` | `int` | 默认权重：table=2, join=2, domain=1, er_edge=1, summary=0 |

---

## 3. 按 chunk_type 解析规则

### 3.1 table

- **来源**: `tables[]`
- **chunk_id**: `table:{表名}`
- **table_refs**: `[表名]`
- **column_refs**: 从 `columns` 中提取的列名列表
- **keywords**: `[]`
- **priority**: `2`

### 3.2 domain

- **来源**: `er_graph.nodes[].group`
- **chunk_id**: `domain:{组名}`
- **table_refs**: 该分组下的表名列表
- **column_refs**: `[]`
- **keywords**: `[组名]`
- **priority**: `1`

### 3.3 join

- **来源**: `join_paths[]`
- **chunk_id**: `join:{索引}`
- **table_refs**: 从 `from.table`、`to.table` 解析
- **column_refs**: 从 `from.column`、`to.column` 解析
- **keywords**: `[]`
- **priority**: `2`

### 3.4 er_edge

- **来源**: `er_graph.edges[]`（且未在 join_paths 中重复的边）
- **chunk_id**: `er_edge:{索引}`
- **table_refs**: `[source, target]`
- **column_refs**: `[source_column, target_column]`（若存在）
- **keywords**: `[]`
- **priority**: `1`

### 3.5 summary

- **来源**: 当无其他 chunk 时的兜底
- **chunk_id**: `summary`
- **table_refs**: `[]`
- **column_refs**: `[]`
- **keywords**: `[]`
- **priority**: `0`

---

## 4. VectorStore 写入

`vectorize_knowledge` 将 chunk 写入 VectorStore 时，metadata 包含：

```json
{
  "source_id": "knowledge_source_id",
  "chunk_id": "table:employees",
  "text": "Table: employees. ...",
  "chunk_type": "table",
  "table_refs": ["employees"],
  "column_refs": ["employee_id", "name", "dept_id"],
  "keywords": [],
  "priority": 2
}
```

检索与重排可基于 `chunk_type`、`table_refs`、`column_refs`、`priority` 进行过滤与排序。

---

## 5. 向后兼容

- `KnowledgeChunk` 支持 `for chunk_id, text in chunks` 的解包，与原有 `(chunk_id, text)` 用法兼容
- 若无 metadata 的旧 chunk，vectorize 时使用默认值：`chunk_type=""`、`table_refs=[]`、`column_refs=[]`、`keywords=[]`、`priority=0`

# RAG 配置与开关说明

本文档描述知识库检索（RAG）相关的环境变量配置、默认值与回滚方式。

## 环境变量一览

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MINE_RAG_HYBRID_ENABLED` | `true` | 是否启用混合检索（召回 + 重排 + 图扩展） |
| `MINE_RAG_TOPK_LARGE` | `24` | 向量召回时的 top_k（仅 hybrid 开启时生效） |
| `MINE_RAG_TOPK_FINAL` | `12` | 最终输出到 prompt 的 chunk 数量（仅 hybrid 开启时生效） |
| `MINE_RAG_GRAPH_EXPAND_ENABLED` | `true` | 是否启用图扩展（命中 join/er_edge 时补齐两侧表 chunk） |
| `MINE_RAG_CONFIDENCE_GUARD_ENABLED` | `true` | 是否启用置信度守护（预留，当前版本暂未使用） |

## 详细说明

### MINE_RAG_HYBRID_ENABLED

- **默认**：`true`（便于联调与观察新行为）
- **行为**：
  - `true`：使用混合检索流程（`top_k_large` 召回 → 配额重排 → 可选图扩展 → 截断至 `top_k_final`）
  - `false`：与升级前一致，仅使用单次向量检索，`top_k=8`

### MINE_RAG_TOPK_LARGE

- **默认**：`24`
- **说明**：向量检索阶段召回的候选 chunk 数量，仅当 `MINE_RAG_HYBRID_ENABLED=true` 时生效

### MINE_RAG_TOPK_FINAL

- **默认**：`12`
- **说明**：最终注入 Schema Context 的 chunk 数量，仅当 `MINE_RAG_HYBRID_ENABLED=true` 时生效

### MINE_RAG_GRAPH_EXPAND_ENABLED

- **默认**：`true`
- **说明**：当命中 join 或 er_edge 时，是否自动补齐两侧表 chunk，仅当 `MINE_RAG_HYBRID_ENABLED=true` 时生效

### MINE_RAG_CONFIDENCE_GUARD_ENABLED

- **默认**：`true`
- **说明**：预留开关，用于未来置信度过滤等逻辑，当前版本仅读取配置，不影响行为

## 布尔值解析规则

以下值均视为 `true`：`1`、`true`、`yes`、`on`（大小写不敏感）

其余非空值或空字符串均视为 `false`

## 回滚方式

**完全回退到升级前行为**：

```bash
export MINE_RAG_HYBRID_ENABLED=false
```

或启动前设置环境变量：

```bash
MINE_RAG_HYBRID_ENABLED=false python -m uvicorn ...
```

**部分回滚**（保留 hybrid，关闭图扩展）：

```bash
export MINE_RAG_HYBRID_ENABLED=true
export MINE_RAG_GRAPH_EXPAND_ENABLED=false
```

**调整召回与输出规模**：

```bash
export MINE_RAG_TOPK_LARGE=32
export MINE_RAG_TOPK_FINAL=16
```

## 日志与可观测性

当 `build_chat_knowledge_context` 执行时，会输出结构化日志（`logger.info`），包含：

| 字段 | 说明 |
|------|------|
| `source_id` | 知识库 source_id |
| `chunk_count` | 命中 chunk 数量 |
| `dedup_count` | 去重后 snippet 数量 |
| `table_count` | 命中的 table 类 chunk 数量 |
| `join_count` | 命中的 join/er_edge 类 chunk 数量 |
| `context_len` | 最终 Schema Context 字符数 |
| `hybrid_enabled` | 是否启用了 hybrid 模式 |

示例：

```json
{
  "message": "build_chat_knowledge_context",
  "source_id": "hr_demo",
  "chunk_count": 12,
  "dedup_count": 10,
  "table_count": 4,
  "join_count": 3,
  "context_len": 1245,
  "hybrid_enabled": true
}
```

## 相关文件

- 配置读取与日志：`src/mine_agent/api/fastapi/knowledge_context.py`
- Chat 路由：`src/mine_agent/api/fastapi/app.py`（不传配置，由 `knowledge_context` 内 `os.getenv` 读取）

# Chat Trace Visibility 协议说明

Chat Trace Visibility 计划定义事件/响应中的 trace 字段，用于调试、前端展示和可观测性。

---

## 1. 事件与响应协议

### 1.1 涉及端点

| 端点 | 协议 | trace 位置 |
|------|------|------------|
| `POST /v1/chat` | JSON | 响应体 `trace`、`trace_id` |
| `POST /api/vanna/v2/chat_poll` | JSON | 响应体 `trace`、`trace_id` |
| `POST /api/vanna/v2/chat_sse` | SSE | 每个 `data:` 行的 JSON 中 `debug` 字段 |

### 1.2 请求头

| 名称 | 说明 |
|------|------|
| `X-Trace-Id` | 可选。客户端传入的请求 trace ID，若未提供则由服务端生成 UUID |
| `Authorization` | Bearer token（当 `api_auth_enabled=true` 时必填） |

### 1.3 响应头

| 名称 | 说明 |
|------|------|
| `X-Trace-Id` | 本次请求的 trace ID，便于关联日志与响应 |

---

## 2. trace 字段定义

### 2.1 顶层结构

```json
{
  "trace_id": "uuid-or-client-provided",
  "trace": {
    "retrieval": { ... },
    "llm_rounds": [ ... ],
    "tool_results": [ ... ]
  }
}
```

- `trace_id`：字符串，请求级唯一 ID
- `trace`：可选对象，包含 retrieval、llm_rounds、tool_results。任一子字段可缺省，兼容旧客户端

### 2.2 retrieval（来自 build_chat_knowledge_context）

| 字段 | 类型 | 说明 |
|------|------|------|
| `prompt_context` | string | 注入 LLM 的 schema context 文本 |
| `retrieved_chunks` | array | 命中 chunk 列表 |
| `table_count` | number | 命中 table 类 chunk 数量 |
| `join_count` | number | 命中 join/er_edge 类 chunk 数量 |

**retrieved_chunks 每项结构：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk_id` | string | 如 `table:employees`、`join:0` |
| `chunk_type` | string | table / join / domain / er_edge / other |
| `text` | string | chunk 文本内容 |
| `score` | number \| null | 向量相似度得分（若可用） |
| `table_refs` | array | 引用表名列表 |
| `column_refs` | array | 引用列名列表 |

### 2.3 llm_rounds（来自 orchestrator.chat）

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | string | assistant |
| `content` | string | LLM 回复内容 |
| `tool_calls` | array | 本轮调用的 tool 列表 |
| `is_final` | boolean | 是否为最终回复（无后续 tool call） |

### 2.4 tool_results（来自 orchestrator.chat）

| 字段 | 类型 | 说明 |
|------|------|------|
| `tool_name` | string | 如 query_data |
| `arguments` | object | 调用参数 |
| `content` | string | 工具返回内容摘要 |
| `metadata_summary` | object | 元数据（如 source_id、row_count） |
| `error` | string \| null | 错误信息（成功时为 null） |

---

## 3. 前端展示说明

### 3.1 展示建议

- **retrieval**：在「知识库检索」面板展示 `retrieved_chunks` 的 chunk_id、chunk_type、score，支持展开查看 text
- **llm_rounds**：按轮次展示 assistant 回复与 tool_calls，可折叠
- **tool_results**：展示工具名、参数、结果摘要、错误状态

### 3.2 兼容性

- `trace` 为可选字段，未实现时可为 `null`，前端应做空值判断
- SSE 中 `debug` 仅在实现时存在，结构同 `trace`

### 3.3 示例（简化）

```json
{
  "trace_id": "abc-123",
  "trace": {
    "retrieval": {
      "retrieved_chunks": [
        {"chunk_id": "table:employees", "chunk_type": "table", "score": 0.92}
      ],
      "table_count": 1,
      "join_count": 0
    },
    "llm_rounds": [
      {"role": "assistant", "content": "", "tool_calls": [...], "is_final": false},
      {"role": "assistant", "content": "查询结果...", "tool_calls": [], "is_final": true}
    ],
    "tool_results": [
      {"tool_name": "query_data", "arguments": {"sql": "SELECT ..."}, "content": "...", "error": null}
    ]
  }
}
```

---

## 4. 回滚方式

若需临时关闭 trace 或回滚：

| 方式 | 说明 |
|------|------|
| 配置开关 | 可通过新增 `MINE_CHAT_TRACE_ENABLED=false` 环境变量控制（若实现） |
| 前端忽略 | 不解析 `trace` / `debug`，仅使用 `assistant_content`、`tool_outputs` |
| API 版本 | 保持 `trace`、`trace_id` 为可选，旧客户端不受影响 |
| 部署回滚 | 回滚到不包含 trace 的镜像/版本 |

当前实现中 `trace` 为可选字段，不破坏现有客户端，无需额外配置即可安全回滚。

---

## 5. 相关实现

| 模块 | 职责 |
|------|------|
| `knowledge_context.build_chat_knowledge_context` | 返回 `ChatContextResult(prompt_context, retrieval_trace)` |
| `orchestrator.chat` | 返回 `llm_rounds`、`tool_results` |
| `app._unpack_knowledge_context` | 解包 ChatContextResult / tuple / str |
| `app._build_trace` | 组装 trace 字典 |
| `app.chat` / `legacy_chat_poll` | 在响应中附加 `trace_id`、`trace` |
| `app.legacy_chat_sse` | 在 chunk 中附加 `debug`（同 trace） |

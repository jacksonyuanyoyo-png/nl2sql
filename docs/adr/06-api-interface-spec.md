# Mine 项目接口文档

本文档基于当前 `mine/src` 代码实现整理，覆盖：

- 对外 HTTP 接口（FastAPI）
- 内部抽象接口（核心代码契约）
- 内置工具接口（`query_data`）

## 1. 对外 HTTP 接口

接口实现文件：`mine/src/mine_agent/api/fastapi/app.py`

### 1.1 `GET /v1/health`

- **用途**：服务存活检查
- **鉴权**：否
- **请求体**：无
- **响应体**

```json
{
  "status": "ok"
}
```

- **curl 示例**

```bash
curl -X GET http://localhost:8000/v1/health
```

---

### 1.2 `GET /health`（兼容接口）

- **用途**：兼容旧版 notebook 前端的健康检查
- **鉴权**：否
- **请求体**：无
- **响应体**

```json
{
  "status": "ok"
}
```

- **curl 示例**

```bash
curl -X GET http://localhost:8000/health
```

---

### 1.3 `GET /v1/metadata`

- **用途**：返回服务元信息与数据源注册/健康状态
- **鉴权**：否
- **请求体**：无
- **响应体字段**
  - `service_name: string`
  - `service_version: string`
  - `environment: string`
  - `auth_enabled: boolean`
  - `registered_data_sources: string[]`
  - `data_source_health: Record<string, boolean>`
- **响应示例**

```json
{
  "service_name": "mine-agent",
  "service_version": "0.1.0",
  "environment": "dev",
  "auth_enabled": false,
  "registered_data_sources": ["oracle_hr", "snowflake_sales"],
  "data_source_health": {
    "oracle_hr": true,
    "snowflake_sales": false
  }
}
```

- **curl 示例**

```bash
curl -X GET http://localhost:8000/v1/metadata
```

---

### 1.4 `POST /v1/chat`

- **用途**：标准聊天接口（推荐）
- **鉴权**：可选（由 `MINE_API_AUTH_ENABLED` 控制）
  - 开启时必须传 `Authorization: Bearer <token>`
- **请求头**
  - `Authorization`（可选/按配置）
  - `X-Trace-Id`（可选；不传则服务端自动生成）
- **请求体模型**：`ChatRequest`（`mine/src/mine_agent/api/fastapi/models.py`）
  - `conversation_id: string`（必填）
  - `user_message: string`（必填）
  - `user_id?: string`
  - `metadata?: Record<string, string>`（可传 `source_id`）
- **请求示例**

```json
{
  "conversation_id": "conv-001",
  "user_message": "查询最低工资员工的经理是谁",
  "user_id": "u-123",
  "metadata": {
    "source_id": "oracle_hr"
  }
}
```

- **响应体模型**：`ChatResponse`
  - `assistant_content: string`
  - `tool_outputs: string[]`
- **响应示例**

```json
{
  "assistant_content": "最低工资员工的经理是 ...",
  "tool_outputs": [
    "Query succeeded. source_id=oracle_hr, row_count=1, columns=['MANAGER_NAME']"
  ]
}
```

- **curl 示例**

```bash
# 无鉴权
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "conv-001",
    "user_message": "查询最低工资员工的经理是谁",
    "user_id": "u-123",
    "metadata": { "source_id": "oracle_demo" }
  }'

# 开启鉴权时
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "X-Trace-Id: my-trace-123" \
  -d '{
    "conversation_id": "conv-001",
    "user_message": "查询最低工资员工的经理是谁",
    "metadata": { "source_id": "oracle_hr" }
  }'
```

---

### 1.5 `POST /api/vanna/v2/chat_poll`（兼容接口）

- **用途**：兼容旧版 Vanna 前端，轮询模式
- **鉴权**：当前实现未接入 Bearer 校验
- **请求体（字典）**
  - `message: string`
  - `conversation_id?: string`（不传则后端生成）
  - `request_id?: string`（不传则后端生成）
  - `metadata?: object`（可传 `source_id`）
- **请求示例**

```json
{
  "message": "查看员工总数",
  "conversation_id": "conv-001",
  "request_id": "req-001",
  "metadata": {
    "source_id": "oracle_hr"
  }
}
```

- **响应示例**

```json
{
  "conversation_id": "conv-001",
  "request_id": "req-001",
  "chunks": [
    {
      "type": "assistant_message_chunk",
      "conversation_id": "conv-001",
      "request_id": "req-001",
      "simple": { "type": "text", "text": "..." }
    }
  ]
}
```

- **curl 示例**

```bash
curl -X POST http://localhost:8000/api/vanna/v2/chat_poll \
  -H "Content-Type: application/json" \
  -d '{
    "message": "查看员工总数",
    "conversation_id": "conv-001",
    "request_id": "req-001",
    "metadata": { "source_id": "oracle_hr" }
  }'
```

---

### 1.6 `POST /api/vanna/v2/chat_sse`（兼容接口）

- **用途**：兼容旧版 Vanna 前端，SSE 流模式
- **鉴权**：当前实现未接入 Bearer 校验
- **请求体**：与 `chat_poll` 一致
- **响应类型**：`text/event-stream`
  - 事件数据格式：`data: <json>\n\n`
  - 结束标记：`data: [DONE]\n\n`
- **curl 示例**

```bash
curl -X POST http://localhost:8000/api/vanna/v2/chat_sse \
  -H "Content-Type: application/json" \
  -N \
  -d '{
    "message": "查看员工总数",
    "conversation_id": "conv-001",
    "metadata": { "source_id": "oracle_hr" }
  }'
```

> 说明：`-N` 禁用 curl 缓冲，便于实时查看 SSE 流。

---

### 1.7 错误响应约定

错误模型定义：`mine/src/mine_agent/api/common/errors.py`

- 统一结构：

```json
{
  "error_code": "BAD_REQUEST",
  "message": "Request failed",
  "trace_id": "..."
}
```

- 已定义错误码：
  - `UNAUTHORIZED`
  - `FORBIDDEN`
  - `BAD_REQUEST`
  - `ORCHESTRATOR_NOT_CONFIGURED`
  - `INTERNAL_ERROR`

## 2. 内部抽象接口（代码契约）

以下接口为核心可扩展点，供不同实现（OpenAI/Mock、Oracle/Snowflake、本地存储等）适配：

### 2.1 `LlmService`

文件：`mine/src/mine_agent/core/llm/base.py`

- `send_request(request: LlmRequest) -> LlmResponse`
- `stream_request(request: LlmRequest) -> AsyncGenerator[LlmStreamChunk, None]`
- `validate_tools(tools: List[ToolSchema]) -> List[str]`

---

### 2.2 `Tool`

文件：`mine/src/mine_agent/core/tool/base.py`

- 属性：
  - `name: str`
  - `description: str`
  - `access_groups: Optional[List[str]]`（默认 `None`）
- 方法：
  - `get_args_schema() -> ToolSchema`
  - `execute(args: Dict[str, Any], context: ToolContext) -> ToolResult`

---

### 2.3 `ConversationStore`

文件：`mine/src/mine_agent/core/storage/base.py`

- `get_messages(conversation_id: str) -> List[Message]`
- `append_message(conversation_id: str, message: Message) -> None`

---

### 2.4 `DataSource`

文件：`mine/src/mine_agent/capabilities/data_source/base.py`

- 属性：
  - `source_id: str`
- 方法：
  - `test_connection() -> bool`
  - `execute_query(request: QueryRequest) -> QueryResult`
  - `list_tables(schema: str | None = None) -> List[str]`

## 3. 核心服务接口（非抽象但对外部调用关键）

### 3.1 `Orchestrator.chat`

文件：`mine/src/mine_agent/engine/orchestrator.py`

- 签名：
  - `chat(conversation_id, user_message, user_id=None, preferred_source_id=None) -> Dict[str, object]`
- 返回：
  - `assistant_content: str`
  - `tool_outputs: List[str]`
- 说明：
  - `preferred_source_id` 会被注入系统提示词，并作为工具执行默认数据源（`default_source_id`）。

---

### 3.2 `DataSourceRouter`

文件：`mine/src/mine_agent/capabilities/data_source/router.py`

- `register(source: DataSource) -> None`
- `get_source(source_id: str) -> DataSource`
- `list_source_ids() -> list[str]`
- `health_check_all() -> dict[str, bool]`
- `execute_query(request: QueryRequest) -> QueryResult`

## 4. 内置工具接口

### 4.1 `query_data`

文件：`mine/src/mine_agent/tools/query_data.py`

- **工具名**：`query_data`
- **参数 schema**
  - `sql: string`（必填）
  - `source_id?: string`（选填；若未传则尝试使用 `default_source_id`）
  - `limit?: integer`（默认 `1000`，范围 `1~10000`）
- **成功输出**
  - `content`：文本摘要（含 `source_id`、`row_count`、`columns`）
  - `metadata`：包含 `source_id`、`row_count`、`rows`

## 5. 备注

- 当前代码中未实现 `/api/vanna/v2/chat_websocket` 路由。
- 若后续新增接口，建议同步更新本文档并增加对应单元测试/契约测试。


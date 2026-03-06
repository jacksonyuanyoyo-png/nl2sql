# mine-agent 阶段开发总结（截至当前）

本文档汇总 `@mine` 项目从初始化到当前的主要开发成果、测试验证结果、当前状态与下一步计划。

## 1. 项目目标与原则

项目目标：

- 在公司内部独立实现一套可控 Agent 框架，借鉴架构思想但不复制外部源码。
- 支持多层架构、可扩展工具机制、Oracle/Snowflake 数据源接入、API 服务化。
- 以高可用、高维护性、可观测性为工程目标。

核心原则（已在 ADR 中落地）：

- 契约优先（Contract-First）
- 分层解耦（core / capabilities / integrations / tools / engine / api）
- 安全默认（只读 SQL、鉴权、审计）
- 测试优先（unit + contract + integration + e2e）

## 2. 架构与目录落地情况

当前已形成的关键目录与职责：

- `src/mine_agent/core`：LLM/Tool/Storage 抽象与模型
- `src/mine_agent/capabilities/data_source`：数据源能力契约、错误体系、SQL Guard、Router
- `src/mine_agent/integrations`：Oracle/Snowflake/Mock/Local 适配
- `src/mine_agent/tools`：`QueryDataTool`
- `src/mine_agent/engine`：`Orchestrator` 主循环
- `src/mine_agent/api`：FastAPI 接入层与兼容路由
- `src/mine_agent/config`：应用配置与数据源环境加载
- `src/mine_agent/observability`：结构化日志与审计函数
- `tests`：`unit`、`contract`、`integration`、`e2e`
- `docs`：ADR、路线图、任务板、测试手册、阶段总结

## 3. 已完成开发内容

### 3.1 第一阶段（基础骨架）

- 初始化 Python 项目与包结构（`pyproject.toml`、`README`、`src`、`tests`、`docs`）
- 实现核心协议层：
  - `core/llm`：`LlmService` + request/response 模型
  - `core/tool`：`Tool`、`ToolRegistry`、`ToolContext`、`ToolResult`
  - `core/storage`：`ConversationStore`、消息模型
- 实现最小运行链路：
  - `engine/orchestrator.py`
  - `integrations/local/storage.py`
  - `integrations/mock/llm.py`
  - `tools/query_data.py`

### 3.2 第二阶段（8-Agent 第 1 轮）

- 数据源异常体系：`DataSourceError` 及子类
- SQL 安全校验：只读语句与 schema 白名单
- DataSourceRouter 增强：注册保护、查询、健康检查
- Oracle/Snowflake 适配器骨架增强（驱动缺失、错误位点、查询位点）
- QueryDataTool 参数校验与返回结构增强
- Orchestrator 可靠性增强：
  - `max_tool_iterations`
  - LLM/Tool 异常兜底
- FastAPI 最小可用 API：
  - `/v1/health`
  - `/v1/chat`

### 3.3 第三阶段（P1 补齐）

- 鉴权与错误处理：
  - Bearer Token 验证（可开关）
  - 统一错误码响应
- trace 能力：
  - `X-Trace-Id` 注入与回传
- 配置能力：
  - `AppSettings.from_env()`
- 可观测性基础：
  - JSON 结构化日志
  - 审计函数（含 SQL hash）
- 新增 `/v1/metadata`

### 3.4 第四阶段（8-Agent 第 2 轮）

- Oracle 真实适配器实现：
  - `oracledb` 实际连接与查询
  - `test_connection` / `execute_query` / `list_tables`
  - 异常映射到统一错误模型
- SQL Guard 真接线到 Oracle/Snowflake 适配器
- 数据源配置增强（`MINE_DATASOURCES` JSON + fail-fast）
- 审计闭环增强（QueryDataTool 成功/失败全记录）
- 新增 contract tests 框架
- 新增 integration tests（Oracle）
- 新增 e2e tests（chat 全链路）

### 3.5 协议兼容改造（Notebook 联调）

针对 `@vanna/notebooks/react-flask-chat` 的旧协议调用，已新增兼容路由：

- `GET /health`
- `POST /api/vanna/v2/chat_sse`
- `POST /api/vanna/v2/chat_poll`

并保留新接口：

- `GET /v1/health`
- `GET /v1/metadata`
- `POST /v1/chat`

## 4. Oracle 本地联调结果

已验证以下本地 Oracle 配置可联通：

- host: `localhost`
- port: `1521`
- service: `XE`
- user: `hr`
- password: `hr`

结果：

- `tests/integration`：通过（3 passed）
- `/v1/chat` 实测可查询 `SELECT 1 FROM dual`
- legacy SSE 接口可返回 chunk + `[DONE]`

## 5. 测试与质量结果

已覆盖测试层级：

- `tests/unit`
- `tests/contract`
- `tests/integration`
- `tests/e2e`

阶段性结果（关键节点）：

- `unit + contract + e2e`: 147 passed
- `integration (Oracle)`: 3 passed
- API 兼容新增后：`test_api_fastapi.py` 全通过
- `ReadLints`：无新增 linter 错误

## 6. 当前状态评估

当前状态：

- 已达到“可联调、可演示、可持续开发”状态。
- 已具备 FastAPI 启动与 notebook 前端兼容能力。
- Oracle 本地链路可用。

尚未完全达到“生产就绪”：

- Snowflake 真实连库实现仍需补全与联调验证
- 更完整的 metrics/tracing（当前为基础版）
- 更细粒度权限策略与多租户治理
- 部署与运维层能力（灰度、容量、SLO）尚未系统化

## 7. 启动与调试说明（当前推荐）

使用 `tools` 环境：

```bash
eval "$(conda shell.zsh hook)"
conda activate tools
cd /Users/jackson/Documents/project/Fidelity/vanna/mine
```

设置环境变量（示例）：

```bash
export MINE_API_AUTH_ENABLED=false
export MINE_DATASOURCES='[
  {
    "source_id":"oracle_demo",
    "source_type":"oracle",
    "options":{
      "user":"hr",
      "password":"hr",
      "host":"localhost",
      "port":1521,
      "service_name":"XE"
    }
  }
]'
```

启动服务：

```bash
uvicorn --factory mine_agent.api.fastapi.app:create_app --host 0.0.0.0 --port 8000 --reload
```

可用接口：

- `/v1/health`
- `/v1/metadata`
- `/v1/chat`
- `/health`（legacy）
- `/api/vanna/v2/chat_sse`（legacy）
- `/api/vanna/v2/chat_poll`（legacy）

## 8. 下一步建议（优先级）

P1（高优先）：

- 完成 Snowflake 真实连库实现与 integration tests
- 增加 `/api/vanna/v2/chat_websocket` 兼容占位或实现
- 增强 API 文档与错误码说明

P2（中优先）：

- 完善 metrics 与 tracing（Prometheus/OpenTelemetry）
- 增加连接池参数化与并发压测
- 增加运行手册与故障排查手册

P3（增强）：

- 记忆能力（memory capability + tools）
- workflow 命令短路体系（help/status/admin actions）

## 9. 相关文档索引

- `docs/adr/0001-architecture-principles.md`
- `docs/01-development-roadmap.md`
- `docs/02-module-testing-playbook.md`
- `docs/03-agent-task-board.md`
- `docs/04-agent-task-board-round2.md`

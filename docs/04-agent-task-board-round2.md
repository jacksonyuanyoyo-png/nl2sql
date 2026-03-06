# 8-Agent 第二轮任务单（P1/P2 实战版）

## 背景

当前项目已具备可开发骨架与稳定 unit tests。第二轮目标是推进到“可真实联调 Oracle + 测试体系分层 + API 能力补齐”。

已知本地 Oracle（Docker）环境：

- host: `localhost`
- port: `1521`
- service/SID: `XE`
- system user/password: `system` / `oracle`
- app user/password: `app` / `app`

## 本轮目标

- 完成 Oracle 真实连接与查询链路
- 补齐 API `/v1/metadata`
- 建立 contract/integration/e2e 的最小框架
- 加强审计与配置加载

## Agent 任务分配

### Agent-1：Oracle 真实适配器（核心）

- 文件：
  - `src/mine_agent/integrations/oracle/client.py`
  - `tests/unit/test_oracle_adapter.py`
- 任务：
  - 接入 `oracledb` 的真实连接与查询执行（含 `test_connection`、`execute_query`、`list_tables`）
  - 将异常映射为 `DataSourceError` 体系
  - 支持连接参数：host/port/service_name 或 dsn
- 验收：
  - 无驱动时错误可读
  - 有驱动时行为符合 `DataSource` 契约

### Agent-2：Oracle 集成测试（本地 Docker）

- 文件：
  - `tests/integration/test_oracle_integration.py`
  - `tests/integration/conftest.py`
- 任务：
  - 基于环境变量读取 Oracle 连接
  - 增加 smoke 场景：连通性、简单查询、list_tables
  - 提供 skip 策略（环境不满足时自动跳过）
- 验收：
  - 在本地 Oracle 可用时可跑通
  - CI 默认可跳过

### Agent-3：SQL Guard 与 Adapter 真正接线

- 文件：
  - `src/mine_agent/integrations/oracle/client.py`
  - `src/mine_agent/integrations/snowflake/client.py`
- 任务：
  - 在 `execute_query` 中调用 `validate_readonly_sql`
  - 根据 `allowed_schemas` 调用 `validate_allowed_schemas`
  - 将 SQL 校验失败映射到 `SqlValidationError`
- 验收：
  - 非法 SQL 在数据源层被阻断
  - 单测覆盖拦截路径

### Agent-4：API `/v1/metadata` + 数据源状态汇总

- 文件：
  - `src/mine_agent/api/fastapi/models.py`
  - `src/mine_agent/api/fastapi/app.py`
  - `tests/unit/test_api_fastapi.py`
- 任务：
  - 新增 `GET /v1/metadata`
  - 返回服务信息、auth 开关、已注册数据源 ID、health_check_all 摘要
- 验收：
  - 无 orchestrator 时仍可返回基础 metadata
  - 有 router 时可返回健康状态

### Agent-5：配置系统加强（数据源配置加载）

- 文件：
  - `src/mine_agent/config/datasources.py`
  - `src/mine_agent/config/settings.py`
  - `tests/unit/test_settings.py`
- 任务：
  - 支持从环境变量加载 Oracle/Snowflake 数据源定义
  - 增加 fail-fast 校验（关键字段缺失时报错）
- 验收：
  - dev/prod 可无代码切换
  - 缺配置时启动失败

### Agent-6：审计闭环增强（Tool + Orchestrator）

- 文件：
  - `src/mine_agent/tools/query_data.py`
  - `src/mine_agent/engine/orchestrator.py`
  - `tests/unit/test_query_data_tool.py`
- 任务：
  - 在查询成功/失败路径记录审计事件（sql hash、source_id、status、row_count）
  - 在 orchestrator 增加回合级日志字段
- 验收：
  - 关键路径日志可追踪
  - 不改变现有返回结构

### Agent-7：Contract Tests 框架

- 文件：
  - `tests/contract/test_datasource_contract.py`
- 任务：
  - 抽象一套 DataSource 契约测试基线（test_connection/execute_query/list_tables）
  - 让 Oracle/Snowflake 适配器都可复用（通过 fixture 参数化）
- 验收：
  - contract 可独立执行
  - 契约失败可定位到具体适配器

### Agent-8：E2E 测试最小闭环

- 文件：
  - `tests/e2e/test_chat_api_e2e.py`
- 任务：
  - 启动 FastAPI TestClient，走 `/v1/chat` 完整链路
  - 覆盖鉴权成功、鉴权失败、工具执行失败兜底
- 验收：
  - 至少 3 条 e2e 测试通过

## 并行策略

- 第一批（先跑）：Agent-1 ~ Agent-4
- 第二批（后跑）：Agent-5 ~ Agent-8

## 统一执行约束

- 默认环境：`eval "$(conda shell.zsh hook)" && conda activate tools`
- Python 使用绝对导入
- 每个任务至少包含单测/对应层级测试
- 不引入破坏性改动

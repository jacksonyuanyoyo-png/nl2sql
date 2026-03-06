# 8-Agent 开发任务清单（执行版）

## 目标

在不破坏现有骨架的前提下，推进 `mine_agent` 到可进行真实模块开发与联调的状态。  
任务按“低耦合、可并行、可独立验收”拆分，优先保证高可用与高维护性。

## Agent 任务分配

### Agent-1：数据源错误模型与异常标准化

- **模块**：`capabilities/data_source`
- **任务**：
  - 新增统一错误模型（如 `DataSourceError` 及子类）。
  - 定义错误码与可重试标识。
  - 补充文档注释，便于 `engine/tool/api` 统一处理。
- **建议文件**：
  - `src/mine_agent/capabilities/data_source/errors.py`
  - `src/mine_agent/capabilities/data_source/__init__.py`（如有必要）
- **验收**：
  - 不依赖具体驱动。
  - 可被 Oracle/Snowflake/Tool 层直接复用。

### Agent-2：SQL 安全校验能力（只读策略）

- **模块**：`capabilities/data_source`
- **任务**：
  - 新增 SQL 校验器：拦截 DDL/DML，允许 SELECT/WITH。
  - 增加 schema 白名单校验接口。
  - 提供可复用函数供 Tool/Adapter 调用。
- **建议文件**：
  - `src/mine_agent/capabilities/data_source/sql_guard.py`
  - `tests/unit/test_sql_guard.py`
- **验收**：
  - 高风险语句被拒绝。
  - 典型只读查询可通过。

### Agent-3：DataSourceRouter 增强

- **模块**：`capabilities/data_source`
- **任务**：
  - 增加重复注册保护。
  - 增加 `get_source`、`list_source_ids`、`health_check_all`。
  - 统一未知数据源错误行为。
- **建议文件**：
  - `src/mine_agent/capabilities/data_source/router.py`
  - `tests/unit/test_data_source_router.py`
- **验收**：
  - 路由行为可预测，异常语义明确。

### Agent-4：Oracle 适配器完善（真实实现骨架）

- **模块**：`integrations/oracle`
- **任务**：
  - 完善 `test_connection/execute_query/list_tables` 的工程化骨架。
  - 增加驱动缺失提示与异常映射。
  - 增加超时参数与 limit 处理位点。
- **建议文件**：
  - `src/mine_agent/integrations/oracle/client.py`
  - `tests/unit/test_oracle_adapter.py`
- **验收**：
  - 无驱动场景下错误可读。
  - 接口行为与 `DataSource` 契约一致。

### Agent-5：Snowflake 适配器完善（真实实现骨架）

- **模块**：`integrations/snowflake`
- **任务**：
  - 完善 `test_connection/execute_query/list_tables` 的工程化骨架。
  - 增加驱动缺失提示与异常映射。
  - 增加 warehouse/database/schema 配置处理位点。
- **建议文件**：
  - `src/mine_agent/integrations/snowflake/client.py`
  - `tests/unit/test_snowflake_adapter.py`
- **验收**：
  - 无驱动场景下错误可读。
  - 接口行为与 `DataSource` 契约一致。

### Agent-6：QueryDataTool 加固

- **模块**：`tools`
- **任务**：
  - 强化参数校验与边界处理。
  - 增加异常映射为用户可读信息。
  - 输出结构增加审计字段（row_count/source_id）。
- **建议文件**：
  - `src/mine_agent/tools/query_data.py`
  - `tests/unit/test_query_data_tool.py`
- **验收**：
  - 非法参数在工具层被阻断。
  - 返回结构稳定可消费。

### Agent-7：Orchestrator 可靠性增强

- **模块**：`engine`
- **任务**：
  - 增加最大工具迭代控制与失败保护。
  - 区分 LLM 错误、Tool 错误并落地统一返回。
  - 增加主循环行为单测（成功/失败/异常）。
- **建议文件**：
  - `src/mine_agent/engine/orchestrator.py`
  - `tests/unit/test_orchestrator_resilience.py`
- **验收**：
  - 不因单点失败导致整体崩溃。
  - 失败路径可追踪。

### Agent-8：API 最小可用层（FastAPI）

- **模块**：`api`
- **任务**：
  - 新建 FastAPI app 与 `/v1/health`、`/v1/chat`。
  - 请求响应模型与异常映射最小实现。
  - 增加 API 层基础测试（健康检查 + chat smoke）。
- **建议文件**：
  - `src/mine_agent/api/fastapi/app.py`
  - `src/mine_agent/api/fastapi/models.py`
  - `tests/unit/test_api_fastapi.py`
- **验收**：
  - 能拉起服务并完成一次 chat 调用。

## 并行执行策略

- 第一批并行：Agent-1 ~ Agent-4
- 第二批并行：Agent-5 ~ Agent-8
- 原则：尽量减少同文件冲突，批次间由主控 agent 进行合并校验。

## 统一工程约束

- Python 导入必须使用绝对导入。
- 保持 ASCII 文本。
- 每个任务必须附带最少单测。
- 开发与测试默认使用：`conda activate tools`。

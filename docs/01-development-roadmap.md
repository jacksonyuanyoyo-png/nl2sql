# 开发任务清单与模块落地路线图

本文档基于对 `@vanna/src` 架构思想的分析，结合当前 `mine_agent` 已有骨架，给出可执行的开发顺序、模块任务拆分、验收标准与里程碑建议。

## 1. 当前状态（As-Is）

已完成：

- 核心基础骨架：`core/llm`、`core/tool`、`core/storage`、`engine/orchestrator`。
- 数据源抽象：`capabilities/data_source`（接口、模型、路由）。
- 占位适配器：`integrations/oracle`、`integrations/snowflake`。
- 最小工具：`tools/query_data`。
- 最小示例与单测：`examples/quickstart.py`、`tests/unit/test_orchestrator.py`。

未完成（核心）：

- 真实数据库连接实现（Oracle/Snowflake）。
- SQL 安全策略与权限约束（只读、白名单、风险语句拦截）。
- API 接入层、鉴权授权、审计日志、可观测性、契约测试、集成测试。

## 2. 开发原则（To-Be）

- 契约优先：先定义模型和接口，再写实现。
- 抽象隔离：`engine/tools` 只依赖 `capabilities`，不依赖具体驱动。
- 最小可发布单元：每个阶段都能跑通一条端到端链路。
- 安全默认：数据库默认只读，所有高风险能力必须显式开关。

## 3. 模块级开发任务（按优先级）

## P0（必须先做，决定可用性）

### 3.1 `capabilities/data_source`

目标：

- 将数据源能力稳定为统一契约，作为 Oracle/Snowflake 的共同标准。

任务：

- 补齐 `DataSource` 行为约束文档（输入、输出、异常类型）。
- 增加统一错误模型（如 `DataSourceError`、`AuthError`、`TimeoutError`、`SqlValidationError`）。
- 增加 SQL 校验策略接口（语句类型、schema 白名单、limit 注入策略）。

验收标准：

- 抽象层不出现具体数据库依赖。
- 同一 `QueryRequest` 可被任意数据源适配器消费。

---

### 3.2 `integrations/oracle` 与 `integrations/snowflake`

目标：

- 实现真实连接、查询与元数据能力。

任务：

- Oracle：接入 `oracledb`，实现连接池、超时、`execute_query`、`list_tables`。
- Snowflake：接入 `snowflake-connector-python`，实现会话管理、超时、`execute_query`、`list_tables`。
- 统一异常映射到 `capabilities` 层定义的错误模型。
- 统一结果转换到 `QueryResult`（列、行、行数）。

验收标准：

- 两个适配器均通过同一套 contract tests。
- 查询超时/鉴权失败/语法错误可准确分类并上抛。

---

### 3.3 `tools/query_data`

目标：

- 把数据查询能力稳定暴露给编排器和模型。

任务：

- 增加参数校验：`source_id` 必填、`sql` 非空、`limit` 上限控制。
- 增加执行上下文字段（`trace_id`、`user_id`、`conversation_id`）透传。
- 增加审计数据输出（脱敏 SQL hash、耗时、返回行数）。

验收标准：

- 非法输入在工具层阻断，不进入驱动层。
- 成功与失败输出结构一致，便于上层消费。

---

### 3.4 `engine/orchestrator`

目标：

- 提升主循环可靠性，支持生产场景异常处理。

任务：

- 增加错误处理流程：工具失败、数据源失败、LLM 失败分别处理。
- 增加重试策略（仅对可重试错误，且有次数上限）。
- 增加回合控制（最大工具迭代次数，防止死循环）。
- 增加中断与超时控制。

验收标准：

- 任一外部依赖失败不会导致进程崩溃。
- 主循环有明确退出条件，日志可追踪。

## P1（发布前必须补齐）

### 3.5 `api/`（FastAPI 优先）

目标：

- 提供标准服务入口，支持后续前端/SDK 接入。

任务：

- 定义 `/v1/chat`、`/v1/health`、`/v1/metadata`。
- 加入鉴权中间件（先支持 token，再扩展 SSO）。
- 统一错误码与异常映射。
- 增加请求级 `trace_id` 注入与返回。

验收标准：

- 核心接口具备稳定输入输出模型。
- 错误行为可预测，文档可读。

---

### 3.6 `config/`

目标：

- 规范化多环境配置与密钥注入。

任务：

- 定义环境配置模型：`dev/test/staging/prod`。
- 数据源配置支持多实例（多个 Oracle/Snowflake）。
- 敏感字段走环境变量，禁止明文提交。

验收标准：

- 不改代码即可切换环境。
- 缺失关键配置时启动即失败（fail fast）。

---

### 3.7 `observability/`（建议新增目录）

目标：

- 建立日志、指标、追踪、审计的最小闭环。

任务：

- 结构化日志规范：统一字段名。
- 指标：请求量、成功率、延迟、工具错误率、数据源错误率。
- 审计：用户、数据源、SQL hash、状态、耗时。

验收标准：

- 关键路径日志可复盘一次完整请求。
- 可按 source_id / tool_name 快速定位问题。

## P2（增强项）

### 3.8 `capabilities/memory` 与 `tools` 扩展

目标：

- 支持问答记忆、经验检索、工作流指令。

任务：

- 记忆存储抽象与本地实现。
- 记忆查询工具与写入工具。
- 工作流短路逻辑（如状态查询、帮助命令）。

## 4. 阶段里程碑（建议 4 周）

- Week 1：完成 P0（数据源真实接入 + 主循环可靠性）。
- Week 2：完成 P1（API + 配置 + 鉴权 + 基础审计）。
- Week 3：补齐 contract/integration tests，修复稳定性问题。
- Week 4：压测、灰度、运维手册、发布评审。

## 5. 模块开发顺序（执行建议）

1. `capabilities/data_source`（先定契约）
2. `integrations/oracle` / `integrations/snowflake`（并行实现）
3. `tools/query_data`（统一能力出口）
4. `engine/orchestrator`（补异常与重试）
5. `api/` + `config/` + `observability/`
6. 测试收口与灰度发布

## 6. Definition of Done（统一完成标准）

每个模块合并前需满足：

- 有类型清晰的输入输出模型。
- 有最少单元测试与失败场景测试。
- 有结构化日志关键字段。
- 有文档更新（至少包含用途、依赖、异常行为）。
- 不引入跨层反向依赖（例如 `core` 依赖 `integrations`）。

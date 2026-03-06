# 模块开发与测试手册（Playbook）

本文档定义“每个模块该怎么开发、怎么测、测到什么程度”，用于保证高可用与高维护性目标可落地。

## 1. 测试分层与职责

- `unit`：验证纯逻辑与边界条件，不依赖真实外部系统。
- `contract`：验证不同实现遵守同一抽象接口行为。
- `integration`：验证与真实依赖（Oracle/Snowflake/LLM）的交互。
- `e2e`：验证完整链路（API -> Engine -> Tool -> DataSource）。

## 2. 各模块开发与测试清单

### 2.1 `core/`

开发重点：

- 只放抽象和模型，不放具体实现。
- 明确字段语义、默认值、兼容策略。

必须测试：

- 模型校验（必填、类型、范围）。
- 抽象契约变更的向后兼容性。

通过标准：

- 100% 单测通过；新增字段不破坏现有调用。

---

### 2.2 `engine/`

开发重点：

- 回合控制、错误恢复、重试策略、超时管理。
- 避免无限循环与重复工具调用。

必须测试：

- 正常链路：用户消息 -> 工具调用 -> 回复。
- 异常链路：工具失败、数据源失败、LLM 超时。
- 重试链路：可重试错误被重试，不可重试错误立即失败。
- 幂等链路：同一请求重复提交不产生副作用。

通过标准：

- 核心路径覆盖率 >= 85%。
- 无未处理异常泄漏到 API 层。

---

### 2.3 `capabilities/data_source`

开发重点：

- 定义统一请求/响应/异常。
- 定义 SQL 安全校验策略接口。

必须测试：

- 输入契约完整性（source_id/sql/limit）。
- 异常分类正确性。
- schema 白名单和 SQL 类型限制。

通过标准：

- 不包含具体驱动依赖。
- 所有适配器均可复用同一 contract tests。

---

### 2.4 `integrations/oracle` 与 `integrations/snowflake`

开发重点：

- 连接管理、执行查询、元数据能力、结果映射。
- 驱动异常到统一异常模型的转换。

必须测试：

- 连通性检查成功/失败。
- 查询成功、超时、鉴权失败、语法错误。
- 大结果集 limit 控制。
- 连接池资源释放与并发行为（基础压力测试）。

通过标准：

- contract tests 全通过。
- integration tests 至少覆盖 1 条成功和 3 条失败场景。

---

### 2.5 `tools/`

开发重点：

- 参数校验、调用 capability、统一结果格式。
- 不在 tool 中直连数据库驱动。

必须测试：

- 参数缺失/非法时立即失败。
- capability 异常时能输出可读错误。
- metadata 输出完整（row_count、source_id、耗时）。

通过标准：

- 工具输入输出稳定，便于 LLM 和 API 消费。

---

### 2.6 `api/`

开发重点：

- 协议转换、鉴权、错误映射、trace 注入。

必须测试：

- 鉴权成功/失败。
- 参数校验错误映射为标准错误码。
- 内部异常不暴露堆栈给调用方。

通过标准：

- OpenAPI 文档可生成。
- 关键接口具备集成测试。

## 3. 建议测试用例矩阵（最小集）

- `UNIT-ENG-001`：主循环单工具成功执行。
- `UNIT-ENG-002`：工具抛错后主循环安全退出。
- `UNIT-TOOL-001`：`query_data` 参数校验。
- `CONTRACT-DS-001`：Oracle/Snowflake 对 `DataSource` 行为一致。
- `INT-ORA-001`：Oracle 查询成功。
- `INT-ORA-002`：Oracle 鉴权失败。
- `INT-SF-001`：Snowflake 查询成功。
- `INT-SF-002`：Snowflake 超时失败。
- `E2E-API-001`：`/v1/chat` 完整链路成功。
- `E2E-API-002`：数据源故障时返回可恢复错误。

## 4. CI 门禁建议

- `python -m pytest tests/unit` 必须通过。
- `python -m pytest tests/contract` 必须通过。
- `python -m pytest tests/integration -m smoke` 在合并前通过。
- 核心模块覆盖率阈值（`engine/capabilities/tools`）>= 80%。

## 5. 本地执行建议（tools 环境）

- 激活环境：`eval "$(conda shell.zsh hook)" && conda activate tools`
- 单测：`python -m pytest tests/unit`
- 契约测试：`python -m pytest tests/contract`
- 集成冒烟：`python -m pytest tests/integration -m smoke`

## 6. 开发顺序与测试顺序绑定（强建议）

1. 先写 `core/capabilities` 契约 -> 先写 unit/contract tests。
2. 再写 `integrations` 实现 -> 立即跑 contract/integration tests。
3. 再写 `tools` 与 `engine` -> 跑 unit + e2e smoke。
4. 最后接 `api` -> 跑 e2e + 回归测试。


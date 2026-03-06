# Vanna NL2SQL 核心逻辑总结

本文档总结 vanna 项目中 NL2SQL 的核心实现逻辑，供 mine 项目对齐实现时参考。

---

## 0. 意图识别：何时调用 SQL 工具 vs 直接回答

### 0.1 核心结论

**vanna 不做显式意图分类**，完全依赖 LLM 根据 system prompt 和工具描述自行判断。

| 维度 | vanna | mine |
|------|-------|------|
| 意图分类 | 无，全权交给 LLM | `_looks_like_data_query()` 启发式预分类 |
| tool_choice | 固定 `"auto"` | 数据查询时 `"required"`，否则 `None` |
| 决策主体 | LLM | 系统预分类 + LLM |

### 0.2 vanna 的实现方式

1. **LLM 请求固定 `tool_choice: "auto"`**

   - 所有请求都传 `tool_choice: "auto"`（见 `openai/llm.py`、`anthropic/llm.py`、`azureopenai/llm.py`）
   - 由 LLM 决定：是否调用工具、调用哪个工具

2. **意图识别完全由 system prompt + 工具 schema 引导**

   - System prompt 说明：「Use the available tools to help the user accomplish their goals」
   - 工具 schema 中有 `run_sql` 的描述：「Execute SQL queries against the configured database」
   - LLM 根据用户问题和工具描述，自行判断是否需要执行 SQL、是否调用 run_sql

3. **WorkflowHandler 只处理命令**（`DefaultWorkflowHandler.try_handle`）

   - `/help`、`/status`、`/memories`、`/delete` 等为固定命令，直接处理，不经过 LLM
   - 其他所有用户输入都交给 LLM，由 LLM 决定是直接回答（如「你好」）还是调用工具（如「查一下销售额」）

4. **无显式「数据查询 vs 非数据查询」分类**

   - 代码中无 `_looks_like_data_query`、`looks_like_data_query`、`data_query`、`intent` 等关键词
   - 所有用户输入（除上述命令外）都走同一套 LLM 流程，由 LLM 决定是否调用工具

### 0.3 mine 的当前实现

- `Orchestrator._looks_like_data_query(message)`：基于关键词启发式判断
- 若为数据查询：`tool_choice="required"` 强制调用工具
- 否则：`tool_choice=None`，LLM 可选择是否调用

### 0.4 对齐建议

若希望与 vanna 对齐：

- **方案 A**：移除 `_looks_like_data_query`，统一使用 `tool_choice="auto"`，由 LLM 自行判断
- **方案 B**：保留启发式作为「加速」手段，对明显数据查询用 `required`，对模糊情况用 `auto`，但需接受与 vanna 行为不完全一致

---

## 1. 两种实现路径

vanna 提供两种 NL2SQL 实现方式：

| 路径 | 入口 | 适用场景 |
|------|------|----------|
| **Legacy RAG** | `VannaBase.generate_sql()` | 单轮生成，无工具调用 |
| **Agent + 工具链** | `Agent.send_message()` → `run_sql` 工具 | 多轮对话，支持工具调用 |

---

## 2. Legacy RAG 流程（`VannaBase`）

**核心文件**: `vanna/src/vanna/legacy/base/base.py`

### 2.1 主流程 `generate_sql(question)`

```
1. get_similar_question_sql(question)  → 相似 Q&A（问题-SQL 对）
2. get_related_ddl(question)          → 相关 DDL（表结构）
3. get_related_documentation(question) → 相关文档（领域知识）
4. get_sql_prompt(...)                 → 组装 prompt
5. submit_prompt(prompt)                → 调用 LLM
6. extract_sql(llm_response)           → 从 LLM 文本中抽取 SQL
```

### 2.2 检索层（向量存储）

以 ChromaDB 为例（`chromadb_vector.py`）：

- **sql 集合**: 存储 `{question, sql}` 的 JSON，按问题语义检索相似示例
- **ddl 集合**: 存储 DDL 文本，按问题语义检索相关表结构
- **documentation 集合**: 存储领域文档，按问题语义检索

### 2.3 Prompt 组装 `get_sql_prompt()`

```
initial_prompt (或默认 "You are a {dialect} expert...")
  + add_ddl_to_prompt(ddl_list)        → "===Tables \n" + DDL
  + add_documentation_to_prompt(doc_list) → "===Additional Context \n" + 文档
  + "===Response Guidelines \n"       → 6 条规则（只生成 SQL、中间 SQL、上下文不足时说明等）
  + 多轮 few-shot: [user: question, assistant: sql] × N
  + 最后一条 user: 当前 question
```

### 2.4 SQL 抽取 `extract_sql()`

按优先级匹配：

1. `CREATE TABLE ... AS SELECT ... ;`
2. `WITH ... ;`（CTE）
3. `SELECT ... ;`
4. ` ```sql ... ``` ` 代码块
5. ` ``` ... ``` ` 通用代码块

### 2.5 中间 SQL 支持

若 LLM 返回含 `intermediate_sql` 的注释，且 `allow_llm_to_see_data=True`：

- 执行中间 SQL，将结果 DataFrame 转为 markdown 追加到 doc_list
- 再次调用 `get_sql_prompt` + `submit_prompt` 生成最终 SQL

---

## 3. Agent + 工具链流程（新版）

**核心文件**: `vanna/src/vanna/core/agent/agent.py`

### 3.1 主循环

```
while tool_iterations < max_tool_iterations:
  1. 构建 LLM 请求（含 tools、system_prompt、conversation）
  2. 调用 llm_service.send_request()
  3. 若 response.tool_calls 为空 → 结束，返回 assistant 文本
  4. 否则执行每个 tool_call，将结果追加到 messages
  5. 继续下一轮
```

### 3.2 上下文增强 `DefaultLlmContextEnhancer`

**文件**: `vanna/src/vanna/core/enhancer/default.py`

- 在每次 LLM 调用前，根据 **用户首条消息** 调用 `agent_memory.search_text_memories(query=user_message, limit=5)`
- 将检索到的文本记忆拼接到 system prompt 末尾：`"## Relevant Context from Memory\n\n" + 记忆内容`

### 3.3 系统提示 `DefaultSystemPromptBuilder`

**文件**: `vanna/src/vanna/core/system_prompt/default.py`

- 基础角色：`"You are Vanna, an AI data analyst assistant..."`
- 若存在 memory 工具，追加 **MEMORY SYSTEM** 说明：
  - **search_saved_correct_tool_uses**: 执行任何工具前必须先调用，检索相似问题的成功模式
  - **save_question_tool_args**: 工具执行成功后必须调用，保存成功模式
  - **save_text_memory**: 保存 schema、领域知识、术语等文本记忆

### 3.4 `run_sql` 工具

**文件**: `vanna/src/vanna/tools/run_sql.py`

- 参数：`RunSqlToolArgs(sql: str)`
- 通过注入的 `SqlRunner` 执行 SQL
- 返回：结果文本 + UI 组件（DataFrameComponent / NotificationComponent）
- SELECT 结果可写入 CSV 供 `visualize_data` 使用

---

## 4. 关键能力对照

| 能力 | vanna 实现 | mine 现状 |
|------|------------|-----------|
| SQL 生成 | LLM + RAG 上下文 | LLM，无 RAG |
| 相似 Q&A 检索 | ChromaDB sql 集合 | 无 |
| DDL/表结构检索 | ChromaDB ddl 集合 | 无 |
| 领域文档检索 | ChromaDB documentation 集合 | 无 |
| 上下文增强 | DefaultLlmContextEnhancer | 无 |
| Memory 工具 | search/save_question_tool_args, save_text_memory | 无 |
| SQL 执行工具 | run_sql | query_data（已有） |

---

## 5. mine 对齐建议

### 5.1 最小可行（MVP）

1. **LlmContextEnhancer 接口**：在 system prompt 中注入上下文
2. **SchemaProvider**：从数据源获取表/列信息（DDL 或 schema 描述）
3. **DefaultLlmContextEnhancer**：根据用户问题 + 默认 source_id，注入相关 schema 到 system prompt

### 5.2 进阶（可选）

4. **向量存储**：实现 question_sql、ddl、documentation 的检索（类似 Legacy RAG）
5. **AgentMemory**：实现 search_saved_correct_tool_uses、save_question_tool_args、save_text_memory
6. **System prompt 对齐**：引入 MEMORY SYSTEM 工作流说明

### 5.3 数据流示意

```
用户问题
  → LlmContextEnhancer.enhance_system_prompt(system_prompt, user_message)
      → SchemaProvider.get_schema_for_question(source_id, question)  [或 向量检索]
      → 拼接 "## Relevant Context\n\n" + schema/DDL/文档
  → Orchestrator 构建 LlmRequest(system_prompt=enhanced_prompt, ...)
  → LLM 返回 tool_calls(query_data, sql=...)
  → QueryDataTool 执行 SQL，返回结果
  → 下一轮或结束
```

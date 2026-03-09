# Knowledge Workflow 流程说明

## 概述

知识库工作流为 **Schema-Aware NL2SQL** 提供元数据：表结构、表间关系、Join 路径等。Chat 对话时根据用户问题做语义检索，将相关 schema 注入 prompt，帮助 LLM 生成准确 SQL。

## 步骤详解

### 1. 连接配置

配置数据库连接（Oracle、Snowflake 等）。抽取 Schema 时使用这些连接执行 SQL 读取元数据。

---

### 2. Schema 抽取

- **执行抽取**：从选中的连接中读取表、列、类型等基础 schema（如 `information_schema` 或厂商元数据表）。
- **异步增强**：LLM 根据表名、列名推断：
  - **join_paths**：表间 JOIN 路径（如 `employees.dept_id -> departments.id`）及自然语言描述；
  - **er_graph**：ER 图节点（表）和边（外键关系）。
- 抽取结果暂存在任务中，完成后跳转到 ER 图页。

---

### 3. ER 图 / Join

| 作用 | 说明 |
|------|------|
| **来源** | 由 Schema 抽取 + 异步增强生成的 `join_paths`、`er_graph` |
| **展示** | 以 ER 图形式可视化表与表之间的关联（节点=表，边=外键关系） |
| **可编辑** | 可补充表描述、修正/增删 join 路径、调整 er_graph 节点位置 |
| **保存** | 保存到 `~/.mine/knowledge/{source_id}.json` |

ER 图和 JSON 编辑页操作同一份知识库，前者可视化编辑，后者原始 JSON 编辑。

---

### 4. JSON 编辑

| 作用 | 说明 |
|------|------|
| **编辑对象** | 知识库 JSON：`tables`、`join_paths`、`domains`、`er_graph` |
| **适用场景** | 高级用户批量修改、脚本导入、或 ER 图无法覆盖的精细调整 |
| **与 ER 页关系** | 同一份数据，两种编辑方式；保存后两边都会看到最新内容 |

---

### 5. 向量化

| 作用 | 说明 |
|------|------|
| **向量化内容** | 将知识库 JSON 切分为 chunk，每块做 embedding，存入 VectorStore |
| **具体包括** | 见下表 |
| **用途** | Chat 时根据用户问题做语义检索，将检索到的 schema 片段注入 prompt |

#### 向量化的 chunk 类型

| 类型 | 来源 | 示例 |
|------|------|------|
| 表信息 | `tables` | `Table: employees. 员工表. Columns: id(number), name(varchar2), dept_id(number)` |
| 分组/域 | `er_graph.nodes[].group` | `Domain: Order Management. Tables: orders, order_items.` |
| Join 路径 | `join_paths` | `employees.dept_id 关联 departments.id，表示部门归属` |
| ER 边 | `er_graph.edges`（未在 join_paths 中重复的） | `employees dept_id -> departments id` |

**重要**：首次选择 embedding 模型后，该知识源会锁定该模型，不可更改，以保证向量空间一致性。

---

## 流程串联

```
连接配置 → Schema 抽取（含异步增强）→ ER 图 / Join（可视化编辑）→ JSON 编辑（可选，精细调整）
                                                                       ↓
                                                       保存知识库 → 向量化 → Chat 问答（RAG 检索）
```

## 参考

- [0002-knowledge-to-chat-bridge](../adr/0002-knowledge-to-chat-bridge.md)
- [architecture-diagram.md](./architecture-diagram.md)

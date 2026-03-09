# RAG 置信门控实现指南

本文档说明如何在当前项目中实现并上线「置信门控（Confidence Gating）」，用于降低因检索上下文不足导致的错误 SQL。

---

## 1. 要解决的问题

当前链路已经支持：

- 混合检索（召回 + 配额重排 + 图扩展）
- 结构化 Schema Context 输出
- `MINE_RAG_CONFIDENCE_GUARD_ENABLED` 开关（目前仅预留，尚未生效）

但仍缺少「检索质量 -> 生成策略」的闭环，即：

- 检索质量低时，系统仍可能按正常路径让 LLM 生成复杂 SQL
- 缺少量化的 `high/medium/low` 置信级别
- 缺少低置信度场景下的显式约束与澄清策略

---

## 2. 设计目标

1. 用可解释指标计算检索置信度  
2. 根据置信度分级调整 prompt 约束  
3. 保持向后兼容，开关可灰度与回滚  
4. 提供可观测日志，便于评估门控收益

---

## 3. 接入位置（当前代码）

- 检索与上下文组装：`src/mine_agent/api/fastapi/knowledge_context.py`
- Prompt 注入：`src/mine_agent/engine/orchestrator.py`
- 开关来源：`src/mine_agent/api/fastapi/knowledge_context.py` 中环境变量读取

建议将置信门控逻辑全部放在 `knowledge_context.py`，`orchestrator.py` 无需新增复杂逻辑，继续只消费 `schema_context` 字符串。

---

## 4. 置信度评分模型（推荐 v1）

## 4.1 输入信号

从现有流程可直接得到以下信号：

- `top1_score`：候选最高相似度（来自 `search_with_score`）
- `avg_topk_score`：前 K 个候选平均分
- `table_count`：命中的 table chunk 数
- `join_count`：命中的 join/er_edge chunk 数
- `has_graph_expansion`：是否发生图扩展补齐
- `context_len`：最终上下文长度（字符）

## 4.2 归一化与总分

建议总分范围 `[0, 1]`：

```
confidence_score =
  0.35 * score_signal
  + 0.35 * coverage_signal
  + 0.20 * join_signal
  + 0.10 * stability_signal
```

推荐定义：

- `score_signal = clamp((top1_score + avg_topk_score) / 2, 0, 1)`
- `coverage_signal = clamp(table_count / 3, 0, 1)`
- `join_signal = clamp(join_count / 2, 0, 1)`
- `stability_signal = 1.0 if context_len >= 300 else context_len / 300`

> 说明：v1 用启发式足够，后续可通过离线评测再调权重。

## 4.3 分级阈值

- `HIGH`: `confidence_score >= 0.75`
- `MEDIUM`: `0.45 <= confidence_score < 0.75`
- `LOW`: `confidence_score < 0.45`

---

## 5. 门控策略（分级动作）

## 5.1 HIGH

- 正常输出结构化 Schema Context
- `SQL Constraints` 保持常规约束

## 5.2 MEDIUM

- 保持结构化输出
- 在 `SQL Constraints` 增加一条保守约束：
  - 「优先使用已确认 join 路径，避免推测不存在的字段」

## 5.3 LOW

- 开启低置信度护栏（`low_confidence=True`）
- 在 `SQL Constraints` 强制加入：
  - 「仅使用已确认表与列」
  - 「若关键关系不明确，先请求用户澄清」

---

## 6. 详细实现步骤

## 步骤 1：新增评分函数

文件：`src/mine_agent/api/fastapi/knowledge_context.py`

建议新增：

- `_compute_confidence_score(...) -> float`
- `_confidence_level(score: float) -> str`

入参使用现有变量，不新增跨模块依赖。

## 步骤 2：在检索后计算置信度

位置：`build_chat_knowledge_context()` 中，完成 `final_snippets/final_infos` 后、格式化前。

关键点：

- 从 `candidates` 中拿 `top1_score/avg_topk_score`
- 结合 `table_count/join_count/context_len` 计算分数
- 仅在 `MINE_RAG_CONFIDENCE_GUARD_ENABLED=true` 时启用门控

## 步骤 3：驱动结构化格式化

现有 `_format_structured_schema_context(..., low_confidence=False)` 已支持低置信标志。  
将 `low_confidence` 改为：

- `low_confidence = (confidence_level == "LOW")`

同时可按 `MEDIUM` 添加一条温和约束（可通过新增参数或在格式化前拼接）。

## 步骤 4：增强日志

在 `logger.info("build_chat_knowledge_context", extra=...)` 中新增：

- `confidence_score`
- `confidence_level`
- `top1_score`
- `avg_topk_score`
- `confidence_guard_enabled`

## 步骤 5：可选透出调试信息

若后续需要前端可见，可在 debug 路由或内部诊断里输出置信度。  
生产默认不回传给终端用户，避免增加心智负担。

---

## 7. 环境变量建议

在 `rag-config-and-flags.md` 追加：

- `MINE_RAG_CONFIDENCE_HIGH_THRESHOLD`（默认 `0.75`）
- `MINE_RAG_CONFIDENCE_LOW_THRESHOLD`（默认 `0.45`）
- `MINE_RAG_CONFIDENCE_GUARD_ENABLED`（已存在，默认 `true`）

这样可无需改代码直接调节门控敏感度。

---

## 8. 测试方案（必须覆盖）

文件：`tests/unit/test_knowledge_context.py`

新增测试建议：

1. **高置信度路径**
   - 高分候选 + 足够 table/join
   - 断言 `low_confidence` 约束未出现

2. **低置信度路径**
   - 低相似度 + table/join 覆盖不足
   - 断言 `SQL Constraints` 中出现「仅使用已确认表」与「必要时先澄清」

3. **开关关闭兼容**
   - `MINE_RAG_CONFIDENCE_GUARD_ENABLED=false`
   - 断言行为与当前版本一致（不触发门控文案）

4. **阈值可配置**
   - 调整 high/low 阈值，验证分级变化符合预期

5. **日志字段校验（可选）**
   - 捕获日志，断言 `confidence_score/confidence_level` 出现

---

## 9. 灰度发布与回滚

## 灰度建议

1. 先在测试环境开启：`MINE_RAG_CONFIDENCE_GUARD_ENABLED=true`
2. 观察 1-2 天日志：
   - LOW 占比
   - LOW 场景 SQL 执行失败率变化
3. 若 LOW 占比过高，先降低阈值敏感度再全量

## 回滚

- 快速回滚：`MINE_RAG_CONFIDENCE_GUARD_ENABLED=false`
- 不影响检索主链路，只关闭门控动作

---

## 10. 验收标准（DoD）

满足以下条件视为置信门控落地完成：

1. 低置信度场景能稳定触发约束文案
2. 开关关闭后行为与当前版本一致
3. 单测覆盖高/中/低三档路径
4. 日志可观测到 `confidence_score/confidence_level`
5. 在评测集上，低置信度样本的高风险错误 SQL 率下降

---

## 11. 推荐落地顺序（1-2 天）

1. 实现评分函数 + 分级阈值（半天）
2. 接入 `_format_structured_schema_context` 的 low_confidence（半天）
3. 增加日志与单测（半天）
4. 联调与灰度验证（半天）

该方案不要求改 Orchestrator 的主循环，不改变现有 API 协议，风险低、可快速上线验证。

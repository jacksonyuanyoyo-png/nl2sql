# Chat Trace Visibility 测试报告模板

**报告日期**：YYYY-MM-DD  
**版本/分支**：  
**环境**：dev / staging / prod

---

## 1. 概述

| 项目 | 说明 |
|------|------|
| 测试范围 | Chat Trace Visibility：retrieval_trace、llm_rounds、tool_results、API trace 字段 |
| 验收标准 | 单测通过、API 响应含 trace、SSE 含 debug、无回归 |

---

## 2. 覆盖场景

### 2.1 build_chat_knowledge_context

| 用例名 | 场景 | 预期 |
|--------|------|------|
| `test_build_chat_knowledge_context_from_vector_hits` | 向量检索命中 | 返回 ChatContextResult，retrieval_trace 含 retrieved_chunks、table_count、join_count |
| `test_build_chat_knowledge_context_fallback_without_vector` | 无向量 fallback | 返回 ChatContextResult，retrieval_trace 有结构 |
| `test_hybrid_flow_expands_join_tables` | hybrid 模式 expand join | prompt_context 含双侧表 |
| `test_hybrid_disabled_keeps_old_behavior` | hybrid 关闭 | 保持旧 vector search 行为 |

### 2.2 orchestrator.chat

| 用例名 | 场景 | 预期 |
|--------|------|------|
| `test_orchestrator_executes_query_tool` | 执行 query_data | 返回 assistant_content、tool_outputs、llm_rounds、tool_results |

### 2.3 POST /v1/chat

| 用例名 | 场景 | 预期 |
|--------|------|------|
| `test_chat_smoke` | 正常请求 | 200，含 assistant_content、tool_outputs、trace_id，可选 trace |
| `test_chat_v1_returns_trace_field_when_source_id_provided` | 带 metadata.source_id | 200，trace 含 retrieval |

### 2.4 POST /api/vanna/v2/chat_sse

| 用例名 | 场景 | 预期 |
|--------|------|------|
| `test_legacy_chat_sse_endpoint` | 正常 SSE 请求 | 200，data 行含 JSON，可含 debug（retrieval、llm_rounds、tool_results） |

---

## 3. 单测结果

| 测试模块 | 通过 | 失败 | 跳过 | 总计 |
|----------|------|------|------|------|
| test_knowledge_context | | | | |
| test_orchestrator | | | | |
| test_api_fastapi | | | | |

**失败用例说明**（如有）：

| 用例名 | 失败原因 |
|--------|----------|
| | |

---

## 4. 回归检查项

- [ ] 无 source_id 时 Chat 仍可正常返回
- [ ] trace 为 null 时前端不报错
- [ ] X-Trace-Id 请求头正确回传
- [ ] chat_poll 响应含 trace（若有 retrieval）
- [ ] chat_sse chunk 含 debug 时结构正确

---

## 5. 可复现验证步骤

```bash
# 1. 运行 unit 测试
cd mine
python3 -m pytest tests/unit/test_knowledge_context.py tests/unit/test_orchestrator.py tests/unit/test_api_fastapi.py -v

# 2. 验证 /v1/chat trace
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: manual-trace-1" \
  -d '{"conversation_id":"v","user_message":"hi","metadata":{"source_id":"oracle_demo"}}'

# 3. 验证 chat_sse debug（若实现）
curl -X POST http://localhost:8000/api/vanna/v2/chat_sse \
  -H "Content-Type: application/json" \
  -d '{"message":"SELECT 1 FROM dual","conversation_id":"v","request_id":"r","metadata":{}}'
```

---

## 6. 结论

- [ ] 所有覆盖场景通过
- [ ] 存在已知问题（见失败用例说明）
- [ ] 需回归项：___________

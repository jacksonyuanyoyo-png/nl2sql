from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from mine_agent.api.fastapi.knowledge_context import (
    ChatContextResult,
    KnowledgeChunk,
    _expand_by_graph,
    _format_structured_schema_context,
    _rerank_with_quota,
    build_chat_knowledge_context,
    build_knowledge_chunks,
    build_schema_fallback_context,
)
from mine_agent.api.fastapi.knowledge_store import save_knowledge
from mine_agent.core.embedding.base import EmbeddingService
from mine_agent.integrations.vector.inmemory import InMemoryVectorStore

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "knowledge"


class FixedEmbeddingService(EmbeddingService):
    def embed(self, texts: List[str]) -> List[List[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.mark.asyncio
async def test_build_chat_knowledge_context_from_vector_hits(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MINE_CONFIG_DIR", str(tmp_path))
    source_id = "hr_demo"
    save_knowledge(
        source_id,
        {
            "tables": [
                {
                    "name": "employees",
                    "columns": [{"name": "employee_id", "type": "NUMBER"}],
                }
            ],
            "join_paths": [{"description": "employees.department_id -> departments.department_id"}],
        },
    )

    chunks = build_knowledge_chunks(
        {
            "tables": [
                {
                    "name": "employees",
                    "columns": [{"name": "employee_id", "type": "NUMBER"}],
                }
            ],
            "join_paths": [{"description": "employees.department_id -> departments.department_id"}],
        }
    )
    store = InMemoryVectorStore()
    for chunk_id, text in chunks:
        store.add(
            namespace=f"knowledge:{source_id}",
            id=chunk_id,
            vector=[0.1, 0.2, 0.3],
            metadata={"text": text, "source_id": source_id},
        )

    result = await build_chat_knowledge_context(
        source_id=source_id,
        user_message="查员工和部门",
        embedding_service=FixedEmbeddingService(),
        vector_store=store,
        top_k=3,
    )
    assert "Schema Context" in result.prompt_context
    assert "employees" in result.prompt_context
    assert isinstance(result, ChatContextResult)
    trace = result.retrieval_trace
    assert "prompt_context" in trace
    assert "retrieved_chunks" in trace
    assert "table_count" in trace
    assert "join_count" in trace
    for ch in trace["retrieved_chunks"]:
        assert "chunk_id" in ch
        assert "chunk_type" in ch
        assert "text" in ch
        assert "table_refs" in ch
        assert "column_refs" in ch


@pytest.mark.asyncio
async def test_build_chat_knowledge_context_fallback_without_vector(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MINE_CONFIG_DIR", str(tmp_path))
    source_id = "sales_demo"
    save_knowledge(
        source_id,
        {
            "tables": [
                {
                    "name": "orders",
                    "columns": [{"name": "order_id", "type": "NUMBER"}],
                }
            ]
        },
    )

    result = await build_chat_knowledge_context(
        source_id=source_id,
        user_message="查订单",
        embedding_service=None,
        vector_store=None,
        top_k=3,
    )
    assert isinstance(result, ChatContextResult)
    assert "Schema Context" in result.prompt_context
    assert "orders" in result.prompt_context
    assert "retrieved_chunks" in result.retrieval_trace


@pytest.mark.asyncio
async def test_hybrid_flow_expands_join_tables(monkeypatch, tmp_path) -> None:
    """MINE_RAG_HYBRID_ENABLED=true 时，命中 join 应补齐两侧表 chunk（如查各部门人数包含 employees、departments）。"""
    monkeypatch.setenv("MINE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MINE_RAG_HYBRID_ENABLED", "true")
    source_id = "hr_dept"
    data = {
        "tables": [
            {"name": "employees", "columns": [{"name": "employee_id", "type": "NUMBER"}, {"name": "dept_id", "type": "NUMBER"}]},
            {"name": "departments", "columns": [{"name": "id", "type": "NUMBER"}, {"name": "name", "type": "VARCHAR2"}]},
        ],
        "join_paths": [
            {
                "description": "employees.dept_id 关联 departments.id，表示部门归属",
                "from": {"table": "employees", "column": "dept_id"},
                "to": {"table": "departments", "column": "id"},
            }
        ],
    }
    save_knowledge(source_id, data)

    chunks = build_knowledge_chunks(data)
    chunk_by_id = {cid: text for cid, text in chunks}
    store = InMemoryVectorStore()
    for chunk_id, text in chunks:
        store.add(
            namespace=f"knowledge:{source_id}",
            id=chunk_id,
            vector=[0.1, 0.2, 0.3],
            metadata={"text": text, "source_id": source_id},
        )

    result = await build_chat_knowledge_context(
        source_id=source_id,
        user_message="查各部门人数",
        embedding_service=FixedEmbeddingService(),
        vector_store=store,
        top_k=8,
    )
    assert isinstance(result, ChatContextResult)
    assert "Schema Context" in result.prompt_context
    assert "employees" in result.prompt_context
    assert "departments" in result.prompt_context


def test_build_knowledge_chunks_includes_metadata_chunk_type_and_table_refs() -> None:
    """验收：build_knowledge_chunks 返回的 chunk metadata 包含 chunk_type 和 table_refs。"""
    data = {
        "tables": [
            {"name": "orders", "columns": [{"name": "order_id", "type": "NUMBER"}, {"name": "customer_id", "type": "NUMBER"}]},
        ],
        "join_paths": [
            {
                "description": "orders.customer_id -> customers.id",
                "from": {"table": "orders", "column": "customer_id"},
                "to": {"table": "customers", "column": "id"},
            }
        ],
        "er_graph": {
            "nodes": [{"table": "orders", "group": "Sales"}, {"table": "customers", "group": "Sales"}],
            "edges": [],
        },
    }
    chunks = build_knowledge_chunks(data)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert isinstance(chunk, KnowledgeChunk)
        assert "chunk_type" in chunk.metadata
        assert "table_refs" in chunk.metadata
        assert chunk.metadata["chunk_type"] in ("table", "domain", "join", "er_edge", "summary")
    table_chunk = next(c for c in chunks if c.metadata["chunk_type"] == "table")
    assert table_chunk.metadata["table_refs"] == ["orders"]
    join_chunk = next(c for c in chunks if c.metadata["chunk_type"] == "join")
    assert set(join_chunk.metadata["table_refs"]) == {"orders", "customers"}


def test_rerank_with_quota_ensures_min_tables_and_min_joins() -> None:
    """验证 _rerank_with_quota 至少包含 min_tables 个 table 和 min_joins 个 join。"""
    candidates = [
        ("table:employees", {"text": "Table: employees"}, 0.9),
        ("table:departments", {"text": "Table: departments"}, 0.8),
        ("join:0", {"text": "employees.dept_id -> departments.id"}, 0.85),
        ("join:1", {"text": "orders.cust_id -> customers.id"}, 0.7),
        ("domain:HR", {"text": "Domain: HR"}, 0.6),
    ]
    chunk_by_id = {c[0]: c[1]["text"] for c in candidates}
    selected = _rerank_with_quota(
        candidates, chunk_by_id, min_tables=2, min_joins=2, max_domain_ratio=0.3
    )
    table_ids = [s for s in selected if s.startswith("table:")]
    join_ids = [s for s in selected if s.startswith("join:")]
    assert len(table_ids) >= 2, f"至少应有 2 个 table，实际: {table_ids}"
    assert len(join_ids) >= 2, f"至少应有 2 个 join，实际: {join_ids}"


def test_search_with_score_returns_score(monkeypatch, tmp_path) -> None:
    """InMemoryVectorStore.search_with_score 应返回 (id, meta, score)。"""
    store = InMemoryVectorStore()
    store.add("ns", "id1", [1.0, 0.0, 0.0], {"x": 1})
    store.add("ns", "id2", [0.0, 1.0, 0.0], {"x": 2})
    results = store.search_with_score("ns", [1.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    assert results[0][0] == "id1"
    assert results[0][2] > results[1][2]


def test_expand_by_graph_adds_join_tables() -> None:
    """_expand_by_graph 命中 join 时应补齐两侧表 chunk。"""
    selected_ids = ["join:0"]
    data = {
        "tables": [
            {"name": "employees", "columns": []},
            {"name": "departments", "columns": []},
        ],
        "join_paths": [
            {
                "from": {"table": "employees", "column": "department_id"},
                "to": {"table": "departments", "column": "department_id"},
                "description": "employees.department_id -> departments.department_id",
            }
        ],
    }
    chunks = build_knowledge_chunks(data)
    chunk_by_id = {cid: text for cid, text in chunks}
    expanded = _expand_by_graph(selected_ids, chunk_by_id, data)
    assert "table:employees" in expanded, f"join 左侧表 employees 应被补齐，实际: {expanded}"
    assert "table:departments" in expanded, f"join 右侧表 departments 应被补齐，实际: {expanded}"


@pytest.mark.asyncio
async def test_hybrid_disabled_keeps_old_behavior(monkeypatch, tmp_path) -> None:
    """MINE_RAG_HYBRID_ENABLED=false 时保持旧行为：使用简单 vector search，不用 quota/expand。"""
    monkeypatch.setenv("MINE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MINE_RAG_HYBRID_ENABLED", "false")
    source_id = "simple_demo"
    save_knowledge(
        source_id,
        {
            "tables": [{"name": "orders", "columns": [{"name": "order_id", "type": "NUMBER"}]}],
            "join_paths": [],
        },
    )
    chunks = build_knowledge_chunks(
        {"tables": [{"name": "orders", "columns": []}], "join_paths": []}
    )
    store = InMemoryVectorStore()
    for chunk_id, text in chunks:
        store.add(
            namespace=f"knowledge:{source_id}",
            id=chunk_id,
            vector=[0.1, 0.2, 0.3],
            metadata={"text": text, "source_id": source_id},
        )

    result = await build_chat_knowledge_context(
        source_id=source_id,
        user_message="查订单",
        embedding_service=FixedEmbeddingService(),
        vector_store=store,
        top_k=5,
    )
    assert isinstance(result, ChatContextResult)
    assert "Schema Context" in result.prompt_context
    assert "orders" in result.prompt_context


def test_format_structured_schema_context_output() -> None:
    """验证 _format_structured_schema_context 输出包含 Candidate Tables、Recommended Join Paths。"""
    snippets = [
        "Table: employees. Columns: employee_id(NUMBER), name(VARCHAR2)",
        "employees.department_id -> departments.department_id，部门归属",
        "Table: departments. Columns: department_id(NUMBER), name(VARCHAR2)",
    ]
    chunk_infos = [
        {"chunk_id": "table:employees"},
        {"chunk_id": "join:0"},
        {"chunk_id": "table:departments"},
    ]
    result = _format_structured_schema_context(snippets, chunk_infos=chunk_infos)
    assert "## Candidate Tables" in result
    assert "## Recommended Join Paths" in result
    assert "employees" in result
    assert "departments" in result


def test_hr_demo_fixture_loaded(monkeypatch, tmp_path) -> None:
    """使用 tests/fixtures/knowledge/hr_demo.json 验证知识库结构。"""
    fixture_path = FIXTURES_DIR / "hr_demo.json"
    if not fixture_path.exists():
        pytest.skip(f"Fixture not found: {fixture_path}")
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)
    assert "tables" in data
    assert "join_paths" in data
    table_names = [t["name"] for t in data["tables"]]
    assert "employees" in table_names
    assert "departments" in table_names
    assert len(data["join_paths"]) >= 1
    j = data["join_paths"][0]
    assert "from" in j and "to" in j
    assert j["from"].get("table") in ("employees", "departments")
    assert j["to"].get("table") in ("employees", "departments")

    # 保存到 tmp 并调用 build_chat 验证能正常使用
    monkeypatch.setenv("MINE_CONFIG_DIR", str(tmp_path))
    save_knowledge("hr_demo", data)
    fallback = build_schema_fallback_context(data)
    assert "employees" in fallback
    assert "departments" in fallback

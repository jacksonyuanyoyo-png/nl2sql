from __future__ import annotations

from typing import List

import pytest

from mine_agent.api.fastapi.knowledge_context import (
    build_chat_knowledge_context,
    build_knowledge_chunks,
)
from mine_agent.api.fastapi.knowledge_store import save_knowledge
from mine_agent.core.embedding.base import EmbeddingService
from mine_agent.integrations.vector.inmemory import InMemoryVectorStore


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

    context = await build_chat_knowledge_context(
        source_id=source_id,
        user_message="查员工和部门",
        embedding_service=FixedEmbeddingService(),
        vector_store=store,
        top_k=3,
    )
    assert "Schema Context" in context
    assert "employees" in context


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

    context = await build_chat_knowledge_context(
        source_id=source_id,
        user_message="查订单",
        embedding_service=None,
        vector_store=None,
        top_k=3,
    )
    assert "Schema Context" in context
    assert "orders" in context

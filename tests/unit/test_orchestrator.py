from __future__ import annotations

from unittest.mock import patch

import pytest

from mine_agent.capabilities.data_source.router import DataSourceRouter
from mine_agent.core.tool.registry import ToolRegistry
from mine_agent.engine.orchestrator import Orchestrator
from mine_agent.integrations.local.storage import InMemoryConversationStore
from mine_agent.integrations.mock.llm import MockLlmService
from mine_agent.integrations.oracle.client import OracleDataSource
from mine_agent.tools.query_data import QueryDataTool


@pytest.mark.asyncio
async def test_orchestrator_executes_query_tool() -> None:
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"):
        router = DataSourceRouter()
        router.register(
            OracleDataSource(
                source_id="oracle_demo",
                connection_options={"dsn": "oracle-host:1521/ORCL"},
            )
        )

        registry = ToolRegistry()
        registry.register(QueryDataTool(router=router))

        orchestrator = Orchestrator(
            llm_service=MockLlmService(),
            tool_registry=registry,
            conversation_store=InMemoryConversationStore(),
        )

        result = await orchestrator.chat(
            conversation_id="test-conv",
            user_message="SELECT 1 FROM dual",
            user_id="tester",
        )
    assert "assistant_content" in result
    assert len(result["tool_outputs"]) == 1
    assert "llm_rounds" in result
    assert "tool_results" in result
    assert len(result["llm_rounds"]) >= 1
    assert any(r["is_final"] for r in result["llm_rounds"])
    assert len(result["tool_results"]) == 1
    tr = result["tool_results"][0]
    assert tr["tool_name"] == "query_data"
    assert "arguments" in tr
    assert "content" in tr
    assert "metadata_summary" in tr
    assert "error" in tr

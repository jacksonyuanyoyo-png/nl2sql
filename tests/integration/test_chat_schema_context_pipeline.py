"""集成测试：Chat 流程中 schema_context 被正确注入到 system prompt。"""

from __future__ import annotations

from typing import AsyncGenerator, List
from unittest.mock import patch

from fastapi.testclient import TestClient

from mine_agent.api.fastapi import create_app
from mine_agent.api.fastapi.knowledge_store import save_knowledge
from mine_agent.capabilities.data_source.router import DataSourceRouter
from mine_agent.config.settings import AppSettings
from mine_agent.core.llm.base import LlmService
from mine_agent.core.llm.models import (
    LlmRequest,
    LlmResponse,
    LlmStreamChunk,
    ToolSchema,
)
from mine_agent.core.tool.registry import ToolRegistry
from mine_agent.engine.orchestrator import Orchestrator
from mine_agent.integrations.local.storage import InMemoryConversationStore
from mine_agent.integrations.oracle.client import OracleDataSource
from mine_agent.tools.query_data import QueryDataTool


class SchemaContextCapturingLlmService(LlmService):
    """Mock LLM 服务：捕获最后一次请求的 system_prompt，用于断言 schema_context 注入。"""

    def __init__(self) -> None:
        self.last_system_prompt: str | None = None

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self.last_system_prompt = request.system_prompt
        return LlmResponse(content="测试完成。", finish_reason="stop")

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        self.last_system_prompt = request.system_prompt
        response = await self.send_request(request=request)
        if response.content:
            yield LlmStreamChunk(content=response.content)
        yield LlmStreamChunk(finish_reason=response.finish_reason)

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return []


def test_chat_schema_context_injected_when_source_id_provided(
    monkeypatch, tmp_path
) -> None:
    """验证：当请求带 source_id 且有知识库时，schema_context 被注入到 system prompt。"""
    monkeypatch.setenv("MINE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MINE_RAG_HYBRID_ENABLED", "false")

    source_id = "hr_demo"
    save_knowledge(
        source_id,
        {
            "tables": [
                {"name": "employees", "columns": [{"name": "id", "type": "NUMBER"}]},
                {"name": "departments", "columns": [{"name": "id", "type": "NUMBER"}]},
            ],
            "join_paths": [
                {
                    "from": {"table": "employees", "column": "dept_id"},
                    "to": {"table": "departments", "column": "id"},
                    "description": "employees.dept_id -> departments.id",
                }
            ],
        },
    )

    from mine_agent.integrations import oracle

    with patch.object(oracle.client, "_ensure_driver"):
        router = DataSourceRouter()
        router.register(
            OracleDataSource(
                source_id=source_id,
                connection_options={"dsn": "oracle-host:1521/ORCL"},
            )
        )
        registry = ToolRegistry()
        registry.register(QueryDataTool(router=router))
        capturing_llm = SchemaContextCapturingLlmService()
        orchestrator = Orchestrator(
            llm_service=capturing_llm,
            tool_registry=registry,
            conversation_store=InMemoryConversationStore(),
        )
        app = create_app(
            orchestrator=orchestrator,
            settings=AppSettings(api_auth_enabled=False),
            router=router,
        )
        client = TestClient(app)

    resp = client.post(
        "/v1/chat",
        json={
            "conversation_id": "schema-pipeline-test",
            "user_message": "查一下员工人数",
            "metadata": {"source_id": source_id},
        },
    )
    assert resp.status_code == 200
    assert capturing_llm.last_system_prompt is not None
    assert "Schema Context" in capturing_llm.last_system_prompt
    assert "employees" in capturing_llm.last_system_prompt or "departments" in capturing_llm.last_system_prompt

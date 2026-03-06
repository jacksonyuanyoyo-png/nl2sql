"""E2E tests for POST /v1/chat full chain: auth, chat flow, tool failure resilience."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from mine_agent.api.fastapi import create_app
from mine_agent.capabilities.data_source.router import DataSourceRouter
from mine_agent.config.settings import AppSettings
from mine_agent.core.tool.registry import ToolRegistry
from mine_agent.engine.orchestrator import Orchestrator, TOOL_ERROR_PREFIX
from mine_agent.integrations.local.storage import InMemoryConversationStore
from mine_agent.integrations.mock.llm import MockLlmService
from mine_agent.integrations.oracle.client import OracleDataSource
from mine_agent.tools.query_data import QueryDataTool

from tests.e2e.helpers import FailingTool, ToolCallLlmService


def _make_chat_app_with_orchestrator(
    auth_enabled: bool = True,
    api_tokens: list[str] | None = None,
) -> tuple[TestClient, Orchestrator | None]:
    """Create app with full orchestrator (Oracle + QueryDataTool + MockLlm)."""
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
        app = create_app(
            orchestrator=orchestrator,
            settings=AppSettings(
                api_auth_enabled=auth_enabled,
                api_tokens=api_tokens or ["token-1"],
            ),
        )
        return TestClient(app), orchestrator


def test_e2e_auth_success_chat_returns_ok() -> None:
    """鉴权成功 + chat 正常返回：完整链路通过。"""
    client, _ = _make_chat_app_with_orchestrator(auth_enabled=True, api_tokens=["token-1"])
    resp = client.post(
        "/v1/chat",
        headers={"Authorization": "Bearer token-1", "X-Trace-Id": "e2e-trace-1"},
        json={
            "conversation_id": "e2e-conv-1",
            "user_message": "SELECT 1 FROM dual",
            "user_id": "e2e-user",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "assistant_content" in data
    assert "tool_outputs" in data
    assert isinstance(data["tool_outputs"], list)
    assert resp.headers.get("X-Trace-Id") == "e2e-trace-1"


def test_e2e_auth_failure_401_no_header() -> None:
    """鉴权失败：无 Authorization 返回 401。"""
    client, _ = _make_chat_app_with_orchestrator(auth_enabled=True, api_tokens=["token-1"])
    resp = client.post(
        "/v1/chat",
        json={
            "conversation_id": "e2e-conv-2",
            "user_message": "hello",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHORIZED"


def test_e2e_auth_failure_403_invalid_token() -> None:
    """鉴权失败：无效 token 返回 403。"""
    client, _ = _make_chat_app_with_orchestrator(auth_enabled=True, api_tokens=["token-1"])
    resp = client.post(
        "/v1/chat",
        headers={"Authorization": "Bearer wrong-token"},
        json={
            "conversation_id": "e2e-conv-3",
            "user_message": "hello",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"


def test_e2e_tool_failure_returns_structured_response() -> None:
    """工具执行失败时系统仍返回结构化响应，不崩溃。"""
    registry = ToolRegistry()
    registry.register(FailingTool())
    orchestrator = Orchestrator(
        llm_service=ToolCallLlmService(tool_name="failing_tool", max_returns=1),
        tool_registry=registry,
        conversation_store=InMemoryConversationStore(),
    )
    app = create_app(
        orchestrator=orchestrator,
        settings=AppSettings(api_auth_enabled=False),
    )
    client = TestClient(app)

    resp = client.post(
        "/v1/chat",
        json={
            "conversation_id": "e2e-conv-tool-fail",
            "user_message": "trigger tool",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "assistant_content" in data
    assert "tool_outputs" in data
    assert len(data["tool_outputs"]) >= 1
    assert TOOL_ERROR_PREFIX in data["tool_outputs"][0]
    assert "ValueError" in data["tool_outputs"][0]
    assert "Intentional tool failure" in data["tool_outputs"][0]

"""Unit tests for FastAPI minimal API layer."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mine_agent.api.fastapi import create_app
from mine_agent.capabilities.data_source.router import DataSourceRouter
from mine_agent.config.settings import AppSettings
from mine_agent.core.tool.registry import ToolRegistry
from mine_agent.engine.orchestrator import Orchestrator
from mine_agent.integrations.local.storage import InMemoryConversationStore
from mine_agent.integrations.mock.llm import MockLlmService
from mine_agent.integrations.oracle.client import OracleDataSource
from mine_agent.tools.query_data import QueryDataTool


@pytest.fixture(autouse=True)
def clear_openai_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


def test_health() -> None:
    """GET /v1/health returns status ok."""
    app = create_app(orchestrator=None)
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metadata_without_router() -> None:
    """GET /v1/metadata returns base info when no router/dynamic connections."""
    from mine_agent.api.fastapi import app as app_module

    with patch.object(app_module, "load_connections", return_value=[]):
        app = create_app(
        orchestrator=None,
        settings=AppSettings(
            service_name="mine-agent",
            service_version="0.1.0",
            environment="dev",
            api_auth_enabled=False,
        ),
        )
        client = TestClient(app)
        resp = client.get("/v1/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service_name"] == "mine-agent"
        assert data["service_version"] == "0.1.0"
        assert data["environment"] == "dev"
        assert data["auth_enabled"] is False
        assert data["registered_data_sources"] == []
        assert data["data_source_health"] == {}


def test_metadata_with_router() -> None:
    """GET /v1/metadata returns data source info when router is configured."""
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"):
        router = DataSourceRouter()
        router.register(
            OracleDataSource(
                source_id="oracle_demo",
                connection_options={"dsn": "oracle-host:1521/ORCL"},
            )
        )
        app = create_app(
            orchestrator=None,
            settings=AppSettings(
                service_name="mine-agent",
                service_version="0.1.0",
                environment="prod",
                api_auth_enabled=True,
            ),
            router=router,
        )
        client = TestClient(app)
        resp = client.get("/v1/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service_name"] == "mine-agent"
        assert data["service_version"] == "0.1.0"
        assert data["environment"] == "prod"
        assert data["auth_enabled"] is True
        assert data["registered_data_sources"] == ["oracle_demo"]
        assert "oracle_demo" in data["data_source_health"]
        assert isinstance(data["data_source_health"]["oracle_demo"], bool)


def test_chat_unauthorized_when_auth_enabled() -> None:
    app = create_app(
        orchestrator=None,
        settings=AppSettings(api_auth_enabled=True, api_tokens=["token-1"]),
    )
    client = TestClient(app)
    resp = client.post(
        "/v1/chat",
        json={
            "conversation_id": "test-conv",
            "user_message": "SELECT 1 FROM dual",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHORIZED"


def test_chat_forbidden_with_invalid_token() -> None:
    app = create_app(
        orchestrator=None,
        settings=AppSettings(api_auth_enabled=True, api_tokens=["token-1"]),
    )
    client = TestClient(app)
    resp = client.post(
        "/v1/chat",
        headers={"Authorization": "Bearer wrong"},
        json={
            "conversation_id": "test-conv",
            "user_message": "SELECT 1 FROM dual",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"


def test_chat_orchestrator_missing_returns_503() -> None:
    app = create_app(
        orchestrator=None,
        settings=AppSettings(api_auth_enabled=True, api_tokens=["token-1"]),
    )
    client = TestClient(app)
    resp = client.post(
        "/v1/chat",
        headers={"Authorization": "Bearer token-1"},
        json={
            "conversation_id": "test-conv",
            "user_message": "SELECT 1 FROM dual",
        },
    )
    assert resp.status_code == 503
    assert resp.json()["error_code"] == "ORCHESTRATOR_NOT_CONFIGURED"


def test_chat_smoke() -> None:
    """POST /v1/chat calls orchestrator.chat and returns ChatResponse."""
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
        settings=AppSettings(api_auth_enabled=True, api_tokens=["token-1"]),
    )
    client = TestClient(app)

    resp = client.post(
        "/v1/chat",
        headers={
            "Authorization": "Bearer token-1",
            "X-Trace-Id": "trace-test-1",
        },
        json={
            "conversation_id": "test-conv",
            "user_message": "SELECT 1 FROM dual",
            "user_id": "tester",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "assistant_content" in data
    assert "tool_outputs" in data
    assert isinstance(data["tool_outputs"], list)
    assert resp.headers["X-Trace-Id"] == "trace-test-1"


def test_create_app_auto_injects_orchestrator_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"oracle_demo","source_type":"oracle","options":{"user":"hr","password":"hr","host":"localhost","port":1521,"service_name":"XE"}}]',
    )
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"), patch.object(
        oracle_client,
        "_execute_query_sync",
        return_value=oracle_client.QueryResult(
            columns=["value"], rows=[{"value": 1}], row_count=1
        ),
    ):
        app = create_app(
            orchestrator=None,
            settings=AppSettings(api_auth_enabled=False),
            router=None,
        )
        client = TestClient(app)
        resp = client.post(
            "/v1/chat",
            json={
                "conversation_id": "auto-conv",
                "user_message": "SELECT 1 FROM dual",
                "user_id": "tester",
            },
        )
    assert resp.status_code == 200
    assert "assistant_content" in resp.json()


def test_create_app_prefers_openai_llm_when_api_key_present(monkeypatch) -> None:
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"oracle_demo","source_type":"oracle","options":{"user":"hr","password":"hr","host":"localhost","port":1521,"service_name":"XE"}}]',
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"), patch.object(
        oracle_client,
        "_execute_query_sync",
        return_value=oracle_client.QueryResult(
            columns=["value"], rows=[{"value": 1}], row_count=1
        ),
    ), patch("mine_agent.api.fastapi.app.OpenAILlmService") as mocked_llm:
        mocked_instance = MockLlmService(default_source_id="oracle_demo")
        mocked_llm.return_value = mocked_instance
        app = create_app(
            orchestrator=None,
            settings=AppSettings(api_auth_enabled=False),
            router=None,
        )
        client = TestClient(app)
        resp = client.post(
            "/v1/chat",
            json={
                "conversation_id": "auto-openai-conv",
                "user_message": "SELECT 1 FROM dual",
                "user_id": "tester",
            },
        )
    assert resp.status_code == 200
    assert mocked_llm.called


def test_legacy_health_endpoint() -> None:
    app = create_app(orchestrator=None)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_legacy_chat_poll_endpoint(monkeypatch) -> None:
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"oracle_demo","source_type":"oracle","options":{"user":"hr","password":"hr","host":"localhost","port":1521,"service_name":"XE"}}]',
    )
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"), patch.object(
        oracle_client,
        "_execute_query_sync",
        return_value=oracle_client.QueryResult(
            columns=["value"], rows=[{"value": 1}], row_count=1
        ),
    ):
        app = create_app(
            orchestrator=None,
            settings=AppSettings(api_auth_enabled=False),
            router=None,
        )
        client = TestClient(app)
        resp = client.post(
            "/api/vanna/v2/chat_poll",
            json={
                "message": "SELECT 1 FROM dual",
                "conversation_id": "legacy-conv",
                "request_id": "legacy-req",
                "metadata": {},
            },
        )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["conversation_id"] == "legacy-conv"
    assert payload["request_id"] == "legacy-req"
    assert isinstance(payload["chunks"], list)
    assert payload["chunks"][0]["simple"]["type"] == "text"


def test_legacy_chat_sse_endpoint(monkeypatch) -> None:
    monkeypatch.setenv(
        "MINE_DATASOURCES",
        '[{"source_id":"oracle_demo","source_type":"oracle","options":{"user":"hr","password":"hr","host":"localhost","port":1521,"service_name":"XE"}}]',
    )
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"), patch.object(
        oracle_client,
        "_execute_query_sync",
        return_value=oracle_client.QueryResult(
            columns=["value"], rows=[{"value": 1}], row_count=1
        ),
    ):
        app = create_app(
            orchestrator=None,
            settings=AppSettings(api_auth_enabled=False),
            router=None,
        )
        client = TestClient(app)
        resp = client.post(
            "/api/vanna/v2/chat_sse",
            json={
                "message": "SELECT 1 FROM dual",
                "conversation_id": "legacy-conv",
                "request_id": "legacy-req",
                "metadata": {},
            },
        )
    assert resp.status_code == 200
    assert "data: " in resp.text
    assert "[DONE]" in resp.text

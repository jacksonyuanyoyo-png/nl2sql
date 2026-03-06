"""Unit tests for knowledge and datasource config API routes."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi.testclient import TestClient

from mine_agent.api.fastapi.app import create_app
from mine_agent.api.fastapi.enrich_jobs import (
    _build_er_graph,
    infer_join_paths_with_llm,
)


@pytest.fixture
def config_dir(tmp_path):
    with patch.dict(os.environ, {"MINE_CONFIG_DIR": str(tmp_path)}):
        yield tmp_path


@pytest.fixture
def app_without_embedding():
    return create_app(
        orchestrator=None,
        settings=None,
        router=None,
    )


@pytest.fixture
def client(app_without_embedding, config_dir):
    return TestClient(app_without_embedding)


def test_datasources_config_list_empty(client, config_dir) -> None:
    with patch.dict(os.environ, {"MINE_CONFIG_DIR": str(config_dir)}):
        resp = client.get("/v1/datasources/config")
    assert resp.status_code == 200
    assert resp.json() == []


def test_datasources_config_create_and_list(client, config_dir) -> None:
    body = {
        "source_id": "test_ora",
        "source_type": "oracle",
        "options": {
            "user": "u",
            "password": "p",
            "host": "localhost",
            "port": 1521,
            "service_name": "XE",
        },
    }
    with patch.dict(os.environ, {"MINE_CONFIG_DIR": str(config_dir)}):
        resp = client.post("/v1/datasources/config", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_id"] == "test_ora"
        assert "id" in data
        resp2 = client.get("/v1/datasources/config")
    assert resp2.status_code == 200
    assert len(resp2.json()) >= 1


def test_datasources_config_delete(client, config_dir) -> None:
    body = {
        "source_id": "del_me",
        "source_type": "oracle",
        "options": {"user": "u", "password": "p", "host": "h", "port": 1521, "service_name": "XE"},
    }
    with patch.dict(os.environ, {"MINE_CONFIG_DIR": str(config_dir)}):
        create = client.post("/v1/datasources/config", json=body)
        cid = create.json()["id"]
        resp = client.delete(f"/v1/datasources/config/{cid}")
        assert resp.status_code == 200
        resp2 = client.get("/v1/datasources/config")
    ids = [c["id"] for c in resp2.json()]
    assert cid not in ids


def test_knowledge_get_404(client) -> None:
    resp = client.get("/v1/knowledge/nonexistent_source")
    assert resp.status_code == 404


def test_knowledge_put_and_get(client, config_dir) -> None:
    with patch.dict(os.environ, {"MINE_CONFIG_DIR": str(config_dir)}):
        body = {"tables": [{"name": "t1", "columns": []}], "join_paths": [], "domains": []}
        resp = client.put("/v1/knowledge/my_source", json=body)
        assert resp.status_code == 200
        resp2 = client.get("/v1/knowledge/my_source")
        assert resp2.status_code == 200
        assert resp2.json()["tables"][0]["name"] == "t1"


def test_vectorize_returns_501_without_embedding(client, config_dir) -> None:
    with patch.dict(os.environ, {"MINE_CONFIG_DIR": str(config_dir)}):
        client.put("/v1/knowledge/vec_source", json={"tables": [], "join_paths": []})
        resp = client.post(
            "/v1/knowledge/vec_source/vectorize",
            json={"embedding_vendor": "deepseek"},
        )
    assert resp.status_code == 501


def test_enrich_async_404_when_connection_missing(client) -> None:
    resp = client.post(
        "/v1/knowledge/schema/enrich/async",
        json={
            "connection_id": "nonexistent-uuid",
            "source_id": "test",
            "persist": False,
        },
    )
    assert resp.status_code == 404
    data = resp.json()
    assert "Connection not found" in (data.get("message") or data.get("detail", ""))


def test_enrich_async_creates_job_and_poll_succeeds(client, config_dir) -> None:
    body = {
        "source_id": "enrich_test",
        "source_type": "oracle",
        "options": {"user": "u", "password": "p", "host": "h", "port": 1521, "service_name": "XE"},
    }
    mock_result = {
        "tables": [
            {"name": "A", "columns": [{"name": "id", "type": "number"}]},
            {"name": "B", "columns": [{"name": "id", "type": "number"}, {"name": "a_id", "type": "number"}]},
        ]
    }

    with patch.dict(os.environ, {"MINE_CONFIG_DIR": str(config_dir)}):
        create_resp = client.post("/v1/datasources/config", json=body)
        assert create_resp.status_code == 200
        cid = create_resp.json()["id"]

        with patch(
            "mine_agent.api.fastapi.knowledge_routes._do_schema_extract",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            enrich_resp = client.post(
                "/v1/knowledge/schema/enrich/async",
                json={"connection_id": cid, "source_id": "enrich_test", "persist": True},
            )
        assert enrich_resp.status_code == 200
        data = enrich_resp.json()
        assert "job_id" in data
        job_id = data["job_id"]

        for _ in range(20):
            job_resp = client.get(f"/v1/knowledge/jobs/{job_id}")
            assert job_resp.status_code == 200
            j = job_resp.json()
            if j["status"] == "succeeded":
                assert "result" in j
                res = j["result"]
                assert "tables" in res
                assert "join_paths" in res
                assert "er_graph" in res
                assert len(res["tables"]) == 2
                break
            if j["status"] == "failed":
                pytest.fail(f"Job failed: {j.get('error')}")
        else:
            pytest.fail("Job did not complete within expected time")


@pytest.mark.asyncio
async def test_infer_join_paths_with_llm_parses_and_builds_er_graph() -> None:
    """LLM returns fixed JSON; infer_join_paths_with_llm parses it and _build_er_graph accepts it."""
    tables = [
        {"name": "ORDERS", "columns": [{"name": "ORDER_ID", "type": "NUMBER"}, {"name": "CUSTOMER_ID", "type": "NUMBER"}]},
        {"name": "CUSTOMERS", "columns": [{"name": "ID", "type": "NUMBER"}, {"name": "NAME", "type": "VARCHAR2"}]},
    ]
    llm_json = '[{"from_table": "ORDERS", "from_column": "CUSTOMER_ID", "to_table": "CUSTOMERS", "to_column": "ID"}]'
    mock_llm = MagicMock()
    mock_llm.send_request = AsyncMock(
        return_value=MagicMock(content=llm_json)
    )
    join_paths = await infer_join_paths_with_llm(tables, mock_llm)
    assert len(join_paths) == 1
    assert join_paths[0]["from"]["table"] == "ORDERS"
    assert join_paths[0]["from"]["column"] == "CUSTOMER_ID"
    assert join_paths[0]["to"]["table"] == "CUSTOMERS"
    assert join_paths[0]["to"]["column"] == "ID"
    assert join_paths[0].get("evidence") == "llm"
    er_graph = _build_er_graph(tables, join_paths)
    assert len(er_graph["nodes"]) == 2
    assert len(er_graph["edges"]) == 1
    assert er_graph["edges"][0]["source"] == "ORDERS" and er_graph["edges"][0]["target"] == "CUSTOMERS"


def test_job_status_404(client) -> None:
    resp = client.get("/v1/knowledge/jobs/nonexistent-job-id")
    assert resp.status_code == 404


def test_knowledge_put_with_er_graph(client, config_dir) -> None:
    with patch.dict(os.environ, {"MINE_CONFIG_DIR": str(config_dir)}):
        body = {
            "tables": [{"name": "T1", "columns": []}],
            "join_paths": [],
            "er_graph": {
                "nodes": [{"id": "T1", "table": "T1"}],
                "edges": [],
            },
        }
        resp = client.put("/v1/knowledge/er_source", json=body)
        assert resp.status_code == 200
        resp2 = client.get("/v1/knowledge/er_source")
        assert resp2.status_code == 200
        assert resp2.json()["er_graph"]["nodes"][0]["table"] == "T1"

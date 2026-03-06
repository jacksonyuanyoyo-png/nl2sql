"""
DataSource 契约测试基线。

验证所有 DataSource 实现满足统一接口契约：
- source_id 属性
- test_connection 返回 bool
- execute_query 返回 QueryResult 结构
- list_tables 返回 list[str]

默认使用轻量 stub adapter，无需真实驱动/数据库。
预留参数化接入 Oracle/Snowflake 真实 adapter 的结构。
"""

from __future__ import annotations

from typing import List
from unittest.mock import patch

import pytest

from mine_agent.capabilities.data_source.base import DataSource
from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult


# ---------------------------------------------------------------------------
# 契约测试用 Stub Adapter（轻量、无依赖）
# ---------------------------------------------------------------------------


class ContractStubDataSource(DataSource):
    """
    契约测试专用 stub adapter。
    不依赖任何数据库驱动，用于验证契约基线。
    """

    def __init__(self, source_id: str = "contract-stub") -> None:
        self._source_id = source_id

    @property
    def source_id(self) -> str:
        return self._source_id

    async def test_connection(self) -> bool:
        return True

    async def execute_query(self, request: QueryRequest) -> QueryResult:
        return QueryResult(
            columns=["col"],
            rows=[{"col": "stub"}],
            row_count=1,
        )

    async def list_tables(self, schema: str | None = None) -> List[str]:
        return ["stub_table_1", "stub_table_2"]

    async def get_columns(self, schema: str | None, table: str) -> List[tuple]:
        return [("col1", "VARCHAR2"), ("col2", "NUMBER")]


# ---------------------------------------------------------------------------
# 参数化 Adapter Fixture（默认 stub，可扩展 Oracle/Snowflake）
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=[
        "stub",
        "oracle",
        "snowflake",
    ],
    ids=["stub", "oracle", "snowflake"],
)
def datasource_adapter(request: pytest.FixtureRequest) -> DataSource:
    """
    参数化 fixture：提供满足契约的 DataSource 实现。
    - stub: 轻量 ContractStubDataSource，无依赖
    - oracle: OracleDataSource（mock 驱动，无真实 DB）
    - snowflake: SnowflakeDataSource（mock 驱动，无真实 DB）
    扩展真实 adapter：在此增加新 param，并实现对应分支。
    """
    adapter_id: str = request.param
    if adapter_id == "stub":
        yield ContractStubDataSource()
        return

    if adapter_id == "oracle":
        from mine_agent.integrations.oracle import client as oracle_client
        from mine_agent.integrations.oracle.client import OracleDataSource

        def fake_execute(_opts: object, sql: str) -> QueryResult:
            return QueryResult(columns=["c1"], rows=[{"c1": 1}], row_count=1)

        def fake_list(_opts: object, schema: str | None) -> list[str]:
            return ["T1", "T2"]

        def fake_get_columns(_opts: object, schema: str | None, table: str) -> list[tuple]:
            return [("col1", "VARCHAR2"), ("col2", "NUMBER")]

        with patch.object(oracle_client, "_ensure_driver"):
            with patch.object(oracle_client, "_execute_query_sync", side_effect=fake_execute):
                with patch.object(oracle_client, "_list_tables_sync", side_effect=fake_list):
                    with patch.object(oracle_client, "_get_columns_sync", side_effect=fake_get_columns):
                        with patch.object(oracle_client, "_test_connection_sync", return_value=True):
                            yield OracleDataSource(source_id="ora-contract", connection_options={})
        return

    if adapter_id == "snowflake":
        from mine_agent.integrations.snowflake import client as snowflake_client
        from mine_agent.integrations.snowflake.client import SnowflakeDataSource

        with patch.object(snowflake_client, "_ensure_driver"):
            yield SnowflakeDataSource(source_id="sf-contract", connection_options={})
        return

    raise ValueError(f"Unknown adapter: {adapter_id}")


# ---------------------------------------------------------------------------
# 契约测试用例
# ---------------------------------------------------------------------------


class TestDataSourceContract:
    """
    DataSource 契约测试基线。
    所有 DataSource 实现必须通过此类测试。
    """

    @pytest.mark.asyncio
    async def test_source_id_attribute(self, datasource_adapter: DataSource) -> None:
        """契约：source_id 为可读属性，返回非空 str。"""
        sid = datasource_adapter.source_id
        assert isinstance(sid, str), "source_id must be str"
        assert len(sid) > 0, "source_id must be non-empty"

    @pytest.mark.asyncio
    async def test_test_connection_returns_bool(self, datasource_adapter: DataSource) -> None:
        """契约：test_connection 返回 bool。"""
        result = await datasource_adapter.test_connection()
        assert isinstance(result, bool), "test_connection must return bool"

    @pytest.mark.asyncio
    async def test_execute_query_returns_query_result(self, datasource_adapter: DataSource) -> None:
        """契约：execute_query 返回 QueryResult 结构。"""
        req = QueryRequest(source_id=datasource_adapter.source_id, sql="SELECT 1", limit=10)
        result = await datasource_adapter.execute_query(req)
        assert isinstance(result, QueryResult), "execute_query must return QueryResult"
        assert isinstance(result.columns, list), "QueryResult.columns must be list"
        assert isinstance(result.rows, list), "QueryResult.rows must be list"
        assert isinstance(result.row_count, int), "QueryResult.row_count must be int"
        assert result.row_count == len(result.rows), "row_count must match rows length"
        if result.rows:
            assert isinstance(result.rows[0], dict), "rows elements must be dict"

    @pytest.mark.asyncio
    async def test_list_tables_returns_list_of_str(self, datasource_adapter: DataSource) -> None:
        """契约：list_tables 返回 list[str]。"""
        tables = await datasource_adapter.list_tables(schema=None)
        assert isinstance(tables, list), "list_tables must return list"
        assert all(isinstance(t, str) for t in tables), "list_tables elements must be str"

    @pytest.mark.asyncio
    async def test_list_tables_accepts_schema_param(self, datasource_adapter: DataSource) -> None:
        """契约：list_tables 接受 schema 参数（可为 None）。"""
        tables = await datasource_adapter.list_tables(schema="SCHEMA_NAME")
        assert isinstance(tables, list), "list_tables(schema=...) must return list"
        assert all(isinstance(t, str) for t in tables), "elements must be str"

    @pytest.mark.asyncio
    async def test_get_columns_returns_list_of_tuples(self, datasource_adapter: DataSource) -> None:
        """契约：get_columns 返回 (name, type) 元组列表。"""
        tables = await datasource_adapter.list_tables(schema=None)
        if not tables:
            pytest.skip("no tables to test get_columns")
        cols = await datasource_adapter.get_columns(schema=None, table=tables[0])
        assert isinstance(cols, list), "get_columns must return list"
        assert all(isinstance(c, (list, tuple)) and len(c) >= 2 for c in cols), "elements must be (name, type)"

    @pytest.mark.asyncio
    async def test_get_columns_accepts_schema_and_table(self, datasource_adapter: DataSource) -> None:
        """契约：get_columns 接受 schema 和 table 参数。"""
        tables = await datasource_adapter.list_tables(schema=None)
        if not tables:
            pytest.skip("no tables")
        cols = await datasource_adapter.get_columns(schema="SCHEMA_NAME", table=tables[0])
        assert isinstance(cols, list), "get_columns(schema=..., table=...) must return list"

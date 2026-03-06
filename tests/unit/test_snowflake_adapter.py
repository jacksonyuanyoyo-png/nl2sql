"""
Unit tests for Snowflake data source adapter.
"""

from __future__ import annotations

import builtins
from unittest.mock import patch

import pytest

from mine_agent.capabilities.data_source.errors import SqlValidationError
from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult
from mine_agent.integrations.snowflake.client import (
    SnowflakeDataSource,
    SnowflakeDriverNotFoundError,
)

_ORIGINAL_IMPORT = builtins.__import__


def _mock_import_no_snowflake(name: str, *args: object, **kwargs: object) -> object:
    """Simulate missing snowflake.connector driver."""
    if name == "snowflake.connector":
        raise ImportError("No module named 'snowflake.connector'")
    return _ORIGINAL_IMPORT(name, *args, **kwargs)


@pytest.fixture
def no_snowflake() -> None:
    """Fixture to simulate snowflake.connector not installed."""
    with patch.object(builtins, "__import__", side_effect=_mock_import_no_snowflake):
        yield


@pytest.mark.asyncio
async def test_test_connection_raises_readable_error_when_no_driver(
    no_snowflake: None,
) -> None:
    """When snowflake.connector is not installed, test_connection raises SnowflakeDriverNotFoundError."""
    ds = SnowflakeDataSource(source_id="sf1", connection_options={})
    with pytest.raises(SnowflakeDriverNotFoundError) as exc_info:
        await ds.test_connection()
    assert "snowflake" in str(exc_info.value).lower()
    assert "pip install" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_execute_query_raises_readable_error_when_no_driver(
    no_snowflake: None,
) -> None:
    """When snowflake.connector is not installed, execute_query raises SnowflakeDriverNotFoundError."""
    ds = SnowflakeDataSource(source_id="sf1", connection_options={})
    req = QueryRequest(source_id="sf1", sql="SELECT 1", limit=10)
    with pytest.raises(SnowflakeDriverNotFoundError) as exc_info:
        await ds.execute_query(req)
    assert "snowflake" in str(exc_info.value).lower()
    assert "pip install" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_list_tables_raises_readable_error_when_no_driver(
    no_snowflake: None,
) -> None:
    """When snowflake.connector is not installed, list_tables raises SnowflakeDriverNotFoundError."""
    ds = SnowflakeDataSource(source_id="sf1", connection_options={})
    with pytest.raises(SnowflakeDriverNotFoundError):
        await ds.list_tables(schema="PUBLIC")


@pytest.mark.asyncio
async def test_execute_query_placeholder_returns_expected_type() -> None:
    """Placeholder path returns QueryResult with correct structure."""
    from mine_agent.integrations.snowflake import client as snowflake_client

    with patch.object(snowflake_client, "_ensure_driver"):
        ds = SnowflakeDataSource(source_id="sf1", connection_options={})
        req = QueryRequest(source_id="sf1", sql="SELECT 1", limit=100)
        result = await ds.execute_query(req)
    assert isinstance(result, QueryResult)
    assert isinstance(result.columns, list)
    assert isinstance(result.rows, list)
    assert isinstance(result.row_count, int)
    assert result.columns == ["status"]
    assert len(result.rows) == 1
    assert result.rows[0]["status"] == "snowflake placeholder"
    assert result.row_count == 1


@pytest.mark.asyncio
async def test_list_tables_placeholder_returns_list_of_str() -> None:
    """Placeholder path returns List[str]."""
    from mine_agent.integrations.snowflake import client as snowflake_client

    with patch.object(snowflake_client, "_ensure_driver"):
        ds = SnowflakeDataSource(source_id="sf1", connection_options={})
        tables = await ds.list_tables(schema=None)
    assert isinstance(tables, list)
    assert all(isinstance(t, str) for t in tables)
    assert tables == []


@pytest.mark.asyncio
async def test_source_id_property() -> None:
    """DataSource interface: source_id returns configured value."""
    ds = SnowflakeDataSource(source_id="my_snowflake", connection_options={})
    assert ds.source_id == "my_snowflake"


# --- SQL Guard integration ---


@pytest.mark.asyncio
async def test_execute_query_write_sql_raises_sql_validation_error() -> None:
    """Write operations (INSERT/UPDATE/DELETE/etc) are blocked by SQL Guard."""
    from mine_agent.integrations.snowflake import client as snowflake_client

    with patch.object(snowflake_client, "_ensure_driver"):
        ds = SnowflakeDataSource(source_id="sf1", connection_options={})
        for bad_sql in [
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET x = 1",
            "DELETE FROM t",
            "DROP TABLE t",
        ]:
            req = QueryRequest(source_id="sf1", sql=bad_sql, limit=10)
            with pytest.raises(SqlValidationError, match="Forbidden keyword"):
                await ds.execute_query(req)


@pytest.mark.asyncio
async def test_execute_query_forbidden_schema_raises_sql_validation_error() -> None:
    """Non-whitelisted schema is blocked when allowed_schemas is set."""
    from mine_agent.integrations.snowflake import client as snowflake_client

    with patch.object(snowflake_client, "_ensure_driver"):
        ds = SnowflakeDataSource(
            source_id="sf1",
            connection_options={"allowed_schemas": ["PUBLIC", "ANALYTICS"]},
        )
        req = QueryRequest(
            source_id="sf1",
            sql="SELECT * FROM forbidden.t",
            limit=10,
        )
        with pytest.raises(SqlValidationError, match="Schema not allowed: FORBIDDEN"):
            await ds.execute_query(req)


@pytest.mark.asyncio
async def test_execute_query_allowed_schema_passes() -> None:
    """When allowed_schemas is set and schema matches, query proceeds."""
    from mine_agent.integrations.snowflake import client as snowflake_client

    with patch.object(snowflake_client, "_ensure_driver"):
        ds = SnowflakeDataSource(
            source_id="sf1",
            connection_options={"allowed_schemas": ["PUBLIC", "ANALYTICS"]},
        )
        req = QueryRequest(
            source_id="sf1",
            sql="SELECT * FROM public.t",
            limit=10,
        )
        result = await ds.execute_query(req)
    assert result.row_count == 1
    assert result.rows[0]["status"] == "snowflake placeholder"


@pytest.mark.asyncio
async def test_execute_query_allowed_schemas_none_skips_validation() -> None:
    """When allowed_schemas is None, schema validation is skipped."""
    from mine_agent.integrations.snowflake import client as snowflake_client

    with patch.object(snowflake_client, "_ensure_driver"):
        ds = SnowflakeDataSource(source_id="sf1", connection_options={})
        req = QueryRequest(
            source_id="sf1",
            sql="SELECT * FROM any_schema.any_table",
            limit=10,
        )
        result = await ds.execute_query(req)
    assert result.row_count == 1

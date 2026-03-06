"""
Oracle integration tests.

Smoke tests against local Docker Oracle when env vars are set.
Skips when oracledb or env is missing (CI-friendly).
"""

from __future__ import annotations

import pytest

from mine_agent.capabilities.data_source.models import QueryRequest


@pytest.mark.asyncio
async def test_connection(oracle_data_source) -> None:
    """Verify OracleDataSource.test_connection succeeds when Oracle is reachable."""
    result = await oracle_data_source.test_connection()
    assert result is True


@pytest.mark.asyncio
async def test_execute_query_select_one(oracle_data_source) -> None:
    """Execute SELECT 1 FROM dual and assert QueryResult structure."""
    req = QueryRequest(
        source_id=oracle_data_source.source_id,
        sql="SELECT 1 FROM dual",
        limit=10,
    )
    result = await oracle_data_source.execute_query(req)
    assert result.columns is not None
    assert isinstance(result.columns, list)
    assert isinstance(result.rows, list)
    assert isinstance(result.row_count, int)
    assert result.row_count >= 1
    assert len(result.rows) >= 1


@pytest.mark.asyncio
async def test_list_tables(oracle_data_source) -> None:
    """list_tables returns a list (schema may be empty)."""
    tables = await oracle_data_source.list_tables()
    assert isinstance(tables, list)
    assert all(isinstance(t, str) for t in tables)

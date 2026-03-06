"""Unit tests for QueryDataTool."""

from __future__ import annotations

from typing import List
from unittest.mock import patch

import pytest

from mine_agent.capabilities.data_source.base import DataSource
from mine_agent.capabilities.data_source.errors import (
    DataSourceExecutionError,
    UnknownDataSourceError,
)
from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult
from mine_agent.capabilities.data_source.router import DataSourceRouter
from mine_agent.core.tool.models import ToolContext
from mine_agent.tools.query_data import LIMIT_MAX, LIMIT_MIN, QueryDataTool


class FakeDataSource(DataSource):
    """Fake data source for testing."""

    def __init__(
        self,
        source_id: str,
        *,
        raise_error: Exception | None = None,
    ) -> None:
        self._source_id = source_id
        self._raise_error = raise_error

    @property
    def source_id(self) -> str:
        return self._source_id

    async def test_connection(self) -> bool:
        return True

    async def execute_query(self, request: QueryRequest) -> QueryResult:
        if self._raise_error:
            raise self._raise_error
        return QueryResult(
            columns=["col1", "col2"],
            rows=[{"col1": 1, "col2": "a"}, {"col1": 2, "col2": "b"}],
            row_count=2,
        )

    async def list_tables(self, schema: str | None = None) -> List[str]:
        return []

    async def get_columns(self, schema: str | None, table: str) -> List[tuple]:
        return []


class RecordingDataSource(DataSource):
    def __init__(self, source_id: str) -> None:
        self._source_id = source_id
        self.last_request: QueryRequest | None = None

    @property
    def source_id(self) -> str:
        return self._source_id

    async def test_connection(self) -> bool:
        return True

    async def execute_query(self, request: QueryRequest) -> QueryResult:
        self.last_request = request
        return QueryResult(
            columns=["col1", "col2"],
            rows=[{"col1": 1, "col2": "a"}],
            row_count=1,
        )

    async def list_tables(self, schema: str | None = None) -> List[str]:
        return []

    async def get_columns(self, schema: str | None, table: str) -> List[tuple]:
        return []


@pytest.fixture
def router() -> DataSourceRouter:
    r = DataSourceRouter()
    r.register(FakeDataSource("s1"))
    return r


@pytest.fixture
def tool(router: DataSourceRouter) -> QueryDataTool:
    return QueryDataTool(router=router)


@pytest.fixture
def context() -> ToolContext:
    return ToolContext()


# --- Success ---


@pytest.mark.asyncio
async def test_execute_success(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "s1", "sql": "SELECT 1"},
        context=context,
    )
    assert "Query succeeded" in result.content
    assert "source_id=s1" in result.content
    assert "row_count=2" in result.content
    assert result.metadata["source_id"] == "s1"
    assert result.metadata["row_count"] == 2
    assert len(result.metadata["rows"]) == 2


@pytest.mark.asyncio
async def test_execute_success_with_limit(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "s1", "sql": "SELECT 1", "limit": 100},
        context=context,
    )
    assert "Query succeeded" in result.content
    assert result.metadata["source_id"] == "s1"
    assert result.metadata["row_count"] == 2


@pytest.mark.asyncio
async def test_default_limit_uses_tool_configuration(context: ToolContext) -> None:
    ds = RecordingDataSource("s1")
    router = DataSourceRouter()
    router.register(ds)
    tool = QueryDataTool(router=router, default_limit=5)

    result = await tool.execute(
        args={"source_id": "s1", "sql": "SELECT 1"},
        context=context,
    )
    assert result.metadata["row_count"] == 1
    assert ds.last_request is not None
    assert ds.last_request.limit == 5


@pytest.mark.asyncio
async def test_sql_validation_rejects_non_readonly_sql(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "s1", "sql": "DELETE FROM some_table"},
        context=context,
    )
    assert "SQL validation failed" in result.content
    assert "Forbidden keyword: DELETE" in result.content


# --- Parameter validation ---


@pytest.mark.asyncio
async def test_missing_source_id(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"sql": "SELECT 1"},
        context=context,
    )
    assert "Parameter validation failed" in result.content
    assert "source_id is required" in result.content


@pytest.mark.asyncio
async def test_missing_sql(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "s1"},
        context=context,
    )
    assert "Parameter validation failed" in result.content
    assert "sql is required" in result.content


@pytest.mark.asyncio
async def test_empty_source_id(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "   ", "sql": "SELECT 1"},
        context=context,
    )
    assert "Parameter validation failed" in result.content
    assert "source_id cannot be empty" in result.content


@pytest.mark.asyncio
async def test_empty_sql(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "s1", "sql": "  "},
        context=context,
    )
    assert "Parameter validation failed" in result.content
    assert "sql cannot be empty" in result.content


@pytest.mark.asyncio
async def test_limit_too_small(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "s1", "sql": "SELECT 1", "limit": 0},
        context=context,
    )
    assert "Parameter validation failed" in result.content
    assert f"between {LIMIT_MIN} and {LIMIT_MAX}" in result.content


@pytest.mark.asyncio
async def test_limit_too_large(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "s1", "sql": "SELECT 1", "limit": LIMIT_MAX + 1},
        context=context,
    )
    assert "Parameter validation failed" in result.content
    assert f"between {LIMIT_MIN} and {LIMIT_MAX}" in result.content


@pytest.mark.asyncio
async def test_limit_invalid_type(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "s1", "sql": "SELECT 1", "limit": "not_an_int"},
        context=context,
    )
    assert "Parameter validation failed" in result.content
    assert "limit must be an integer" in result.content


# --- Routing / DataSource errors ---


@pytest.mark.asyncio
async def test_unknown_source_returns_error(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    result = await tool.execute(
        args={"source_id": "unknown_src", "sql": "SELECT 1"},
        context=context,
    )
    assert "UNKNOWN_DATA_SOURCE" in result.content
    assert "Unknown data source" in result.content
    assert result.metadata["source_id"] == "unknown_src"


@pytest.mark.asyncio
async def test_execution_error_returns_unified_message(
    router: DataSourceRouter,
    context: ToolContext,
) -> None:
    router.register(
        FakeDataSource(
            "s2",
            raise_error=DataSourceExecutionError(
                "Connection refused",
                sql="SELECT 1",
            ),
        )
    )
    tool = QueryDataTool(router=router)
    result = await tool.execute(
        args={"source_id": "s2", "sql": "SELECT 1"},
        context=context,
    )
    assert "DATA_SOURCE_EXECUTION" in result.content
    assert "Connection refused" in result.content
    assert result.metadata["source_id"] == "s2"


@pytest.mark.asyncio
async def test_schema_includes_limit_range() -> None:
    tool = QueryDataTool(router=DataSourceRouter())
    schema = tool.get_args_schema()
    props = schema.parameters["properties"]
    assert props["limit"]["minimum"] == LIMIT_MIN
    assert props["limit"]["maximum"] == LIMIT_MAX


# --- Audit ---


@pytest.mark.asyncio
async def test_audit_called_on_success(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    """成功路径应调用 audit_query_event，且 status=success、row_count 正确。"""
    with patch("mine_agent.tools.query_data.audit_query_event") as mock_audit:
        result = await tool.execute(
            args={"source_id": "s1", "sql": "SELECT 1"},
            context=context,
        )
        assert "Query succeeded" in result.content
        mock_audit.assert_called_once()
        call_kw = mock_audit.call_args.kwargs
        assert call_kw["source_id"] == "s1"
        assert call_kw["sql"] == "SELECT 1"
        assert call_kw["status"] == "success"
        assert call_kw["row_count"] == 2


@pytest.mark.asyncio
async def test_audit_called_on_success_with_user_id(
    tool: QueryDataTool,
) -> None:
    """成功路径应传入 context.user_id。"""
    ctx = ToolContext(user_id="u123", conversation_id="c1")
    with patch("mine_agent.tools.query_data.audit_query_event") as mock_audit:
        await tool.execute(
            args={"source_id": "s1", "sql": "SELECT 1"},
            context=ctx,
        )
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["user_id"] == "u123"


@pytest.mark.asyncio
async def test_audit_called_on_datasource_error(
    router: DataSourceRouter,
    context: ToolContext,
) -> None:
    """DataSourceError 路径应调用 audit_query_event，status=failure。"""
    router.register(
        FakeDataSource(
            "s2",
            raise_error=DataSourceExecutionError("Connection refused", sql="SELECT 1"),
        )
    )
    tool = QueryDataTool(router=router)
    with patch("mine_agent.tools.query_data.audit_query_event") as mock_audit:
        result = await tool.execute(
            args={"source_id": "s2", "sql": "SELECT 1"},
            context=context,
        )
        assert "DATA_SOURCE_EXECUTION" in result.content
        mock_audit.assert_called_once()
        call_kw = mock_audit.call_args.kwargs
        assert call_kw["source_id"] == "s2"
        assert call_kw["sql"] == "SELECT 1"
        assert call_kw["status"] == "failure"
        assert call_kw["row_count"] is None


@pytest.mark.asyncio
async def test_audit_called_on_validation_failure(
    tool: QueryDataTool,
    context: ToolContext,
) -> None:
    """参数校验失败路径应调用 audit_query_event，status=failure。"""
    with patch("mine_agent.tools.query_data.audit_query_event") as mock_audit:
        result = await tool.execute(
            args={"source_id": "s1"},
            context=context,
        )
        assert "Parameter validation failed" in result.content
        mock_audit.assert_called_once()
        call_kw = mock_audit.call_args.kwargs
        assert call_kw["status"] == "failure"
        assert call_kw["row_count"] is None

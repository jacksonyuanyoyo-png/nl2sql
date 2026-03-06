"""
Snowflake data source adapter.

Provides DataSource implementation for Snowflake via snowflake.connector.
Requires optional dependency: pip install mine-agent[snowflake]
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from mine_agent.capabilities.data_source.base import DataSource
from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult
from mine_agent.capabilities.data_source.sql_guard import (
    DEFAULT_ALLOWED_START_KEYWORDS,
    validate_allowed_schemas,
    validate_readonly_sql,
)


class SnowflakeDriverNotFoundError(Exception):
    """Raised when snowflake.connector is not installed. Install with: pip install mine-agent[snowflake]"""

    def __init__(self) -> None:
        super().__init__(
            "snowflake.connector not installed. Install with: pip install mine-agent[snowflake]"
        )


def _ensure_driver() -> None:
    """Ensure snowflake.connector is available; raise SnowflakeDriverNotFoundError if not."""
    try:
        import snowflake.connector  # noqa: F401
    except ImportError as e:
        raise SnowflakeDriverNotFoundError() from e


def _apply_limit(sql: str, limit: int | None) -> str:
    """
    Apply row limit to SQL if supported.
    Call point for limit handling; Snowflake uses LIMIT n.
    """
    # TODO: Parse SQL and append LIMIT {limit} when appropriate
    _ = limit
    return sql


def _map_snowflake_exception(exc: BaseException) -> Exception:
    """
    Map Snowflake connector exceptions to user-readable errors.
    Call point for exception mapping; skeleton for now.
    """
    # TODO: Map snowflake.connector errors to DataSourceError subclasses
    return exc


class SnowflakeDataSource(DataSource):
    def __init__(self, source_id: str, connection_options: Dict[str, Any]) -> None:
        self._source_id = source_id
        self._connection_options = connection_options

    @property
    def source_id(self) -> str:
        return self._source_id

    async def test_connection(self) -> bool:
        _ensure_driver()
        # TODO: Create connection and verify connectivity
        return True

    async def execute_query(self, request: QueryRequest) -> QueryResult:
        _ensure_driver()
        allowed_kw = self._connection_options.get("allowed_sql_keywords")
        allowed_keywords = (
            list(allowed_kw) if allowed_kw is not None else list(DEFAULT_ALLOWED_START_KEYWORDS)
        )
        validate_readonly_sql(request.sql, allowed_start_keywords=allowed_keywords)
        allowed_schemas: List[str] | None = self._connection_options.get("allowed_schemas")
        validate_allowed_schemas(request.sql, allowed_schemas)
        limited_sql = _apply_limit(request.sql, request.limit)
        try:
            # TODO: Execute limited_sql via snowflake.connector and return real results
            _ = limited_sql
            return QueryResult(
                columns=["status"],
                rows=[{"status": "snowflake placeholder"}],
                row_count=1,
            )
        except BaseException as e:
            raise _map_snowflake_exception(e)

    async def list_tables(self, schema: str | None = None) -> List[str]:
        _ensure_driver()
        # TODO: Query INFORMATION_SCHEMA.TABLES for table list
        # SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = :schema (or no filter)
        _ = schema
        return []

    async def get_columns(
        self, schema: str | None, table: str
    ) -> List[Tuple[str, str]]:
        _ensure_driver()
        # TODO: Query INFORMATION_SCHEMA.COLUMNS for column name and type
        _ = schema
        _ = table
        return []

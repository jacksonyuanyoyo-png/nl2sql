"""
Oracle data source adapter.

Provides DataSource implementation for Oracle databases via oracledb.
Requires optional dependency: pip install mine-agent[oracle]
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

from mine_agent.capabilities.data_source.base import DataSource
from mine_agent.capabilities.data_source.errors import (
    DataSourceAuthError,
    DataSourceExecutionError,
    DataSourceTimeoutError,
)
from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult
from mine_agent.capabilities.data_source.sql_guard import (
    DEFAULT_ALLOWED_START_KEYWORDS,
    validate_allowed_schemas,
    validate_readonly_sql,
)


class OracleDriverNotFoundError(Exception):
    """Raised when oracledb is not installed. Install with: pip install mine-agent[oracle]"""

    def __init__(self) -> None:
        super().__init__(
            "oracledb driver not installed. Install with: pip install mine-agent[oracle]"
        )


def _ensure_driver() -> None:
    """Ensure oracledb is available; raise OracleDriverNotFoundError if not."""
    try:
        import oracledb  # noqa: F401
    except ImportError as e:
        raise OracleDriverNotFoundError() from e


def _build_dsn(connection_options: Dict[str, Any]) -> Optional[str]:
    """
    Build DSN from connection_options.
    Returns dsn if provided, or assembles from host/port/service_name.
    """
    if "dsn" in connection_options:
        return str(connection_options["dsn"])
    host = connection_options.get("host")
    if not host:
        return None
    port = connection_options.get("port", 1521)
    service_name = connection_options.get("service_name", "ORCL")
    return f"{host}:{port}/{service_name}"


def _get_connection_params(connection_options: Dict[str, Any]) -> Dict[str, Any]:
    """Extract connection params: user, password, dsn (or host/port/service_name)."""
    params: Dict[str, Any] = {}
    if "user" in connection_options:
        params["user"] = connection_options["user"]
    if "password" in connection_options:
        params["password"] = connection_options["password"]
    dsn = _build_dsn(connection_options)
    if dsn:
        params["dsn"] = dsn
    else:
        # Fallback: pass host/port/service_name directly to oracledb.connect
        for key in ("host", "port", "service_name"):
            if key in connection_options:
                params[key] = connection_options[key]
    return params


def _create_connection(connection_options: Dict[str, Any]) -> Any:
    """Create oracledb connection. Must be called with driver available."""
    import oracledb

    params = _get_connection_params(connection_options)
    return oracledb.connect(**params)


# Oracle 12c+ FETCH FIRST n ROWS ONLY; simple heuristic: no LIMIT/FETCH in normalized SQL
_LIMIT_PATTERN = re.compile(
    r"\b(?:LIMIT|FETCH\s+FIRST|ROWNUM\s*[<>=])\b",
    re.IGNORECASE | re.DOTALL,
)


def _apply_limit(sql: str, limit: Optional[int]) -> str:
    """
    Apply row limit to SQL when no limit clause present.
    Appends Oracle syntax: FETCH FIRST n ROWS ONLY.
    """
    if limit is None or limit <= 0:
        return sql
    if _LIMIT_PATTERN.search(sql):
        return sql
    # Append before trailing semicolon if any
    stripped = sql.rstrip()
    if stripped.endswith(";"):
        return stripped[:-1].rstrip() + f" FETCH FIRST {limit} ROWS ONLY;"
    return stripped + f" FETCH FIRST {limit} ROWS ONLY"


def _map_oracle_exception(exc: BaseException, sql: Optional[str] = None) -> Exception:
    """
    Map Oracle/oracledb exceptions to DataSourceError subclasses.
    """
    # OracleDriverNotFoundError is raised before oracledb is used, re-raise as-is
    if isinstance(exc, OracleDriverNotFoundError):
        return exc

    try:
        import oracledb
    except ImportError:
        return exc

    if not isinstance(exc, oracledb.DatabaseError):
        return DataSourceExecutionError(
            message=str(exc),
            sql=sql,
            details={"original_type": type(exc).__name__},
        )

    err = exc.args[0] if exc.args else None
    if err is None:
        return DataSourceExecutionError(message=str(exc), sql=sql)

    code = getattr(err, "code", None)
    msg = str(exc)

    # ORA-01017: invalid username/password
    if code == 1017:
        return DataSourceAuthError(message=msg or "Invalid username/password")

    # ORA-12170, ORA-12535: TNS timeout / connection timeout
    if code in (12170, 12535):
        return DataSourceTimeoutError(message=msg or "Connection timeout")

    # ORA-01031: insufficient privileges
    if code == 1031:
        return DataSourceAuthError(message=msg or "Insufficient privileges")

    return DataSourceExecutionError(
        message=msg,
        sql=sql,
        details={"ora_code": code, "ora_full": str(err)},
    )


def _execute_query_sync(connection_options: Dict[str, Any], sql: str) -> QueryResult:
    """Execute SQL and return QueryResult. Runs in sync context."""
    conn = _create_connection(connection_options)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        if cursor.description:
            columns = [d[0] for d in cursor.description]
            raw_rows = cursor.fetchall()
            rows = [dict(zip(columns, r)) for r in raw_rows]
            return QueryResult(columns=columns, rows=rows, row_count=len(rows))
        return QueryResult(columns=[], rows=[], row_count=0)
    finally:
        conn.close()


def _test_connection_sync(connection_options: Dict[str, Any]) -> bool:
    """Test connection by executing SELECT 1 FROM DUAL."""
    conn = _create_connection(connection_options)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.fetchone()
        return True
    finally:
        conn.close()


def _list_tables_sync(
    connection_options: Dict[str, Any], schema: Optional[str]
) -> List[str]:
    """Query ALL_TABLES for table names, optionally filtered by schema (OWNER)."""
    conn = _create_connection(connection_options)
    try:
        cursor = conn.cursor()
        if schema:
            cursor.execute(
                "SELECT TABLE_NAME FROM ALL_TABLES WHERE OWNER = :owner ORDER BY TABLE_NAME",
                {"owner": schema.upper()},
            )
        else:
            cursor.execute(
                "SELECT TABLE_NAME FROM ALL_TABLES ORDER BY OWNER, TABLE_NAME"
            )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def _get_columns_sync(
    connection_options: Dict[str, Any],
    schema: Optional[str],
    table: str,
) -> List[tuple]:
    """Query ALL_TAB_COLUMNS for column name and data type. Returns list of (name, type)."""
    conn = _create_connection(connection_options)
    try:
        cursor = conn.cursor()
        if schema:
            cursor.execute(
                """SELECT COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS
                   WHERE OWNER = :owner AND TABLE_NAME = :tname ORDER BY COLUMN_ID""",
                {"owner": schema.upper(), "tname": table.upper()},
            )
        else:
            cursor.execute(
                """SELECT COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS
                   WHERE TABLE_NAME = :tname ORDER BY OWNER, COLUMN_ID""",
                {"tname": table.upper()},
            )
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        conn.close()


def _get_all_columns_sync(
    connection_options: Dict[str, Any],
    schema: Optional[str],
) -> Dict[str, List[tuple]]:
    """Fetch all tables' columns in one query. Returns dict table_name -> [(col_name, data_type), ...]."""
    conn = _create_connection(connection_options)
    try:
        cursor = conn.cursor()
        if schema:
            cursor.execute(
                """SELECT OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS
                   WHERE OWNER = :owner ORDER BY TABLE_NAME, COLUMN_ID""",
                {"owner": schema.upper()},
            )
        else:
            cursor.execute(
                """SELECT OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS
                   WHERE OWNER NOT IN ('SYS', 'SYSTEM', 'XDB', 'MDSYS', 'CTXSYS', 'WMSYS')
                   ORDER BY OWNER, TABLE_NAME, COLUMN_ID"""
            )
        result: Dict[str, List[tuple]] = {}
        for owner, table_name, col_name, data_type in cursor.fetchall():
            key = table_name if schema else f"{owner}.{table_name}"
            result.setdefault(key, []).append((col_name, data_type))
        return result
    finally:
        conn.close()


class OracleDataSource(DataSource):
    def __init__(self, source_id: str, connection_options: Dict[str, Any]) -> None:
        self._source_id = source_id
        self._connection_options = connection_options

    @property
    def source_id(self) -> str:
        return self._source_id

    async def test_connection(self) -> bool:
        _ensure_driver()
        try:
            return await asyncio.to_thread(
                _test_connection_sync, self._connection_options
            )
        except BaseException as e:
            raise _map_oracle_exception(e)

    async def execute_query(self, request: QueryRequest) -> QueryResult:
        _ensure_driver()
        allowed_kw = self._connection_options.get("allowed_sql_keywords")
        if allowed_kw is not None:
            allowed_keywords: List[str] = list(allowed_kw)
        else:
            allowed_keywords = list(DEFAULT_ALLOWED_START_KEYWORDS)
        validate_readonly_sql(request.sql, allowed_start_keywords=allowed_keywords)
        allowed_schemas: List[str] | None = self._connection_options.get(
            "allowed_schemas"
        )
        validate_allowed_schemas(request.sql, allowed_schemas)
        limited_sql = _apply_limit(request.sql, request.limit)
        try:
            return await asyncio.to_thread(
                _execute_query_sync, self._connection_options, limited_sql
            )
        except BaseException as e:
            raise _map_oracle_exception(e, sql=request.sql)

    async def list_tables(self, schema: Optional[str] = None) -> List[str]:
        _ensure_driver()
        try:
            return await asyncio.to_thread(
                _list_tables_sync, self._connection_options, schema
            )
        except BaseException as e:
            raise _map_oracle_exception(e)

    async def get_columns(
        self, schema: Optional[str], table: str
    ) -> List[tuple]:
        _ensure_driver()
        try:
            return await asyncio.to_thread(
                _get_columns_sync,
                self._connection_options,
                schema,
                table,
            )
        except BaseException as e:
            raise _map_oracle_exception(e)

    async def get_all_columns(
        self, schema: Optional[str]
    ) -> Dict[str, List[tuple]]:
        """Fetch all tables' columns in one DB round-trip. Used by schema extract for speed."""
        _ensure_driver()
        try:
            return await asyncio.to_thread(
                _get_all_columns_sync,
                self._connection_options,
                schema,
            )
        except BaseException as e:
            raise _map_oracle_exception(e)

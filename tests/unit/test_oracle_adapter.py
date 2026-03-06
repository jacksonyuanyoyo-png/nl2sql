"""
Unit tests for Oracle data source adapter.
"""

from __future__ import annotations

import builtins
from unittest.mock import MagicMock, patch

import pytest

from mine_agent.capabilities.data_source.errors import (
    DataSourceAuthError,
    DataSourceExecutionError,
    DataSourceTimeoutError,
    SqlValidationError,
)
from mine_agent.capabilities.data_source.models import QueryRequest, QueryResult
from mine_agent.integrations.oracle.client import (
    OracleDataSource,
    OracleDriverNotFoundError,
    _apply_limit,
    _build_dsn,
    _get_connection_params,
    _map_oracle_exception,
)

_ORIGINAL_IMPORT = builtins.__import__


def _mock_import_no_oracledb(name: str, *args: object, **kwargs: object) -> object:
    """Simulate missing oracledb driver."""
    if name == "oracledb":
        raise ImportError("No module named 'oracledb'")
    return _ORIGINAL_IMPORT(name, *args, **kwargs)


@pytest.fixture
def no_oracledb() -> None:
    """Fixture to simulate oracledb not installed."""
    with patch.object(builtins, "__import__", side_effect=_mock_import_no_oracledb):
        yield


# --- No driver tests ---


@pytest.mark.asyncio
async def test_test_connection_raises_readable_error_when_no_driver(
    no_oracledb: None,
) -> None:
    """When oracledb is not installed, test_connection raises OracleDriverNotFoundError."""
    ds = OracleDataSource(source_id="ora1", connection_options={})
    with pytest.raises(OracleDriverNotFoundError) as exc_info:
        await ds.test_connection()
    assert "oracledb" in str(exc_info.value).lower()
    assert "pip install" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_execute_query_raises_readable_error_when_no_driver(
    no_oracledb: None,
) -> None:
    """When oracledb is not installed, execute_query raises OracleDriverNotFoundError."""
    ds = OracleDataSource(source_id="ora1", connection_options={})
    req = QueryRequest(source_id="ora1", sql="SELECT 1 FROM dual", limit=10)
    with pytest.raises(OracleDriverNotFoundError) as exc_info:
        await ds.execute_query(req)
    assert "oracledb" in str(exc_info.value).lower()
    assert "pip install" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_list_tables_raises_readable_error_when_no_driver(
    no_oracledb: None,
) -> None:
    """When oracledb is not installed, list_tables raises OracleDriverNotFoundError."""
    ds = OracleDataSource(source_id="ora1", connection_options={})
    with pytest.raises(OracleDriverNotFoundError):
        await ds.list_tables(schema="SCOTT")


# --- With mocked oracledb ---


@pytest.mark.asyncio
async def test_execute_query_returns_query_result_from_cursor() -> None:
    """execute_query returns QueryResult built from cursor.description and fetchall."""
    from mine_agent.integrations.oracle import client as oracle_client

    expected = QueryResult(
        columns=["id", "name"],
        rows=[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
        row_count=2,
    )

    def fake_execute_sync(_opts: object, sql: str) -> QueryResult:
        assert "SELECT" in sql
        return expected

    with patch.object(oracle_client, "_execute_query_sync", side_effect=fake_execute_sync):
        ds = OracleDataSource(source_id="ora1", connection_options={})
        req = QueryRequest(source_id="ora1", sql="SELECT id, name FROM t", limit=100)
        result = await ds.execute_query(req)
    assert result == expected
    assert result.columns == ["id", "name"]
    assert result.row_count == 2
    assert len(result.rows) == 2


@pytest.mark.asyncio
async def test_list_tables_returns_list_from_all_tables() -> None:
    """list_tables returns List[str] from ALL_TABLES query."""
    from mine_agent.integrations.oracle import client as oracle_client

    def fake_list_sync(_opts: object, schema: str | None) -> list[str]:
        if schema == "SCOTT":
            return ["EMP", "DEPT"]
        return ["T1", "T2", "T3"]

    with patch.object(oracle_client, "_list_tables_sync", side_effect=fake_list_sync):
        ds = OracleDataSource(source_id="ora1", connection_options={})
        tables = await ds.list_tables(schema="SCOTT")
    assert tables == ["EMP", "DEPT"]

    with patch.object(oracle_client, "_list_tables_sync", side_effect=fake_list_sync):
        ds = OracleDataSource(source_id="ora1", connection_options={})
        tables = await ds.list_tables(schema=None)
    assert tables == ["T1", "T2", "T3"]


@pytest.mark.asyncio
async def test_test_connection_returns_true_when_ok() -> None:
    """test_connection returns True when connection succeeds."""
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_test_connection_sync", return_value=True):
        ds = OracleDataSource(source_id="ora1", connection_options={})
        ok = await ds.test_connection()
    assert ok is True


# --- _apply_limit ---


def test_apply_limit_appends_fetch_first_when_no_limit_clause() -> None:
    """_apply_limit appends FETCH FIRST n ROWS ONLY when SQL has no limit."""
    sql = "SELECT * FROM t"
    assert _apply_limit(sql, 10) == "SELECT * FROM t FETCH FIRST 10 ROWS ONLY"


def test_apply_limit_preserves_semicolon() -> None:
    """_apply_limit inserts before trailing semicolon."""
    sql = "SELECT * FROM t;"
    assert _apply_limit(sql, 5) == "SELECT * FROM t FETCH FIRST 5 ROWS ONLY;"


def test_apply_limit_skips_when_limit_none() -> None:
    """_apply_limit returns original SQL when limit is None."""
    sql = "SELECT * FROM t"
    assert _apply_limit(sql, None) == sql


def test_apply_limit_skips_when_limit_zero() -> None:
    """_apply_limit returns original SQL when limit <= 0."""
    sql = "SELECT * FROM t"
    assert _apply_limit(sql, 0) == sql


def test_apply_limit_skips_when_sql_has_limit() -> None:
    """_apply_limit does not append when SQL already has LIMIT."""
    sql = "SELECT * FROM t LIMIT 5"
    assert _apply_limit(sql, 10) == sql


def test_apply_limit_skips_when_sql_has_fetch_first() -> None:
    """_apply_limit does not append when SQL already has FETCH FIRST."""
    sql = "SELECT * FROM t FETCH FIRST 3 ROWS ONLY"
    assert _apply_limit(sql, 10) == sql


# --- _build_dsn ---


def test_build_dsn_uses_dsn_when_provided() -> None:
    """_build_dsn returns dsn from connection_options when present."""
    opts = {"dsn": "localhost:1521/XEPDB1", "user": "u", "password": "p"}
    assert _build_dsn(opts) == "localhost:1521/XEPDB1"


def test_build_dsn_assembles_from_host_port_service() -> None:
    """_build_dsn assembles host:port/service_name when dsn not provided."""
    opts = {"host": "db.example.com", "port": 1521, "service_name": "ORCL"}
    assert _build_dsn(opts) == "db.example.com:1521/ORCL"


def test_build_dsn_defaults_port_and_service() -> None:
    """_build_dsn uses default port 1521 and service_name ORCL."""
    opts = {"host": "localhost"}
    assert _build_dsn(opts) == "localhost:1521/ORCL"


def test_build_dsn_returns_none_when_no_host_or_dsn() -> None:
    """_build_dsn returns None when neither dsn nor host provided."""
    opts = {"user": "u", "password": "p"}
    assert _build_dsn(opts) is None


# --- _get_connection_params ---


def test_get_connection_params_includes_user_password_dsn() -> None:
    """_get_connection_params extracts user, password, dsn."""
    opts = {
        "user": "scott",
        "password": "tiger",
        "dsn": "localhost/XE",
    }
    params = _get_connection_params(opts)
    assert params["user"] == "scott"
    assert params["password"] == "tiger"
    assert params["dsn"] == "localhost/XE"


def test_get_connection_params_assembles_dsn_from_host() -> None:
    """_get_connection_params builds dsn from host/port/service_name."""
    opts = {"user": "u", "password": "p", "host": "db", "port": 1522, "service_name": "XE"}
    params = _get_connection_params(opts)
    assert params["dsn"] == "db:1522/XE"


# --- _map_oracle_exception ---


def test_map_oracle_exception_preserves_driver_not_found() -> None:
    """_map_oracle_exception re-raises OracleDriverNotFoundError as-is."""
    exc = OracleDriverNotFoundError()
    result = _map_oracle_exception(exc)
    assert result is exc


def _make_fake_db_error_and_map(code: int, sql: str | None = None) -> Exception:
    """Create fake oracledb.DatabaseError and call _map_oracle_exception with mocked oracledb."""
    import sys

    class FakeErrorObj:
        def __init__(self, code: int):
            self.code = code

    class FakeDatabaseError(Exception):
        pass

    mock_oracledb = MagicMock()
    mock_oracledb.DatabaseError = FakeDatabaseError

    with patch.dict(sys.modules, {"oracledb": mock_oracledb}):
        err_obj = FakeErrorObj(code)
        db_err = FakeDatabaseError()
        db_err.args = (err_obj,)
        return _map_oracle_exception(db_err, sql=sql)


def test_map_oracle_exception_maps_ora_1017_to_auth_error() -> None:
    """ORA-01017 maps to DataSourceAuthError."""
    result = _make_fake_db_error_and_map(1017)
    assert isinstance(result, DataSourceAuthError)


def test_map_oracle_exception_maps_ora_12170_to_timeout_error() -> None:
    """ORA-12170 maps to DataSourceTimeoutError."""
    result = _make_fake_db_error_and_map(12170)
    assert isinstance(result, DataSourceTimeoutError)


def test_map_oracle_exception_maps_ora_1031_to_auth_error() -> None:
    """ORA-01031 (insufficient privileges) maps to DataSourceAuthError."""
    result = _make_fake_db_error_and_map(1031)
    assert isinstance(result, DataSourceAuthError)


def test_map_oracle_exception_maps_unknown_ora_to_execution_error() -> None:
    """Unknown ORA code maps to DataSourceExecutionError."""
    result = _make_fake_db_error_and_map(942, sql="SELECT * FROM missing")
    assert isinstance(result, DataSourceExecutionError)
    assert result.details.get("ora_code") == 942
    assert result.details.get("sql") == "SELECT * FROM missing"


def test_map_oracle_exception_maps_non_db_exception_to_execution_error() -> None:
    """Non-DatabaseError maps to DataSourceExecutionError."""
    exc = ValueError("something went wrong")
    result = _map_oracle_exception(exc, sql="SELECT 1")
    assert isinstance(result, DataSourceExecutionError)
    assert "something went wrong" in str(result)
    assert result.details.get("original_type") == "ValueError"


# --- DataSource interface ---


@pytest.mark.asyncio
async def test_source_id_property() -> None:
    """DataSource interface: source_id returns configured value."""
    ds = OracleDataSource(source_id="my_oracle", connection_options={})
    assert ds.source_id == "my_oracle"


# --- Error propagation ---


@pytest.mark.asyncio
async def test_execute_query_raises_mapped_error_on_sync_failure() -> None:
    """execute_query raises DataSourceAuthError when sync raises ORA-01017."""
    import sys

    from mine_agent.integrations.oracle import client as oracle_client

    class FakeErrorObj:
        def __init__(self, code: int):
            self.code = code

    class FakeDatabaseError(Exception):
        pass

    mock_oracledb = MagicMock()
    mock_oracledb.DatabaseError = FakeDatabaseError

    err_obj = FakeErrorObj(1017)
    db_err = FakeDatabaseError()
    db_err.args = (err_obj,)

    def fake_execute_sync(_opts: object, _sql: str) -> QueryResult:
        raise db_err

    with patch.dict(sys.modules, {"oracledb": mock_oracledb}):
        with patch.object(oracle_client, "_execute_query_sync", side_effect=fake_execute_sync):
            ds = OracleDataSource(source_id="ora1", connection_options={})
            req = QueryRequest(source_id="ora1", sql="SELECT 1", limit=10)
            with pytest.raises(DataSourceAuthError):
                await ds.execute_query(req)


# --- SQL Guard integration ---


@pytest.mark.asyncio
async def test_execute_query_write_sql_raises_sql_validation_error() -> None:
    """Write operations (INSERT/UPDATE/DELETE/etc) are blocked by SQL Guard."""
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"):
        ds = OracleDataSource(source_id="ora1", connection_options={})
        for bad_sql in [
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET x = 1",
            "DELETE FROM t",
            "DROP TABLE t",
        ]:
            req = QueryRequest(source_id="ora1", sql=bad_sql, limit=10)
            with pytest.raises(SqlValidationError, match="Forbidden keyword"):
                await ds.execute_query(req)


@pytest.mark.asyncio
async def test_execute_query_forbidden_schema_raises_sql_validation_error() -> None:
    """Non-whitelisted schema is blocked when allowed_schemas is set."""
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"):
        ds = OracleDataSource(
            source_id="ora1",
            connection_options={"allowed_schemas": ["ALLOWED", "SCOTT"]},
        )
        req = QueryRequest(
            source_id="ora1",
            sql="SELECT * FROM forbidden.t",
            limit=10,
        )
        with pytest.raises(SqlValidationError, match="Schema not allowed: FORBIDDEN"):
            await ds.execute_query(req)


@pytest.mark.asyncio
async def test_execute_query_allowed_schema_passes() -> None:
    """When allowed_schemas is set and schema matches, query proceeds."""
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"), patch.object(
        oracle_client, "_execute_query_sync", side_effect=lambda _o, s: QueryResult(
            columns=["status"],
            rows=[{"status": "oracle placeholder"}],
            row_count=1,
        )
    ):
        ds = OracleDataSource(
            source_id="ora1",
            connection_options={"allowed_schemas": ["ALLOWED", "SCOTT"]},
        )
        req = QueryRequest(
            source_id="ora1",
            sql="SELECT * FROM allowed.t",
            limit=10,
        )
        result = await ds.execute_query(req)
    assert result.row_count == 1
    assert result.rows[0]["status"] == "oracle placeholder"


@pytest.mark.asyncio
async def test_execute_query_allowed_schemas_none_skips_validation() -> None:
    """When allowed_schemas is None, schema validation is skipped."""
    from mine_agent.integrations.oracle import client as oracle_client

    with patch.object(oracle_client, "_ensure_driver"), patch.object(
        oracle_client, "_execute_query_sync", side_effect=lambda _o, s: QueryResult(
            columns=["status"],
            rows=[{"status": "oracle placeholder"}],
            row_count=1,
        )
    ):
        ds = OracleDataSource(source_id="ora1", connection_options={})
        req = QueryRequest(
            source_id="ora1",
            sql="SELECT * FROM any_schema.any_table",
            limit=10,
        )
        result = await ds.execute_query(req)
    assert result.row_count == 1

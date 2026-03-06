"""Unit tests for data source error types."""

from __future__ import annotations

import pytest

from mine_agent.capabilities.data_source.errors import (
    DataSourceAuthError,
    DataSourceError,
    DataSourceExecutionError,
    DataSourceTimeoutError,
    SqlValidationError,
    UnknownDataSourceError,
)


class TestDataSourceError:
    """Tests for base DataSourceError."""

    def test_base_attributes(self) -> None:
        err = DataSourceError(
            message="test message",
            error_code="CUSTOM_CODE",
            retryable=True,
            details={"key": "value"},
        )
        assert err.message == "test message"
        assert err.error_code == "CUSTOM_CODE"
        assert err.retryable is True
        assert err.details == {"key": "value"}

    def test_default_values(self) -> None:
        err = DataSourceError(message="minimal")
        assert err.message == "minimal"
        assert err.error_code == "DATA_SOURCE_ERROR"
        assert err.retryable is False
        assert err.details == {}

    def test_str_returns_message(self) -> None:
        err = DataSourceError(message="str test")
        assert str(err) == "str test"

    def test_inherits_from_exception(self) -> None:
        err = DataSourceError(message="base")
        assert isinstance(err, Exception)
        with pytest.raises(DataSourceError):
            raise err


class TestUnknownDataSourceError:
    """Tests for UnknownDataSourceError."""

    def test_default_error_code_and_retryable(self) -> None:
        err = UnknownDataSourceError(message="source not found")
        assert err.error_code == "UNKNOWN_DATA_SOURCE"
        assert err.retryable is False

    def test_source_id_in_details(self) -> None:
        err = UnknownDataSourceError(
            message="not found",
            source_id="my_source",
        )
        assert err.details["source_id"] == "my_source"


class TestDataSourceAuthError:
    """Tests for DataSourceAuthError."""

    def test_default_error_code_and_retryable(self) -> None:
        err = DataSourceAuthError(message="auth failed")
        assert err.error_code == "DATA_SOURCE_AUTH"
        assert err.retryable is False


class TestDataSourceTimeoutError:
    """Tests for DataSourceTimeoutError."""

    def test_retryable_is_true(self) -> None:
        err = DataSourceTimeoutError(message="timeout")
        assert err.error_code == "DATA_SOURCE_TIMEOUT"
        assert err.retryable is True


class TestSqlValidationError:
    """Tests for SqlValidationError."""

    def test_default_error_code_and_retryable(self) -> None:
        err = SqlValidationError(message="invalid sql")
        assert err.error_code == "SQL_VALIDATION"
        assert err.retryable is False

    def test_sql_in_details(self) -> None:
        err = SqlValidationError(
            message="syntax error",
            sql="SELECT * FORM t",
        )
        assert err.details["sql"] == "SELECT * FORM t"


class TestDataSourceExecutionError:
    """Tests for DataSourceExecutionError."""

    def test_retryable_is_true(self) -> None:
        err = DataSourceExecutionError(message="execution failed")
        assert err.error_code == "DATA_SOURCE_EXECUTION"
        assert err.retryable is True

    def test_sql_in_details(self) -> None:
        err = DataSourceExecutionError(
            message="runtime error",
            sql="SELECT 1",
        )
        assert err.details["sql"] == "SELECT 1"


class TestExceptionHierarchy:
    """Tests for exception inheritance."""

    def test_all_subclasses_inherit_from_datasource_error(self) -> None:
        for cls in (
            UnknownDataSourceError,
            DataSourceAuthError,
            DataSourceTimeoutError,
            SqlValidationError,
            DataSourceExecutionError,
        ):
            err = cls(message="test")
            assert isinstance(err, DataSourceError)
            assert isinstance(err, Exception)

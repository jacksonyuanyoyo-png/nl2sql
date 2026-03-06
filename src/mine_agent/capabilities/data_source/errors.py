"""Unified data source exception system."""

from __future__ import annotations

from typing import Any, Dict, Optional


class DataSourceError(Exception):
    """Base exception for all data source errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "DATA_SOURCE_ERROR",
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.retryable = retryable
        self.details = details or {}

    def __str__(self) -> str:
        return self.message


class UnknownDataSourceError(DataSourceError):
    """Raised when the requested data source is not found or not registered."""

    def __init__(
        self,
        message: str,
        source_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        extra = details or {}
        if source_id is not None:
            extra["source_id"] = source_id
        super().__init__(
            message=message,
            error_code="UNKNOWN_DATA_SOURCE",
            retryable=False,
            details=extra,
        )


class DataSourceAuthError(DataSourceError):
    """Raised when authentication or authorization fails."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="DATA_SOURCE_AUTH",
            retryable=False,
            details=details or {},
        )


class DataSourceTimeoutError(DataSourceError):
    """Raised when a data source operation times out."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="DATA_SOURCE_TIMEOUT",
            retryable=True,
            details=details or {},
        )


class SqlValidationError(DataSourceError):
    """Raised when SQL validation fails (syntax, schema, permissions)."""

    def __init__(
        self,
        message: str,
        sql: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        extra = details or {}
        if sql is not None:
            extra["sql"] = sql
        super().__init__(
            message=message,
            error_code="SQL_VALIDATION",
            retryable=False,
            details=extra,
        )


class DataSourceExecutionError(DataSourceError):
    """Raised when query execution fails at the data source."""

    def __init__(
        self,
        message: str,
        sql: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        extra = details or {}
        if sql is not None:
            extra["sql"] = sql
        super().__init__(
            message=message,
            error_code="DATA_SOURCE_EXECUTION",
            retryable=True,
            details=extra,
        )

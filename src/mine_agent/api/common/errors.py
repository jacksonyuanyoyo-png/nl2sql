from __future__ import annotations

from enum import Enum
from typing import Optional

from fastapi import HTTPException, status
from pydantic import BaseModel


class ApiErrorCode(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    BAD_REQUEST = "BAD_REQUEST"
    ORCHESTRATOR_NOT_CONFIGURED = "ORCHESTRATOR_NOT_CONFIGURED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    trace_id: Optional[str] = None


def unauthorized_error(message: str = "Unauthorized") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error_code": ApiErrorCode.UNAUTHORIZED.value, "message": message},
    )


def forbidden_error(message: str = "Forbidden") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error_code": ApiErrorCode.FORBIDDEN.value, "message": message},
    )


def bad_request_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error_code": ApiErrorCode.BAD_REQUEST.value, "message": message},
    )


def orchestrator_not_configured_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error_code": ApiErrorCode.ORCHESTRATOR_NOT_CONFIGURED.value,
            "message": "Orchestrator not configured",
        },
    )

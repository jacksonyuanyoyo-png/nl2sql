"""FastAPI request/response models for chat endpoints."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request body for POST /v1/chat."""

    conversation_id: str = Field(..., description="Conversation identifier")
    user_message: str = Field(..., description="User input message")
    user_id: Optional[str] = Field(default=None, description="Optional user identifier")
    metadata: Dict[str, str] = Field(
        default_factory=dict,
        description="Optional metadata (e.g. selected source_id)",
    )


class ChatResponse(BaseModel):
    """Response body for POST /v1/chat."""

    assistant_content: str = Field(..., description="Assistant reply content")
    tool_outputs: List[str] = Field(default_factory=list, description="Tool execution outputs")


class HealthResponse(BaseModel):
    status: str = Field(..., description="Service health status")


class MetadataResponse(BaseModel):
    """Response body for GET /v1/metadata."""

    service_name: str = Field(..., description="Service name")
    service_version: str = Field(..., description="Service version")
    environment: str = Field(..., description="Environment (dev/prod)")
    auth_enabled: bool = Field(..., description="Whether API auth is enabled")
    registered_data_sources: List[str] = Field(
        default_factory=list,
        description="List of registered data source IDs",
    )
    data_source_health: Dict[str, bool] = Field(
        default_factory=dict,
        description="Health status per data source ID",
    )


class ErrorResponse(BaseModel):
    error_code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    trace_id: Optional[str] = Field(default=None, description="Request trace identifier")

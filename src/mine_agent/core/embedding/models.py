"""Configuration models for embedding services."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class EmbeddingConfig(BaseModel):
    """Configuration for an embedding provider."""

    vendor: str = Field(..., description="Provider name: deepseek, openai, etc.")
    model: Optional[str] = Field(default=None, description="Model name, e.g. embed-base, text-embedding-3-small")
    api_key: Optional[str] = Field(default=None, description="API key")
    base_url: Optional[str] = Field(default=None, description="Base URL for API")

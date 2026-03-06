from __future__ import annotations

import os
from typing import List

from pydantic import BaseModel, Field


# Default allowed SQL statement starters (read-only). Used when MINE_ALLOWED_SQL_KEYWORDS is not set.
# Env: MINE_ALLOWED_SQL_KEYWORDS = comma-separated, e.g. "SELECT,WITH,DESCRIBE,DESC,SHOW,EXPLAIN".
DEFAULT_ALLOWED_SQL_KEYWORDS = [
    "SELECT",
    "WITH",
    "DESCRIBE",
    "DESC",
    "SHOW",
    "EXPLAIN",
]


class AppSettings(BaseModel):
    environment: str = "dev"
    api_auth_enabled: bool = False
    api_tokens: List[str] = Field(default_factory=list)
    service_name: str = "mine-agent"
    service_version: str = "0.1.0"
    default_query_limit: int = Field(default=1000, ge=1, le=10000)
    max_tool_iterations: int = Field(default=10, ge=1, le=100)
    allowed_sql_keywords: List[str] = Field(default_factory=lambda: list(DEFAULT_ALLOWED_SQL_KEYWORDS))

    @classmethod
    def from_env(cls) -> "AppSettings":
        env = os.getenv("MINE_ENVIRONMENT", "dev")
        auth_enabled = os.getenv("MINE_API_AUTH_ENABLED", "false").strip().lower()
        raw_tokens = os.getenv("MINE_API_TOKENS", "")
        tokens = [token.strip() for token in raw_tokens.split(",") if token.strip()]

        raw_keywords = os.getenv("MINE_ALLOWED_SQL_KEYWORDS", "").strip()
        if raw_keywords:
            allowed_sql_keywords = [k.strip().upper() for k in raw_keywords.split(",") if k.strip()]
        else:
            allowed_sql_keywords = list(DEFAULT_ALLOWED_SQL_KEYWORDS)

        return cls(
            environment=env,
            api_auth_enabled=auth_enabled in {"1", "true", "yes", "on"},
            api_tokens=tokens,
            service_name=os.getenv("MINE_SERVICE_NAME", "mine-agent"),
            service_version=os.getenv("MINE_SERVICE_VERSION", "0.1.0"),
            default_query_limit=int(os.getenv("MINE_DEFAULT_QUERY_LIMIT", "1000")),
            max_tool_iterations=int(os.getenv("MINE_MAX_TOOL_ITERATIONS", "10")),
            allowed_sql_keywords=allowed_sql_keywords,
        )

    @classmethod
    def datasources_from_env(cls) -> "DataSourceRegistryConfig":
        """Load data sources from MINE_DATASOURCES env (JSON). See datasources module docs."""
        from mine_agent.config.datasources import DataSourceRegistryConfig

        return DataSourceRegistryConfig.from_env()

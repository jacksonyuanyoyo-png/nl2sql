"""
Data source registry configuration with environment variable loading.

Environment variable format (JSON):
  MINE_DATASOURCES - JSON array of data source definitions.
  Example:
    export MINE_DATASOURCES='[
      {"source_id":"ora1","source_type":"oracle","options":{"user":"app","password":"app","host":"localhost","port":1521,"service_name":"XE"}}
    ]'
  Or with DSN:
    export MINE_DATASOURCES='[
      {"source_id":"ora1","source_type":"oracle","options":{"user":"app","password":"app","dsn":"localhost:1521/XE"}}
    ]'

  Optional per-source: "allowed_sql_keywords" (list of allowed statement starters, e.g. ["SELECT","WITH","DESCRIBE","SHOW"]).
  Global default is from MINE_ALLOWED_SQL_KEYWORDS (see settings); per-source overrides for that data source only.

Alternative prefix format (not implemented; JSON preferred for flexibility):
  MINE_DATASOURCE_1_SOURCE_ID, MINE_DATASOURCE_1_SOURCE_TYPE, MINE_DATASOURCE_1_OPTIONS_USER, etc.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from mine_agent.capabilities.data_source.models import DataSourceConfig, DataSourceType


def _validate_oracle_options(source_id: str, options: Dict[str, Any]) -> None:
    """
    Fail-fast validation for Oracle data source options.
    Raises ValueError if required fields are missing.
    Required: user, password, and either dsn or (host + port + service_name).
    """
    missing: List[str] = []
    if not options.get("user"):
        missing.append("user")
    if not options.get("password"):
        missing.append("password")

    has_dsn = bool(options.get("dsn"))
    has_host = bool(options.get("host"))
    has_port = options.get("port") is not None
    has_service = bool(options.get("service_name"))
    has_host_port_service = has_host and has_port and has_service

    if not has_dsn and not has_host_port_service:
        if not has_host:
            missing.append("host")
        if not has_port:
            missing.append("port")
        if not has_service:
            missing.append("service_name")

    if missing:
        raise ValueError(
            f"Oracle data source '{source_id}' missing required options: {', '.join(missing)}. "
            "Required: user, password, and either dsn or (host, port, service_name)."
        )


def _validate_datasource_config(source_id: str, source_type: DataSourceType, options: Dict[str, Any]) -> None:
    """Fail-fast validation per source type. Raises ValueError on missing required fields."""
    if source_type == DataSourceType.ORACLE:
        _validate_oracle_options(source_id, options)
    # Snowflake validation can be added here when needed


class DataSourceRegistryConfig(BaseModel):
    sources: List[DataSourceConfig] = Field(default_factory=list)

    @classmethod
    def from_env(cls) -> "DataSourceRegistryConfig":
        """
        Load data sources from MINE_DATASOURCES environment variable (JSON format).
        Empty or unset env returns empty sources list.
        Fail-fast: raises ValueError if a declared source has missing required fields.
        """
        raw = os.getenv("MINE_DATASOURCES", "").strip()
        if not raw:
            return cls(sources=[])

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"MINE_DATASOURCES must be valid JSON: {e}"
            ) from e

        if not isinstance(data, list):
            raise ValueError("MINE_DATASOURCES must be a JSON array of data source objects")

        sources: List[DataSourceConfig] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(
                    f"MINE_DATASOURCES[{i}] must be an object, got {type(item).__name__}"
                )
            try:
                config = DataSourceConfig.model_validate(item)
            except Exception as e:
                raise ValueError(
                    f"MINE_DATASOURCES[{i}] invalid: {e}"
                ) from e
            _validate_datasource_config(
                config.source_id, config.source_type, config.options
            )
            sources.append(config)

        return cls(sources=sources)

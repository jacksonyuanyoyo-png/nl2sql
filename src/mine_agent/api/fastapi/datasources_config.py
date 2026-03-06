"""Dynamic datasource config storage (JSON file) and API models."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from mine_agent.capabilities.data_source.models import DataSourceConfig, DataSourceType


class ConnectionEntry(BaseModel):
    """Single connection config entry with unique id."""

    id: str = Field(..., description="Unique connection id")
    source_id: str = Field(..., description="Data source id")
    source_type: DataSourceType = Field(...)
    options: Dict[str, Any] = Field(default_factory=dict)
    allowed_schemas: Optional[List[str]] = None
    allowed_sql_keywords: Optional[List[str]] = None


def _config_path() -> Path:
    base = os.getenv("MINE_CONFIG_DIR", os.path.expanduser("~/.mine"))
    Path(base).mkdir(parents=True, exist_ok=True)
    return Path(base) / "dynamic_datasources.json"


def load_connections() -> List[ConnectionEntry]:
    path = _config_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [ConnectionEntry.model_validate(item) for item in data]
    except Exception:
        return []


def save_connections(entries: List[ConnectionEntry]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([e.model_dump() for e in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_connection(connection_id: str) -> Optional[ConnectionEntry]:
    for e in load_connections():
        if e.id == connection_id:
            return e
    return None


def create_connection(
    source_id: str,
    source_type: DataSourceType,
    options: Dict[str, Any],
    allowed_schemas: Optional[List[str]] = None,
    allowed_sql_keywords: Optional[List[str]] = None,
) -> ConnectionEntry:
    entries = load_connections()
    entry = ConnectionEntry(
        id=str(uuid.uuid4()),
        source_id=source_id,
        source_type=source_type,
        options=options,
        allowed_schemas=allowed_schemas,
        allowed_sql_keywords=allowed_sql_keywords,
    )
    entries.append(entry)
    save_connections(entries)
    return entry


def update_connection(
    connection_id: str,
    source_id: Optional[str] = None,
    source_type: Optional[DataSourceType] = None,
    options: Optional[Dict[str, Any]] = None,
    allowed_schemas: Optional[List[str]] = None,
    allowed_sql_keywords: Optional[List[str]] = None,
) -> Optional[ConnectionEntry]:
    entries = load_connections()
    for i, e in enumerate(entries):
        if e.id == connection_id:
            updated = ConnectionEntry(
                id=e.id,
                source_id=source_id if source_id is not None else e.source_id,
                source_type=source_type if source_type is not None else e.source_type,
                options=options if options is not None else e.options,
                allowed_schemas=allowed_schemas if allowed_schemas is not None else e.allowed_schemas,
                allowed_sql_keywords=allowed_sql_keywords if allowed_sql_keywords is not None else e.allowed_sql_keywords,
            )
            entries[i] = updated
            save_connections(entries)
            return updated
    return None


def delete_connection(connection_id: str) -> bool:
    entries = [e for e in load_connections() if e.id != connection_id]
    if len(entries) == len(load_connections()):
        return False
    save_connections(entries)
    return True


def connection_to_datasource_config(entry: ConnectionEntry) -> DataSourceConfig:
    opts = dict(entry.options)
    if entry.allowed_schemas is not None and "allowed_schemas" not in opts:
        opts["allowed_schemas"] = entry.allowed_schemas
    if entry.allowed_sql_keywords is not None and "allowed_sql_keywords" not in opts:
        opts["allowed_sql_keywords"] = entry.allowed_sql_keywords
    return DataSourceConfig(
        source_id=entry.source_id,
        source_type=entry.source_type,
        options=opts,
        allowed_schemas=entry.allowed_schemas,
        allowed_sql_keywords=entry.allowed_sql_keywords,
    )

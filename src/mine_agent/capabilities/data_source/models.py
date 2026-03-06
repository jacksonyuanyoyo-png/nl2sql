from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DataSourceType(str, Enum):
    ORACLE = "oracle"
    SNOWFLAKE = "snowflake"


class DataSourceConfig(BaseModel):
    source_id: str
    source_type: DataSourceType
    options: Dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True
    allowed_schemas: Optional[List[str]] = None
    allowed_sql_keywords: Optional[List[str]] = None


class QueryRequest(BaseModel):
    source_id: str
    sql: str
    limit: Optional[int] = 1000


class QueryResult(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int

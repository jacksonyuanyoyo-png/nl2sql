"""QueryDataTool: execute SQL against a registered data source."""

from __future__ import annotations

from typing import Any, Dict

import json

from mine_agent.capabilities.data_source.errors import DataSourceError, SqlValidationError
from mine_agent.capabilities.data_source.sql_guard import validate_readonly_sql
from mine_agent.observability.audit import audit_query_event
from mine_agent.capabilities.data_source.models import QueryRequest
from mine_agent.capabilities.data_source.router import DataSourceRouter
from mine_agent.core.llm.models import ToolSchema
from mine_agent.core.tool.base import Tool
from mine_agent.core.tool.models import ToolContext, ToolResult

LIMIT_MIN = 1
LIMIT_MAX = 10000
LIMIT_DEFAULT = 1000


def _render_query_result(
    source_id: str, rows: list[dict[str, Any]], row_count: int, columns: list[str]
) -> str:
    sample_rows = rows[:3]
    return (
        "Query succeeded. "
        f"source_id={source_id}, "
        f"row_count={row_count}, columns={columns}, "
        f"sample_rows={json.dumps(sample_rows, ensure_ascii=False, default=str)}"
    )


def _validate_args(
    args: Dict[str, Any], default_source_id: str | None, default_limit: int = LIMIT_DEFAULT
) -> str | None:
    """Validate source_id/sql/limit. source_id may come from default_source_id."""
    has_source_id = "source_id" in args and args.get("source_id") is not None
    source_id = str(args.get("source_id", "")).strip() if has_source_id else ""
    fallback_source_id = (default_source_id or "").strip()
    if has_source_id and not source_id and not fallback_source_id:
        return "source_id cannot be empty"
    if not source_id and not fallback_source_id:
        return "source_id is required"

    if "sql" not in args or args["sql"] is None:
        return "sql is required"
    sql = str(args["sql"]).strip()
    if not sql:
        return "sql cannot be empty"

    limit_val = args.get("limit", default_limit)
    try:
        limit = int(limit_val)
    except (TypeError, ValueError):
        return f"limit must be an integer between {LIMIT_MIN} and {LIMIT_MAX}"
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        return f"limit must be between {LIMIT_MIN} and {LIMIT_MAX}, got {limit}"

    return None


class QueryDataTool(Tool):
    def __init__(
        self,
        router: DataSourceRouter,
        default_limit: int = LIMIT_DEFAULT,
        allowed_sql_keywords: list[str] | None = None,
    ) -> None:
        self._router = router
        self._default_limit = default_limit
        if allowed_sql_keywords is not None:
            self._allowed_sql_keywords = list(allowed_sql_keywords)
        else:
            from mine_agent.config.settings import AppSettings

            self._allowed_sql_keywords = AppSettings.from_env().allowed_sql_keywords

    @property
    def name(self) -> str:
        return "query_data"

    @property
    def description(self) -> str:
        return "Execute SQL against a registered data source."

    def get_args_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "sql": {
                        "type": "string",
                        "description": "Read-only SELECT/WITH SQL statement.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": LIMIT_MIN,
                        "maximum": LIMIT_MAX,
                        "description": "Maximum rows to return",
                    },
                },
                "required": ["sql"],
            },
        )

    async def execute(self, args: Dict[str, Any], context: ToolContext) -> ToolResult:
        default_source_id = str(context.metadata.get("default_source_id", "")).strip()
        err = _validate_args(
            args=args, default_source_id=default_source_id, default_limit=self._default_limit
        )
        source_id = str(args.get("source_id", "")).strip() or default_source_id
        sql = str(args.get("sql", "")).strip()
        user_id = context.user_id if context else None

        if err:
            audit_query_event(
                user_id=user_id,
                source_id=source_id or "unknown",
                sql=sql or "(validation failed before sql)",
                row_count=None,
                status="failure",
            )
            return ToolResult(
                content=f"Parameter validation failed: {err}",
                metadata={"source_id": source_id},
            )

        try:
            validate_readonly_sql(sql, allowed_start_keywords=self._allowed_sql_keywords)
        except SqlValidationError as e:
            audit_query_event(
                user_id=user_id,
                source_id=source_id,
                sql=sql,
                row_count=None,
                status="failure",
            )
            return ToolResult(
                content=f"SQL validation failed: {e!s}",
                metadata={"source_id": source_id, "status": "validation_failed"},
            )

        limit = int(args.get("limit", self._default_limit))
        request = QueryRequest(source_id=source_id, sql=sql, limit=limit)

        try:
            result = await self._router.execute_query(request=request)
        except DataSourceError as e:
            audit_query_event(
                user_id=user_id,
                source_id=source_id,
                sql=sql,
                row_count=None,
                status="failure",
            )
            return ToolResult(
                content=f"{e.error_code}: {e.message}",
                metadata={"source_id": source_id},
            )
        except Exception as e:
            audit_query_event(
                user_id=user_id,
                source_id=source_id,
                sql=sql,
                row_count=None,
                status="failure",
            )
            return ToolResult(
                content=f"Query execution failed: {e!s}",
                metadata={"source_id": source_id},
            )

        audit_query_event(
            user_id=user_id,
            source_id=source_id,
            sql=sql,
            row_count=result.row_count,
            status="success",
        )
        return ToolResult(
            content=_render_query_result(
                source_id=request.source_id,
                rows=result.rows,
                row_count=result.row_count,
                columns=result.columns,
            ),
            metadata={
                "source_id": request.source_id,
                "row_count": result.row_count,
                "rows": result.rows,
            },
        )

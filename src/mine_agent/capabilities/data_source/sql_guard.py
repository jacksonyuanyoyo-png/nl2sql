"""
SQL security guard: read-only validation and schema whitelist.

Provides normalize_sql, validate_readonly_sql, validate_allowed_schemas
for Tool/Adapter layer to enforce safe query execution.
"""

from __future__ import annotations

import re
from typing import Iterable, List

try:
    from mine_agent.capabilities.data_source.errors import SqlValidationError
except ImportError:
    # Fallback when errors module not yet integrated
    class SqlValidationError(Exception):
        """Raised when SQL fails security validation (read-only or schema)."""

        pass


# Keywords that indicate write/DML/DDL operations - must not appear as statement starters
_FORBIDDEN_START_KEYWORDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "MERGE",
        "TRUNCATE",
        "CREATE",
        "ALTER",
        "DROP",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "CALL",
    }
)

# Default allowed statement starters (read-only). Configurable per app/datasource.
# Includes metadata commands for MySQL (DESC/DESCRIBE/SHOW) and Snowflake (DESCRIBE/SHOW).
DEFAULT_ALLOWED_START_KEYWORDS = frozenset(
    {"SELECT", "WITH", "DESCRIBE", "DESC", "SHOW", "EXPLAIN"}
)


def _strip_string_literals(sql: str) -> str:
    """
    Replace single-quoted string literals with placeholders.
    Double-quoted identifiers are preserved (SQL standard).
    """
    result = []
    i = 0
    placeholder_idx = 0
    while i < len(sql):
        if sql[i] == "'":
            # Single-quoted string (handle '' escape)
            i += 1
            while i < len(sql):
                if sql[i] == "'" and (i + 1 >= len(sql) or sql[i + 1] != "'"):
                    i += 1
                    break
                if sql[i] == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
                    i += 2
                    continue
                i += 1
            result.append(f"__STR{placeholder_idx}__")
            placeholder_idx += 1
            continue
        result.append(sql[i])
        i += 1
    return "".join(result)


def _strip_comments(sql: str) -> str:
    """Remove single-line (--) and multi-line (/* */) comments."""
    # Multi-line first
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    # Single-line
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def normalize_sql(sql: str) -> str:
    """
    Normalize SQL for validation: strip comments, collapse whitespace, trim.

    Does not alter semantics. Used as preprocessing before validate_*.
    """
    if not sql or not sql.strip():
        return ""
    s = _strip_comments(sql)
    s = " ".join(s.split())
    return s.strip()


def _get_first_keyword(normalized: str) -> str | None:
    """Extract the first alphanumeric keyword from normalized SQL."""
    normalized = _strip_string_literals(normalized)
    normalized = _strip_comments(normalized)
    normalized = " ".join(normalized.split()).strip()
    match = re.match(r"^(\w+)", normalized, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _get_statement_start_keywords(normalized: str) -> List[str]:
    """
    Get the first keyword of each semicolon-separated statement.
    Used to reject multi-statement SQL with any write operation.
    """
    normalized = _strip_string_literals(normalized)
    normalized = _strip_comments(normalized)
    keywords = []
    for stmt in normalized.split(";"):
        stmt = " ".join(stmt.split()).strip()
        if not stmt:
            continue
        match = re.match(r"^(\w+)", stmt, re.IGNORECASE)
        if match:
            keywords.append(match.group(1).upper())
    return keywords


def validate_readonly_sql(
    sql: str,
    allowed_start_keywords: Iterable[str] | None = None,
) -> None:
    """
    Ensure SQL is read-only: statement starters must be in allowed set.

    By default allows: SELECT, WITH, DESCRIBE, DESC, SHOW, EXPLAIN (suitable for
    Oracle, MySQL, Snowflake metadata queries). Pass allowed_start_keywords to
    override (e.g. from config or per-datasource).

    Rejects: INSERT, UPDATE, DELETE, MERGE, DDL, GRANT, REVOKE, TRUNCATE,
    ALTER, DROP, EXEC, EXECUTE, CALL, etc.

    Raises:
        SqlValidationError: if any statement is not read-only.
    """
    normalized = normalize_sql(sql)
    if not normalized:
        raise SqlValidationError("Empty SQL")

    keywords = _get_statement_start_keywords(normalized)
    if not keywords:
        raise SqlValidationError("No valid statement found")

    allowed = (
        frozenset(k.upper() for k in allowed_start_keywords)
        if allowed_start_keywords is not None
        else DEFAULT_ALLOWED_START_KEYWORDS
    )
    allowed_list = ", ".join(sorted(allowed))

    for kw in keywords:
        if kw in _FORBIDDEN_START_KEYWORDS:
            raise SqlValidationError(f"Forbidden keyword: {kw}")
        if kw not in allowed:
            raise SqlValidationError(
                f"Statement must start with one of [{allowed_list}], got: {kw}"
            )


def _extract_schema_refs(sql: str) -> List[str]:
    """
    Extract schema names from table references in FROM/JOIN clauses.
    Supports schema.table and db.schema.table. Strips string literals first.
    """
    s = _strip_string_literals(sql)
    schemas: List[str] = []
    # FROM/JOIN schema.table (2-part)
    for m in re.finditer(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\s|$|,|\)|;)",
        s,
        re.IGNORECASE,
    ):
        schemas.append(m.group(1).upper())
    # FROM/JOIN db.schema.table (3-part) -> schema is middle
    for m in re.finditer(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\s|$|,|\)|;)",
        s,
        re.IGNORECASE,
    ):
        schemas.append(m.group(2).upper())
    # Quoted "schema"."table" after FROM/JOIN
    for m in re.finditer(
        r'\b(?:FROM|JOIN)\s+"([^"]+)"\s*\.\s*"(?:[^"]+)"',
        s,
    ):
        schemas.append(m.group(1).upper())
    return list(dict.fromkeys(schemas))


def validate_allowed_schemas(sql: str, allowed_schemas: List[str] | None) -> None:
    """
    Ensure all schema references in SQL are in the whitelist.

    Extracts schema.table and "schema"."table" patterns. If allowed_schemas
    is None, no restriction is applied.

    Raises:
        SqlValidationError: if a schema is used that is not in allowed_schemas.
    """
    if allowed_schemas is None:
        return

    normalized = normalize_sql(sql)
    if not normalized:
        return

    refs = _extract_schema_refs(normalized)
    allowed_upper = {s.upper() for s in allowed_schemas}

    for schema in refs:
        if schema not in allowed_upper:
            raise SqlValidationError(f"Schema not allowed: {schema}")

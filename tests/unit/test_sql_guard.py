"""
Unit tests for SQL guard: normalize_sql, validate_readonly_sql, validate_allowed_schemas.
"""

from __future__ import annotations

import pytest

from mine_agent.capabilities.data_source.sql_guard import (
    SqlValidationError,
    normalize_sql,
    validate_allowed_schemas,
    validate_readonly_sql,
)


# --- normalize_sql ---


def test_normalize_sql_collapses_whitespace() -> None:
    assert normalize_sql("  SELECT   *   FROM   t  ") == "SELECT * FROM t"


def test_normalize_sql_strips_single_line_comments() -> None:
    assert normalize_sql("SELECT 1 -- comment") == "SELECT 1"


def test_normalize_sql_strips_multi_line_comments() -> None:
    assert normalize_sql("SELECT /* inline */ 1") == "SELECT 1"
    assert normalize_sql("SELECT 1 /* multi\nline */ FROM t") == "SELECT 1 FROM t"


def test_normalize_sql_empty() -> None:
    assert normalize_sql("") == ""
    assert normalize_sql("   \n\t  ") == ""


# --- validate_readonly_sql: success ---


def test_validate_readonly_sql_select_passes() -> None:
    validate_readonly_sql("SELECT * FROM t")
    validate_readonly_sql("select * from t")


def test_validate_readonly_sql_with_cte_passes() -> None:
    validate_readonly_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")
    validate_readonly_sql("with cte as (select 1) select * from cte")


def test_validate_readonly_sql_multiple_selects_passes() -> None:
    validate_readonly_sql("SELECT 1; SELECT 2")


def test_validate_readonly_sql_string_with_keyword_passes() -> None:
    validate_readonly_sql("SELECT 'INSERT INTO x' AS txt FROM t")


# --- validate_readonly_sql: failure ---


def test_validate_readonly_sql_empty_raises() -> None:
    with pytest.raises(SqlValidationError, match="Empty SQL"):
        validate_readonly_sql("")
    with pytest.raises(SqlValidationError, match="Empty SQL"):
        validate_readonly_sql("   ")


def test_validate_readonly_sql_insert_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: INSERT"):
        validate_readonly_sql("INSERT INTO t VALUES (1)")


def test_validate_readonly_sql_update_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: UPDATE"):
        validate_readonly_sql("UPDATE t SET x = 1")


def test_validate_readonly_sql_delete_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: DELETE"):
        validate_readonly_sql("DELETE FROM t")


def test_validate_readonly_sql_merge_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: MERGE"):
        validate_readonly_sql("MERGE INTO t USING s ON ...")


def test_validate_readonly_sql_drop_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: DROP"):
        validate_readonly_sql("DROP TABLE t")


def test_validate_readonly_sql_truncate_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: TRUNCATE"):
        validate_readonly_sql("TRUNCATE TABLE t")


def test_validate_readonly_sql_alter_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: ALTER"):
        validate_readonly_sql("ALTER TABLE t ADD COLUMN x INT")


def test_validate_readonly_sql_grant_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: GRANT"):
        validate_readonly_sql("GRANT SELECT ON t TO u")


def test_validate_readonly_sql_revoke_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: REVOKE"):
        validate_readonly_sql("REVOKE SELECT ON t FROM u")


def test_validate_readonly_sql_create_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: CREATE"):
        validate_readonly_sql("CREATE TABLE t (x INT)")


def test_validate_readonly_sql_second_statement_dangerous_raises() -> None:
    with pytest.raises(SqlValidationError, match="Forbidden keyword: DROP"):
        validate_readonly_sql("SELECT 1; DROP TABLE t")


def test_validate_readonly_sql_describe_show_pass_with_default() -> None:
    """With default allowed keywords, DESCRIBE/DESC/SHOW/EXPLAIN are allowed."""
    validate_readonly_sql("DESCRIBE t")
    validate_readonly_sql("DESC my_table")
    validate_readonly_sql("SHOW TABLES")
    validate_readonly_sql("EXPLAIN SELECT 1")


def test_validate_readonly_sql_custom_allowed_keywords() -> None:
    """When allowed_start_keywords is provided, only those are accepted."""
    strict = ["SELECT", "WITH"]
    validate_readonly_sql("SELECT 1", allowed_start_keywords=strict)
    validate_readonly_sql("WITH cte AS (SELECT 1) SELECT * FROM cte", allowed_start_keywords=strict)
    with pytest.raises(SqlValidationError, match="must start with one of"):
        validate_readonly_sql("DESCRIBE t", allowed_start_keywords=strict)
    with pytest.raises(SqlValidationError, match="must start with one of"):
        validate_readonly_sql("SHOW TABLES", allowed_start_keywords=strict)


def test_validate_readonly_sql_unknown_keyword_raises() -> None:
    """Truly unknown statement starter raises (e.g. when using strict SELECT,WITH only)."""
    with pytest.raises(SqlValidationError, match="must start with one of"):
        validate_readonly_sql("FOO bar", allowed_start_keywords=["SELECT", "WITH"])


# --- validate_allowed_schemas: success ---


def test_validate_allowed_schemas_none_skips() -> None:
    validate_allowed_schemas("SELECT * FROM schema1.t", None)
    validate_allowed_schemas("SELECT * FROM any_schema.any_table", None)


def test_validate_allowed_schemas_single_schema_passes() -> None:
    validate_allowed_schemas("SELECT * FROM allowed.t", ["allowed"])
    validate_allowed_schemas("SELECT * FROM ALLOWED.t", ["allowed"])


def test_validate_allowed_schemas_multiple_schemas_passes() -> None:
    validate_allowed_schemas(
        "SELECT * FROM s1.t1 JOIN s2.t2 ON t1.id = t2.id",
        ["s1", "s2"],
    )


def test_validate_allowed_schemas_no_schema_ref_passes() -> None:
    validate_allowed_schemas("SELECT 1", ["any"])
    validate_allowed_schemas("SELECT * FROM t", ["any"])


def test_validate_allowed_schemas_quoted_schema_passes() -> None:
    validate_allowed_schemas('SELECT * FROM "MySchema"."MyTable"', ["MySchema"])


# --- validate_allowed_schemas: failure ---


def test_validate_allowed_schemas_forbidden_schema_raises() -> None:
    with pytest.raises(SqlValidationError, match="Schema not allowed: FORBIDDEN"):
        validate_allowed_schemas("SELECT * FROM forbidden.t", ["allowed"])


def test_validate_allowed_schemas_one_of_two_forbidden_raises() -> None:
    with pytest.raises(SqlValidationError, match="Schema not allowed: S2"):
        validate_allowed_schemas(
            "SELECT * FROM s1.t1 JOIN s2.t2 ON t1.id = t2.id",
            ["s1"],
        )


def test_validate_allowed_schemas_empty_list_rejects_any_schema() -> None:
    with pytest.raises(SqlValidationError, match="Schema not allowed"):
        validate_allowed_schemas("SELECT * FROM any_schema.t", [])

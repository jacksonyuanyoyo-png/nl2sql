from __future__ import annotations

import hashlib
import logging
from typing import Optional


AUDIT_LOGGER_NAME = "mine_agent.audit"


def sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def audit_query_event(
    *,
    user_id: Optional[str],
    source_id: str,
    sql: str,
    row_count: Optional[int],
    status: str,
) -> None:
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    logger.info(
        "query_event",
        extra={
            "user_id": user_id or "anonymous",
            "source_id": source_id,
            "sql_hash": sql_hash(sql),
            "row_count": row_count if row_count is not None else -1,
            "status": status,
        },
    )

from __future__ import annotations

import json
import logging
from typing import Any, Dict

# Python LogRecord 标准属性，extra 传入的字段不在此列
_LOG_RECORD_STANDARD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",  # getMessage() 写入
        "taskName",  # asyncio
        "processId",  # 某些版本
    }
)

# 敏感字段：精确匹配，不输出完整 SQL、完整 row 数据等
_SENSITIVE_KEYS = frozenset(
    {
        "sql",
        "query",
        "row",
        "rows",
        "result",
        "content",
        "user_message",
        "assistant_content",
        "tool_outputs",
        "schema_context",
    }
)


def _is_safe_for_log(key: str, value: Any) -> bool:
    """排除敏感字段，不输出完整 SQL、完整 row 数据。"""
    if key in _SENSITIVE_KEYS:
        return False
    if isinstance(value, str) and len(value) > 512:
        return False
    return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 遍历 record.__dict__，排除标准 logging 字段，将其余加入 payload
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_STANDARD_ATTRS:
                continue
            if not _is_safe_for_log(key, value):
                continue
            payload[key] = value

        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers:
        handler.setFormatter(JsonLogFormatter())

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        root.addHandler(handler)

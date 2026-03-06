"""Knowledge JSON storage per source_id. Embedding config is locked after first vectorize."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _knowledge_dir() -> Path:
    base = os.getenv("MINE_CONFIG_DIR", os.path.expanduser("~/.mine"))
    d = Path(base) / "knowledge"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _knowledge_path(source_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source_id)
    return _knowledge_dir() / f"{safe}.json"


def _embedding_config_path(source_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source_id)
    return _knowledge_dir() / f"{safe}.embedding.json"


def load_embedding_config(source_id: str) -> Optional[Dict[str, Any]]:
    """加载已锁定的 embedding 配置，若存在则不可更改。"""
    path = _embedding_config_path(source_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_embedding_config(source_id: str, vendor: str, model: str) -> None:
    """保存并锁定 embedding 配置，一旦保存则不可更改。"""
    path = _embedding_config_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"vendor": vendor, "model": model, "locked": True}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_knowledge(source_id: str) -> Optional[Dict[str, Any]]:
    path = _knowledge_path(source_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_knowledge(source_id: str, data: Dict[str, Any]) -> None:
    path = _knowledge_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

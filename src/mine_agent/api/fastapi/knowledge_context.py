"""Knowledge-to-chat context bridge: chunking, retrieval, and fallback prompt context."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

from mine_agent.api.fastapi.knowledge_store import load_knowledge
from mine_agent.core.embedding.base import EmbeddingService
from mine_agent.core.vector.base import VectorStore


def build_knowledge_chunks(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Turn knowledge JSON into (chunk_id, text) chunks for embedding/retrieval."""
    chunks: List[Tuple[str, str]] = []
    tables = data.get("tables") or []
    for t in tables:
        name = t.get("name", "?")
        desc = t.get("description", "")
        cols = t.get("columns") or []
        col_str = ", ".join(f"{c.get('name', '')}({c.get('type', '')})" for c in cols)
        text = f"Table: {name}. {desc}. Columns: {col_str}".strip()
        chunks.append((f"table:{name}", text))

    join_paths = data.get("join_paths") or []
    for i, j in enumerate(join_paths):
        text = str(j.get("description", j))
        chunks.append((f"join:{i}", text))

    er_graph = data.get("er_graph") or {}
    er_edges = er_graph.get("edges") or []
    seen_join_keys = {
        (
            (j.get("from") or {}).get("table"),
            (j.get("from") or {}).get("column"),
            (j.get("to") or {}).get("table"),
            (j.get("to") or {}).get("column"),
        )
        for j in join_paths
    }
    for i, e in enumerate(er_edges):
        src = e.get("source", "?")
        tgt = e.get("target", "?")
        src_col = e.get("source_column") or ""
        tgt_col = e.get("target_column") or ""
        key = (src, src_col or None, tgt, tgt_col or None)
        if key in seen_join_keys:
            continue
        seen_join_keys.add(key)
        parts = [f"{src}"]
        if src_col:
            parts.append(src_col)
        parts.append("->")
        parts.append(tgt)
        if tgt_col:
            parts.append(tgt_col)
        text = " ".join(parts)
        if len(text) > 500:
            text = text[:500]
        chunks.append((f"er_edge:{i}", text))

    if not chunks:
        chunks.append(("summary", str(data)[:2000]))
    return chunks


def build_schema_fallback_context(data: Dict[str, Any], max_tables: int = 8) -> str:
    """Fallback context from knowledge JSON when vector retrieval is unavailable."""
    lines: List[str] = []
    tables = data.get("tables") or []
    for t in tables[:max_tables]:
        name = t.get("name", "?")
        cols = t.get("columns") or []
        col_names = [str(c.get("name", "")) for c in cols[:12] if c.get("name")]
        if col_names:
            lines.append(f"- {name}: {', '.join(col_names)}")
        else:
            lines.append(f"- {name}")

    join_paths = data.get("join_paths") or []
    for j in join_paths[:8]:
        desc = str(j.get("description", "")).strip()
        if desc:
            lines.append(f"- join: {desc}")
    return "\n".join(lines)


async def build_chat_knowledge_context(
    *,
    source_id: str | None,
    user_message: str,
    embedding_service: EmbeddingService | None,
    vector_store: VectorStore | None,
    top_k: int = 8,
) -> str:
    """
    Retrieve schema-aware context for NL2SQL from vectorized knowledge.

    If vector retrieval fails or no vectors are found, fallback to knowledge JSON summary.
    """
    sid = (source_id or "").strip()
    if not sid:
        return ""
    data = load_knowledge(sid)
    if data is None:
        return ""

    chunks = build_knowledge_chunks(data)
    chunk_by_id = {cid: text for cid, text in chunks}
    snippets: List[str] = []

    if embedding_service is not None and vector_store is not None and user_message.strip():
        try:
            query_vecs = await asyncio.to_thread(embedding_service.embed, [user_message])
            query_vec = query_vecs[0] if query_vecs else []
            if query_vec:
                namespace = f"knowledge:{sid}"
                neighbors = vector_store.search(namespace=namespace, vector=query_vec, top_k=top_k)
                for chunk_id, meta in neighbors:
                    text = str(meta.get("text", "")).strip() if isinstance(meta, dict) else ""
                    if not text:
                        text = chunk_by_id.get(chunk_id, "")
                    if text:
                        snippets.append(text)
        except Exception:
            # Keep chat available even when retrieval fails.
            pass

    if not snippets:
        snippets = [text for _, text in chunks[:top_k] if text]
    if not snippets:
        fallback = build_schema_fallback_context(data)
        snippets = [fallback] if fallback else []
    if not snippets:
        return ""

    deduped: List[str] = []
    seen = set()
    for s in snippets:
        if s in seen:
            continue
        seen.add(s)
        deduped.append(s)

    return "## Schema Context (retrieved from knowledge base)\n" + "\n".join(
        f"- {s}" for s in deduped[:top_k]
    )

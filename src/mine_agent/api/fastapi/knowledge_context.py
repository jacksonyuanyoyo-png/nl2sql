"""Knowledge-to-chat context bridge: chunking, retrieval, and fallback prompt context."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from mine_agent.api.fastapi.knowledge_store import load_knowledge
from mine_agent.core.embedding.base import EmbeddingService
from mine_agent.core.vector.base import VectorStore


def _parse_bool(val: str | None, default: bool) -> bool:
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _parse_int(val: str | None, default: int) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default


# RAG 配置：通过环境变量控制，knowledge_context 内直接读取
MINE_RAG_HYBRID_ENABLED = _parse_bool(os.getenv("MINE_RAG_HYBRID_ENABLED"), True)
MINE_RAG_TOPK_LARGE = _parse_int(os.getenv("MINE_RAG_TOPK_LARGE"), 24)
MINE_RAG_TOPK_FINAL = _parse_int(os.getenv("MINE_RAG_TOPK_FINAL"), 12)
MINE_RAG_GRAPH_EXPAND_ENABLED = _parse_bool(os.getenv("MINE_RAG_GRAPH_EXPAND_ENABLED"), True)
MINE_RAG_CONFIDENCE_GUARD_ENABLED = _parse_bool(os.getenv("MINE_RAG_CONFIDENCE_GUARD_ENABLED"), True)

logger = logging.getLogger(__name__)

# Default priority by chunk_type: table=2, join=2, domain=1, er_edge=1
_DEFAULT_PRIORITY: Dict[str, int] = {
    "table": 2,
    "join": 2,
    "domain": 1,
    "er_edge": 1,
    "summary": 0,
}


@dataclass
class KnowledgeChunk:
    """Chunk with metadata. Unpacks to (chunk_id, text) for backward compatibility."""

    chunk_id: str
    text: str
    metadata: Dict[str, Any]

    def __iter__(self):
        yield self.chunk_id
        yield self.text

    def __getitem__(self, index: int) -> str:
        """Support chunks[i][0] / chunks[i][1] style access."""
        if index == 0:
            return self.chunk_id
        if index == 1:
            return self.text
        raise IndexError(f"KnowledgeChunk index {index} out of range")


def build_knowledge_chunks(data: Dict[str, Any]) -> List[KnowledgeChunk]:
    """Turn knowledge JSON into chunks with metadata for embedding/retrieval.

    Returns List[KnowledgeChunk]. Each chunk has metadata:
    - chunk_type: table | domain | join | er_edge | summary
    - table_refs: list of table names
    - column_refs: list of column names
    - keywords: business terms (default [])
    - priority: table=2, join=2, domain=1, er_edge=1

    Compatible with `for chunk_id, text in chunks` (unpacks to chunk_id, text).
    """
    chunks: List[KnowledgeChunk] = []
    tables = data.get("tables") or []
    for t in tables:
        name = t.get("name", "?")
        desc = t.get("description", "")
        cols = t.get("columns") or []
        col_parts = []
        col_names: List[str] = []
        for c in cols:
            n = c.get("name", "") if isinstance(c, dict) else str(c)
            ty = c.get("type", "") if isinstance(c, dict) else ""
            d = c.get("description", "") if isinstance(c, dict) else ""
            if n:
                col_names.append(n)
            part = f"{n}({ty})" + (f": {d}" if d else "")
            col_parts.append(part)
        col_str = ", ".join(col_parts)
        text = f"Table: {name}. {desc}. Columns: {col_str}".strip()
        meta = {
            "chunk_type": "table",
            "table_refs": [name],
            "column_refs": col_names,
            "keywords": [],
            "priority": _DEFAULT_PRIORITY["table"],
        }
        chunks.append(KnowledgeChunk(f"table:{name}", text, meta))

    # Domain/group chunks (from er_graph.nodes[].group)
    er_graph = data.get("er_graph") or {}
    er_nodes = er_graph.get("nodes") or []
    group_to_tables: Dict[str, List[str]] = {}
    for n in er_nodes:
        grp = n.get("group") or ""
        if not grp:
            continue
        tname = n.get("table") or n.get("id") or n.get("label") or ""
        if tname:
            group_to_tables.setdefault(grp, []).append(tname)
    for grp_name, tbls in group_to_tables.items():
        tbl_str = ", ".join(sorted(tbls))
        text = f"Domain: {grp_name}. Tables: {tbl_str}."
        meta = {
            "chunk_type": "domain",
            "table_refs": sorted(tbls),
            "column_refs": [],
            "keywords": [grp_name],
            "priority": _DEFAULT_PRIORITY["domain"],
        }
        chunks.append(KnowledgeChunk(f"domain:{grp_name}", text, meta))

    join_paths = data.get("join_paths") or []
    for i, j in enumerate(join_paths):
        text = str(j.get("description", j))
        fr = j.get("from") or {}
        to = j.get("to") or {}
        tbl_from = fr.get("table") or ""
        tbl_to = to.get("table") or ""
        col_from = fr.get("column") or ""
        col_to = to.get("column") or ""
        table_refs = [t for t in (tbl_from, tbl_to) if t]
        column_refs = [c for c in (col_from, col_to) if c]
        meta = {
            "chunk_type": "join",
            "table_refs": list(dict.fromkeys(table_refs)),
            "column_refs": column_refs,
            "keywords": [],
            "priority": _DEFAULT_PRIORITY["join"],
        }
        chunks.append(KnowledgeChunk(f"join:{i}", text, meta))

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
        table_refs = [t for t in (src, tgt) if t and t != "?"]
        column_refs = [c for c in (src_col, tgt_col) if c]
        meta = {
            "chunk_type": "er_edge",
            "table_refs": table_refs,
            "column_refs": column_refs,
            "keywords": [],
            "priority": _DEFAULT_PRIORITY["er_edge"],
        }
        chunks.append(KnowledgeChunk(f"er_edge:{i}", text, meta))

    if not chunks:
        meta = {
            "chunk_type": "summary",
            "table_refs": [],
            "column_refs": [],
            "keywords": [],
            "priority": _DEFAULT_PRIORITY["summary"],
        }
        chunks.append(KnowledgeChunk("summary", str(data)[:2000], meta))
    return chunks


def _infer_chunk_type(snippet: str) -> str:
    """Infer chunk type from snippet content when chunk_infos is not available."""
    s = snippet.strip()
    if s.startswith("Table: "):
        return "table"
    if s.startswith("Domain: "):
        return "domain"
    if s.startswith("- join: ") or (s.startswith("- ") and " join:" in s[:20]):
        return "join"
    if " -> " in s and not s.startswith("- join:"):
        return "edge"
    if s.startswith("- ") and ": " in s:
        return "table"
    return "other"


def _format_structured_schema_context(
    snippets: List[str],
    chunk_infos: Optional[List[Dict[str, Any]]] = None,
    low_confidence: bool = False,
) -> str:
    """
    Format snippets into structured schema context sections.

    Groups snippets by type (table/join/domain/edge) and outputs:
    ## Candidate Tables, ## Recommended Join Paths, ## Domain Hints, ## SQL Constraints.
    When low_confidence=True, appends a clarification prompt to SQL Constraints.
    """
    tables: List[str] = []
    joins: List[str] = []
    domains: List[str] = []
    edges: List[str] = []

    for i, text in enumerate(snippets):
        if not text or not text.strip():
            continue
        chunk_id: Optional[str] = None
        if chunk_infos and i < len(chunk_infos):
            info = chunk_infos[i]
            if isinstance(info, dict):
                chunk_id = info.get("chunk_id") if isinstance(info.get("chunk_id"), str) else None

        if chunk_id:
            if chunk_id.startswith("table:"):
                tables.append(text.strip())
            elif chunk_id.startswith("join:"):
                joins.append(text.strip())
            elif chunk_id.startswith("domain:"):
                domains.append(text.strip())
            elif chunk_id.startswith("er_edge:"):
                edges.append(text.strip())
        else:
            t = _infer_chunk_type(text)
            stripped = text.strip()
            if t == "table":
                tables.append(stripped)
            elif t == "join":
                joins.append(stripped)
            elif t == "domain":
                domains.append(stripped)
            elif t == "edge":
                edges.append(stripped)

    lines: List[str] = ["## Schema Context\n"]
    if tables:
        lines.append("## Candidate Tables")
        for t in tables:
            lines.append(f"- {t}")
        lines.append("")
    if joins:
        lines.append("## Recommended Join Paths")
        for j in joins:
            lines.append(f"- {j}")
        lines.append("")
    if domains:
        lines.append("## Domain Hints")
        for d in domains:
            lines.append(f"- {d}")
        lines.append("")
    lines.append("## SQL Constraints")
    if low_confidence:
        lines.append("- 若 schema 覆盖不足，仅使用已确认表，必要时先澄清再生成 SQL")
    if not tables and not joins and not domains:
        lines.append("- 基于上述检索结果生成 SQL")
    return "\n".join(lines).rstrip()


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


def _retrieve_candidates(
    vector_store: VectorStore,
    namespace: str,
    query_vec: List[float],
    top_k_large: int = 24,
) -> List[Tuple[str, Dict[str, Any], float]]:
    """向量召回候选，返回 (chunk_id, metadata, score) 列表。"""
    if hasattr(vector_store, "search_with_score"):
        return vector_store.search_with_score(namespace, query_vec, top_k_large)
    results = vector_store.search(namespace, query_vec, top_k_large)
    return [(cid, meta, 1.0) for cid, meta in results]


@dataclass
class RetrievedChunkInfo:
    """单条检索 chunk 的结构化信息，用于 retrieval_trace。"""

    chunk_id: str
    chunk_type: str
    text: str
    score: Optional[float]
    table_refs: List[str]
    column_refs: List[str]


@dataclass
class ChatContextResult:
    """build_chat_knowledge_context 的返回结果，含 prompt_context 与 retrieval_trace。"""

    prompt_context: str
    retrieval_trace: Dict[str, Any]


def _parse_chunk_type(chunk_id: str) -> Tuple[str, str]:
    """解析 chunk_id 前缀，返回 (type, rest)。类型: table, join, domain, er_edge。"""
    for prefix in ("table:", "join:", "domain:", "er_edge:"):
        if chunk_id.startswith(prefix):
            return prefix.rstrip(":"), chunk_id[len(prefix) :]
    return "other", chunk_id


def _rerank_with_quota(
    candidates: List[Tuple[str, Dict[str, Any], float]],
    chunk_by_id: Dict[str, str],
    min_tables: int = 2,
    min_joins: int = 2,
    max_domain_ratio: float = 0.3,
) -> List[str]:
    """
    按类型配额重排：chunk_id 前缀可解析 table/join/domain/er_edge。
    确保至少 min_tables 个表、min_joins 个 join/er_edge，domain 占比不超过 max_domain_ratio。
    返回选中的 chunk_id 列表（保持分数顺序，优先满足配额）。
    """
    by_type: Dict[str, List[Tuple[str, Dict[str, Any], float]]] = {
        "table": [],
        "join": [],
        "domain": [],
        "er_edge": [],
        "other": [],
    }
    for cid, meta, score in candidates:
        t, _ = _parse_chunk_type(cid)
        by_type.setdefault(t, []).append((cid, meta, score))

    selected: List[str] = []
    seen = set()

    def add_one(lst: List[Tuple[str, Dict[str, Any], float]]) -> bool:
        for cid, _, _ in lst:
            if cid not in seen:
                seen.add(cid)
                selected.append(cid)
                return True
        return False

    # 1. 先满足 min_tables
    for _ in range(min_tables):
        add_one(by_type["table"])

    # 2. 满足 min_joins（join 与 er_edge 合并计数）
    join_or_edge = by_type["join"] + by_type["er_edge"]
    join_or_edge.sort(key=lambda x: x[2], reverse=True)
    for _ in range(min_joins):
        if join_or_edge:
            add_one(join_or_edge)

    # 3. 按分数补其余，但 domain 不超过 max_domain_ratio
    remaining = []
    for t, lst in by_type.items():
        for item in lst:
            if item[0] not in seen:
                remaining.append((item[0], item[1], item[2], t))
    remaining.sort(key=lambda x: x[2], reverse=True)

    max_domain = max(1, int((len(selected) + len(remaining)) * max_domain_ratio))
    domain_count = sum(1 for s in selected if _parse_chunk_type(s)[0] == "domain")
    for cid, _, _, t in remaining:
        if cid in seen:
            continue
        if t == "domain" and domain_count >= max_domain:
            continue
        seen.add(cid)
        selected.append(cid)
        if t == "domain":
            domain_count += 1

    return selected


def _expand_by_graph(
    selected_ids: List[str],
    chunk_by_id: Dict[str, str],
    data: Dict[str, Any],
) -> List[str]:
    """
    命中 join 或 er_edge 时，补齐两侧表 chunk。
    从 join_paths 和 er_graph.edges 获取 from/to 表。
    """
    tables_to_add: set[str] = set()
    join_paths = data.get("join_paths") or []
    er_graph = data.get("er_graph") or {}
    er_edges = er_graph.get("edges") or []
    existing_tables = {r[len("table:") :] for r in selected_ids if r.startswith("table:")}

    for cid in selected_ids:
        t, rest = _parse_chunk_type(cid)
        if t == "join":
            try:
                idx = int(rest)
                if 0 <= idx < len(join_paths):
                    j = join_paths[idx]
                    fr = (j.get("from") or {}).get("table") or ""
                    to_tbl = (j.get("to") or {}).get("table") or ""
                    if fr and fr not in existing_tables:
                        tables_to_add.add(fr)
                    if to_tbl and to_tbl not in existing_tables:
                        tables_to_add.add(to_tbl)
            except ValueError:
                pass
        elif t == "er_edge":
            try:
                idx = int(rest)
                if 0 <= idx < len(er_edges):
                    e = er_edges[idx]
                    src = e.get("source") or ""
                    tgt = e.get("target") or ""
                    if src and src not in existing_tables:
                        tables_to_add.add(src)
                    if tgt and tgt not in existing_tables:
                        tables_to_add.add(tgt)
            except ValueError:
                pass

    out = list(selected_ids)
    for tname in tables_to_add:
        tid = f"table:{tname}"
        if tid in chunk_by_id and tid not in {s for s in selected_ids}:
            out.append(tid)
    return out


def _empty_retrieval_trace(context_str: str = "") -> Dict[str, Any]:
    """空 retrieval_trace 结构。"""
    return {
        "prompt_context": context_str,
        "retrieved_chunks": [],
        "table_count": 0,
        "join_count": 0,
    }


async def build_chat_knowledge_context(
    *,
    source_id: str | None,
    user_message: str,
    embedding_service: EmbeddingService | None,
    vector_store: VectorStore | None,
    top_k: int = 8,
) -> ChatContextResult:
    """
    Retrieve schema-aware context for NL2SQL from vectorized knowledge.

    If vector retrieval fails or no vectors are found, fallback to knowledge JSON summary.
    Returns ChatContextResult(prompt_context, retrieval_trace). 调用方可只用 prompt_context，
    或使用 retrieval_trace 传给下游用于 trace visibility。
    """
    sid = (source_id or "").strip()
    if not sid:
        return ChatContextResult("", _empty_retrieval_trace())
    data = load_knowledge(sid)
    if data is None:
        return ChatContextResult("", _empty_retrieval_trace())

    chunks = build_knowledge_chunks(data)
    chunk_by_id = {cid: text for cid, text in chunks}
    chunk_by_meta = {c.chunk_id: c.metadata for c in chunks}
    snippets: List[str] = []
    hit_chunk_ids: List[str] = []
    id_to_score: Dict[str, float] = {}

    # 当 MINE_RAG_HYBRID_ENABLED=false 时，行为与升级前一致：top_k=8
    if MINE_RAG_HYBRID_ENABLED:
        search_top_k = MINE_RAG_TOPK_LARGE
        output_top_k = MINE_RAG_TOPK_FINAL
    else:
        search_top_k = 8
        output_top_k = 8

    if embedding_service is not None and vector_store is not None and user_message.strip():
        try:
            query_vecs = await asyncio.to_thread(embedding_service.embed, [user_message])
            query_vec = query_vecs[0] if query_vecs else []
            if query_vec:
                namespace = f"knowledge:{sid}"
                if MINE_RAG_HYBRID_ENABLED:
                    candidates = _retrieve_candidates(
                        vector_store, namespace, query_vec, top_k_large=search_top_k
                    )
                    id_to_score = {c[0]: c[2] for c in candidates}
                    selected_ids = _rerank_with_quota(
                        candidates, chunk_by_id,
                        min_tables=2, min_joins=2, max_domain_ratio=0.3,
                    )
                    if MINE_RAG_GRAPH_EXPAND_ENABLED:
                        final_ids = _expand_by_graph(selected_ids, chunk_by_id, data)
                    else:
                        final_ids = selected_ids
                    for chunk_id in final_ids[:search_top_k]:
                        text = chunk_by_id.get(chunk_id, "")
                        if text:
                            snippets.append(text)
                            hit_chunk_ids.append(chunk_id)
                else:
                    neighbors = vector_store.search(
                        namespace=namespace, vector=query_vec, top_k=search_top_k
                    )
                    for chunk_id, meta in neighbors:
                        text = str(meta.get("text", "")).strip() if isinstance(meta, dict) else ""
                        if not text:
                            text = chunk_by_id.get(chunk_id, "")
                        if text:
                            snippets.append(text)
                            hit_chunk_ids.append(chunk_id)
        except Exception:
            # Keep chat available even when retrieval fails.
            pass

    if not snippets:
        chunk_list = [(cid, text) for cid, text in chunks[:search_top_k] if text]
        snippets = [text for _, text in chunk_list]
        hit_chunk_ids = [cid for cid, _ in chunk_list]
    if not snippets:
        fallback = build_schema_fallback_context(data)
        if fallback:
            snippets = [fallback]
            hit_chunk_ids = []

    deduped: List[str] = []
    deduped_ids: List[str] = []
    seen = set()
    for i, s in enumerate(snippets):
        if s in seen:
            continue
        seen.add(s)
        deduped.append(s)
        if i < len(hit_chunk_ids):
            deduped_ids.append(hit_chunk_ids[i])

    final_snippets = deduped[:output_top_k]
    final_infos = deduped_ids[:output_top_k]
    context_str = ""
    if final_snippets:
        if hit_chunk_ids:
            chunk_infos = [{"chunk_id": cid} for cid in final_infos]
            context_str = _format_structured_schema_context(
                final_snippets,
                chunk_infos=chunk_infos if chunk_infos else None,
                low_confidence=False,
            )
        else:
            context_str = (
                "## Schema Context (retrieved from knowledge base)\n"
                + "\n".join(f"- {s}" for s in final_snippets)
            )

    # 构建 retrieved_chunks 用于 retrieval_trace
    retrieved_chunks: List[Dict[str, Any]] = []
    for i, chunk_id in enumerate(final_infos):
        meta = chunk_by_meta.get(chunk_id, {})
        chunk_type = meta.get("chunk_type") or _parse_chunk_type(chunk_id)[0]
        text = final_snippets[i] if i < len(final_snippets) else chunk_by_id.get(chunk_id, "")
        score = id_to_score.get(chunk_id)
        table_refs = list(meta.get("table_refs") or [])
        column_refs = list(meta.get("column_refs") or [])
        retrieved_chunks.append({
            "chunk_id": chunk_id,
            "chunk_type": chunk_type,
            "text": text,
            "score": score,
            "table_refs": table_refs,
            "column_refs": column_refs,
        })

    table_count = sum(
        1 for cid in final_infos if cid.startswith("table:")
    )
    join_count = sum(
        1 for cid in final_infos
        if cid.startswith("join:") or cid.startswith("er_edge:")
    )
    retrieval_trace = {
        "prompt_context": context_str,
        "retrieved_chunks": retrieved_chunks,
        "table_count": table_count,
        "join_count": join_count,
    }

    # 结构化日志：retrieved_chunk_ids（逗号分隔）、table_count、join_count
    retrieved_chunk_ids_str = ",".join(final_infos) if final_infos else ""
    logger.info(
        "build_chat_knowledge_context",
        extra={
            "source_id": sid,
            "chunk_count": len(hit_chunk_ids) if hit_chunk_ids else len(snippets),
            "dedup_count": len(deduped),
            "retrieved_chunk_ids": retrieved_chunk_ids_str,
            "table_count": table_count,
            "join_count": join_count,
            "context_len": len(context_str),
            "hybrid_enabled": MINE_RAG_HYBRID_ENABLED,
        },
    )

    return ChatContextResult(prompt_context=context_str, retrieval_trace=retrieval_trace)

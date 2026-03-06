"""In-memory job store and enrich task logic for schema enrichment."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mine_agent.api.fastapi.knowledge_store import save_knowledge

logger = logging.getLogger(__name__)


def _append_llm_debug_log(call_type: str, request_preview: str, response_content: Optional[str], extra: str = "") -> None:
    """Append LLM request/response to debug log file for inspection."""
    base = os.getenv("MINE_CONFIG_DIR", os.path.expanduser("~/.mine"))
    Path(base).mkdir(parents=True, exist_ok=True)
    log_path = Path(base) / "llm_response_debug.log"
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    resp_repr = repr(response_content) if response_content is not None else "<None/empty>"
    if response_content and len(resp_repr) > 2000:
        resp_repr = resp_repr[:2000] + "... (truncated)"
    req_preview = (request_preview or "")[:500] + ("..." if len(request_preview or "") > 500 else "")
    line = f"\n--- {ts} [{call_type}] ---\nrequest_preview: {req_preview}\nresponse: {resp_repr}\n{extra}\n"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.debug("Failed to write LLM debug log: %s", e)

_JOBS: Dict[str, Dict[str, Any]] = {}

# When use_grouping=true and table count > this value, use phased flow (group -> per-group ER -> cross-group).
_GROUPING_THRESHOLD = 3

# System prompt for LLM: output only a JSON array of relationships.
_ER_INFER_SYSTEM = """You are a database schema analyst. Given a list of tables and their columns, output the foreign-key-like relationships between tables.

Output ONLY a JSON array. Each element must have exactly: "from_table", "from_column", "to_table", "to_column".
Use the exact table and column names from the input (case-sensitive). Do not add explanations or markdown.
Example: [{"from_table": "ORDERS", "from_column": "CUSTOMER_ID", "to_table": "CUSTOMERS", "to_column": "ID"}]"""

# System prompt for phase 1: group table names by business module / prefix.
_GROUPING_SYSTEM = """You are a database schema analyst. Given a list of table names, group them by business module, table name prefix, or logical domain.

Output ONLY a JSON object with a single key "groups". The value is an array of objects, each with:
- "name": a short English label for the group (e.g. "Order Management", "Product Info", "HR")
- "tables": an array of table names belonging to this group (use exact names from the input, case-sensitive)

Every table must appear in exactly one group. Do not add explanations or markdown.
Example: {"groups": [{"name": "Order Management", "tables": ["orders", "order_items"]}, {"name": "Product Info", "tables": ["products", "categories"]}]}"""


def _resolve_target_table(base: str, table_names: set, table_map: dict) -> Optional[str]:
    """Resolve target table from FK column base. Handles plural forms and prefixes (TB_, T_, etc)."""
    base_upper = base.upper()
    if base_upper in table_names:
        return table_map[base_upper]["name"]
    for suffix in ("S", "ES"):
        candidate = base_upper + suffix
        if candidate in table_names:
            return table_map[candidate]["name"]
    if base_upper.endswith("Y") and (base_upper[:-1] + "IES") in table_names:
        return table_map[base_upper[:-1] + "IES"]["name"]
    # Try tables with common prefixes: TB_ORDER, T_ORDERS, tab_orders
    for prefix in ("TB_", "T_", "TBL_", "TABLE_"):
        for suffix in ("", "S", "ES"):
            candidate = prefix + base_upper + suffix
            if candidate in table_names:
                return table_map[candidate]["name"]
    return None


def _infer_join_paths(tables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rule-based join path inference from table/column names."""
    join_paths: List[Dict[str, Any]] = []
    table_names = {t["name"].upper() for t in tables}
    table_map = {t["name"].upper(): t for t in tables}

    fk_candidates_no_target = []

    for t in tables:
        tname = t["name"]
        cols = t.get("columns") or []
        for c in cols:
            cname = (c.get("name") or "").upper()
            if not cname.endswith("_ID") and not cname.endswith("_REF"):
                continue
            base = cname[:-3] if cname.endswith("_ID") else cname[:-4]
            if not base:
                continue
            target_table = _resolve_target_table(base, table_names, table_map)
            if not target_table:
                fk_candidates_no_target.append(f"{tname}.{c.get('name') or cname} (base={base})")
                continue
            target_cols = (table_map[target_table.upper()].get("columns") or [])
            target_col = "ID"
            for tc in target_cols:
                tn = (tc.get("name") or "").upper()
                if tn == "ID" or tn == base.upper() + "_ID":
                    target_col = tc.get("name") or "ID"
                    break
            path = {
                "id": str(uuid.uuid4()),
                "from": {"table": tname, "column": c.get("name") or cname},
                "to": {"table": target_table, "column": target_col},
                "join_type": "inner",
                "confidence": 0.8,
                "evidence": "name_similarity",
                "description": f"{tname}.{c.get('name')} -> {target_table}.{target_col}",
            }
            join_paths.append(path)

    if not join_paths and fk_candidates_no_target:
        logger.info(
            "[enrich] Rule-based: 0 join paths. FK-like columns without matching table (sample): %s. "
            "Table names: %s. Tip: ensure columns end with _ID/_REF and target table exists (e.g. ORDER_ID->ORDERS).",
            fk_candidates_no_target[:10],
            sorted(table_names)[:20],
        )
    return join_paths


def _build_schema_text(tables: List[Dict[str, Any]]) -> str:
    """Build a short schema description for the LLM."""
    lines = []
    for t in tables:
        name = t.get("name", "?")
        cols = t.get("columns") or []
        col_str = ", ".join(
            f"{c.get('name', '')} ({c.get('type', '')})" for c in cols[:50]
        )
        if len(cols) > 50:
            col_str += ", ..."
        lines.append(f"Table: {name}. Columns: {col_str}")
    return "\n".join(lines)


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    """Parse JSON array from LLM content; strip markdown code block if present."""
    if not text or not text.strip():
        return []
    raw = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(out, list):
        return []
    return out


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Parse JSON object from LLM content; strip markdown code block if present."""
    if not text or not text.strip():
        return {}
    raw = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(out, dict):
        return {}
    return out


async def infer_groups_from_table_names(
    table_names: List[str],
    llm_service: Any,
    max_retries: int = 3,
    debug_context: str = "",
) -> List[Dict[str, Any]]:
    """Phase 1: Ask LLM to group table names by business module / prefix. Returns list of {name, tables}. Retries on empty/invalid."""
    from mine_agent.core.llm.models import LlmMessage, LlmRequest

    if not table_names:
        return []
    user_content = (
        "Group the following table names by business module, table name prefix, or logical domain. "
        "Output only a JSON object with key 'groups' (array of {name, tables}).\n\n"
        + "\n".join(table_names)
    )
    last_error = None
    for attempt in range(max_retries):
        try:
            request = LlmRequest(
                messages=[LlmMessage(role="user", content=user_content)],
                system_prompt=_GROUPING_SYSTEM,
                temperature=0.0,
                max_tokens=4096,
            )
            response = await llm_service.send_request(request)
            content = (response.content or "").strip()
            _append_llm_debug_log(
                "grouping",
                user_content,
                response.content,
                extra=f"{debug_context}, attempt={attempt + 1}, content_len={len(content or '')}, empty={not content}",
            )
            if not content:
                last_error = "LLM returned empty content"
                logger.warning("[enrich] Phase 1 grouping attempt %d: %s, retrying...", attempt + 1, last_error)
                continue
            obj = _extract_json_object(content)
            groups = obj.get("groups")
            if not isinstance(groups, list) or len(groups) == 0:
                last_error = f"groups invalid or empty (got {type(groups).__name__})"
                logger.warning("[enrich] Phase 1 grouping attempt %d: %s, retrying...", attempt + 1, last_error)
                continue
            seen = set()
            result = []
            for g in groups:
                if not isinstance(g, dict):
                    continue
                name = g.get("name") or "Default"
                tbls = g.get("tables")
                if not isinstance(tbls, list):
                    continue
                tbls = [t for t in tbls if isinstance(t, str) and t not in seen]
                for t in tbls:
                    seen.add(t)
                if tbls:
                    result.append({"name": name, "tables": tbls})
            all_names = set(table_names)
            missing = list(all_names - seen)
            if missing:
                result.append({"name": "Other", "tables": missing})
            if result:
                return result
            last_error = "no valid groups parsed"
            logger.warning("[enrich] Phase 1 grouping attempt %d: %s, retrying...", attempt + 1, last_error)
        except Exception as e:
            last_error = str(e)
            logger.warning("[enrich] Phase 1 grouping attempt %d failed: %s, retrying...", attempt + 1, e)
    logger.error("[enrich] Phase 1 grouping failed after %d attempts: %s", max_retries, last_error)
    return []


async def infer_join_paths_with_llm(
    tables: List[Dict[str, Any]],
    llm_service: Any,
    max_retries: int = 3,
    debug_context: str = "",
) -> List[Dict[str, Any]]:
    """Use LLM to infer join paths from table schema. Returns list of join_path dicts. Retries on empty/invalid."""
    from mine_agent.core.llm.models import LlmMessage, LlmRequest

    schema_text = _build_schema_text(tables)
    user_content = (
        "Infer all foreign-key relationships between these tables. "
        "Output only a JSON array of objects with from_table, from_column, to_table, to_column.\n\n"
        + schema_text
    )
    table_names_set = {t.get("name") for t in tables if t.get("name")}
    # Case-insensitive lookup: UPPER(name) -> actual name (Oracle often uses uppercase)
    upper_to_actual = {n.upper(): n for n in table_names_set}
    for attempt in range(max_retries):
        try:
            request = LlmRequest(
                messages=[LlmMessage(role="user", content=user_content)],
                system_prompt=_ER_INFER_SYSTEM,
                temperature=0.0,
                max_tokens=4096,
            )
            response = await llm_service.send_request(request)
            content = (response.content or "").strip()
            _append_llm_debug_log(
                "join_inference",
                user_content,
                response.content,
                extra=f"{debug_context}, attempt={attempt + 1}, content_len={len(content or '')}, empty={not content}",
            )
            if not content:
                logger.warning("[enrich] LLM join inference attempt %d: empty content, retrying...", attempt + 1)
                continue
            items = _extract_json_array(content)
            if not items:
                logger.warning("[enrich] LLM join inference attempt %d: parsed 0 items (content len=%d), retrying...", attempt + 1, len(content))
                continue
            join_paths: List[Dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                from_table = item.get("from_table")
                from_column = item.get("from_column")
                to_table = item.get("to_table")
                to_column = item.get("to_column")
                if not all([from_table, from_column, to_table, to_column]):
                    continue
                from_actual = upper_to_actual.get((from_table or "").upper())
                to_actual = upper_to_actual.get((to_table or "").upper())
                if not from_actual or not to_actual:
                    continue
                join_paths.append({
                    "id": str(uuid.uuid4()),
                    "from": {"table": from_actual, "column": from_column},
                    "to": {"table": to_actual, "column": to_column},
                    "join_type": "inner",
                    "confidence": 0.85,
                    "evidence": "llm",
                    "description": f"{from_table}.{from_column} -> {to_table}.{to_column}",
                })
            if join_paths:
                return join_paths
            logger.warning(
                "[enrich] LLM join inference attempt %d: 0 valid paths after filtering (parsed %d items, table names may not match). Retrying...",
                attempt + 1,
                len(items),
            )
        except Exception as e:
            logger.warning("[enrich] LLM join inference attempt %d failed: %s, retrying...", attempt + 1, e)
    return []


def _find_cross_group_candidates(
    tables: List[Dict[str, Any]],
    table_to_group: Dict[str, str],
) -> List[Tuple[str, str]]:
    """Find (from_table, to_table) pairs that are in different groups and have candidate FK (e.g. *_ID)."""
    name_to_table = {t.get("name"): t for t in tables if t.get("name")}
    all_names = set(name_to_table.keys())
    candidates = []
    for t in tables:
        tname = t.get("name")
        if not tname or table_to_group.get(tname) is None:
            continue
        group_from = table_to_group[tname]
        cols = t.get("columns") or []
        for c in cols:
            cname = (c.get("name") or "").upper()
            if cname.endswith("_ID"):
                base = cname[:-3]
            elif cname.endswith("_REF"):
                base = cname[:-4]
            else:
                continue
            if not base:
                continue
            # Try to find a table matching base (e.g. CUSTOMER_ID -> CUSTOMERS or CUSTOMER)
            to_table = None
            base_upper = base.upper()
            for other in all_names:
                ou = other.upper()
                if ou == base_upper or ou == base_upper + "S":
                    to_table = other
                    break
                if base_upper.endswith("S") and ou == base_upper[:-1]:
                    to_table = other
                    break
            if not to_table or to_table == tname:
                continue
            group_to = table_to_group.get(to_table)
            if group_to is not None and group_from != group_to:
                candidates.append((tname, to_table))
    return list(dict.fromkeys(candidates))  # dedupe preserving order


async def _infer_join_paths_for_pair(
    table_a: Dict[str, Any],
    table_b: Dict[str, Any],
    llm_service: Any,
    debug_context: str = "",
) -> List[Dict[str, Any]]:
    """Lightweight: infer join paths between exactly two tables (for cross-group phase)."""
    return await infer_join_paths_with_llm([table_a, table_b], llm_service, debug_context=debug_context)


def _build_er_graph(
    tables: List[Dict[str, Any]],
    join_paths: List[Dict[str, Any]],
    table_to_group: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build er_graph nodes and edges from tables and join_paths. Optional table_to_group for node.group."""
    nodes = []
    for t in tables:
        tname = t.get("name", "?")
        cols = t.get("columns") or []
        node = {
            "id": tname,
            "table": tname,
            "label": tname,
            "schema": None,
        }
        if table_to_group and tname in table_to_group:
            node["group"] = table_to_group[tname]
        nodes.append(node)
    edges = []
    for i, j in enumerate(join_paths):
        fr = j.get("from") or {}
        to = j.get("to") or {}
        edges.append({
            "id": j.get("id") or f"edge_{i}",
            "source": fr.get("table", ""),
            "target": to.get("table", ""),
            "source_column": fr.get("column"),
            "target_column": to.get("column"),
            "cardinality": "n:1",
            "relation_type": "foreign_key",
            "confidence": j.get("confidence", 0.5),
            "evidence": j.get("evidence", "inferred"),
        })
    return {"nodes": nodes, "edges": edges}


async def _run_enrich_job(
    job_id: str,
    connection_id: str,
    source_id: str,
    schema_filter: Optional[str],
    persist: bool,
    llm_service: Optional[Any] = None,
    use_grouping: Optional[bool] = None,
) -> None:
    """Execute enrich task: extract schema -> infer joins (LLM or rules) -> build er_graph -> optionally save."""
    try:
        _JOBS[job_id]["status"] = "running"
        _JOBS[job_id]["progress"] = 0.1

        from mine_agent.api.fastapi.knowledge_routes import _do_schema_extract

        result = await _do_schema_extract(connection_id, schema_filter)
        tables = result.get("tables") or []
        _JOBS[job_id]["progress"] = 0.5
        logger.info("[enrich] Schema extracted: %d tables", len(tables))

        generator = "rule_based"
        table_to_group: Optional[Dict[str, str]] = None
        if llm_service and tables:
            try:
                should_group = (
                    bool(use_grouping) and len(tables) > _GROUPING_THRESHOLD
                )
                debug_context = f"job_id={job_id}"
                if should_group:
                    # Phased flow: group by LLM -> per-group ER -> cross-group补边
                    logger.info("[enrich] Phase flow: %d tables > %d, using group->per-group->cross-group", len(tables), _GROUPING_THRESHOLD)
                    table_names = [t.get("name") for t in tables if t.get("name")]
                    logger.info("[enrich] Phase 1: grouping %d tables by LLM...", len(table_names))
                    groups = await infer_groups_from_table_names(table_names, llm_service, debug_context=debug_context)
                    logger.info("[enrich] Phase 1 done: %d groups", len(groups))
                    table_to_group = {}
                    for g in groups:
                        grp_name = g.get("name") or "Default"
                        grp_tbls = g.get("tables") or []
                        for tn in grp_tbls:
                            table_to_group[tn] = grp_name
                        logger.info("[enrich]   - %s: %d tables %s", grp_name, len(grp_tbls), grp_tbls[:5] + (["..."] if len(grp_tbls) > 5 else []))
                    name_to_table = {t.get("name"): t for t in tables if t.get("name")}
                    join_paths = []
                    # Phase 2: parallel per-group LLM calls
                    async def _infer_group(g, idx: int):
                        grp_name = g.get("name") or f"Group_{idx}"
                        grp_tables = [name_to_table[tn] for tn in (g.get("tables") or []) if name_to_table.get(tn)]
                        if len(grp_tables) < 2:
                            logger.info("[enrich] Phase 2: skip group '%s' (%d tables, need >=2)", grp_name, len(grp_tables))
                            return []
                        try:
                            jps = await infer_join_paths_with_llm(grp_tables, llm_service, debug_context=debug_context)
                            logger.info("[enrich] Phase 2 %s: got %d join paths", grp_name, len(jps))
                            return jps
                        except Exception as eg:
                            logger.warning("LLM per-group inference failed for %s: %s", grp_name, eg)
                            return []
                    results = await asyncio.gather(*[_infer_group(g, i) for i, g in enumerate(groups)])
                    for jps in results:
                        join_paths.extend(jps)
                    # Phase 3: cross-group candidates (e.g. *_ID column -> table in another group), parallel
                    candidates = _find_cross_group_candidates(tables, table_to_group)
                    logger.info("[enrich] Phase 3: found %d cross-group candidate pairs", len(candidates))

                    async def _infer_pair(from_t: str, to_t: str):
                        ta = name_to_table.get(from_t)
                        tb = name_to_table.get(to_t)
                        if not ta or not tb:
                            return []
                        try:
                            jps = await _infer_join_paths_for_pair(ta, tb, llm_service, debug_context=debug_context)
                            logger.info("[enrich] Phase 3 %s->%s: got %d paths", from_t, to_t, len(jps))
                            return jps
                        except Exception as ec:
                            logger.debug("Cross-group pair %s->%s failed: %s", from_t, to_t, ec)
                            return []
                    pair_results = await asyncio.gather(*[_infer_pair(ft, tt) for (ft, tt) in candidates])
                    for jps in pair_results:
                        join_paths.extend(jps)
                    # Dedupe by (from_table, from_column, to_table, to_column)
                    orig_count = len(join_paths)
                    seen_keys = set()
                    unique_paths = []
                    for j in join_paths:
                        fr = j.get("from") or {}
                        to = j.get("to") or {}
                        key = (fr.get("table"), fr.get("column"), to.get("table"), to.get("column"))
                        if key not in seen_keys:
                            seen_keys.add(key)
                            unique_paths.append(j)
                    join_paths = unique_paths
                    logger.info("[enrich] Merged: %d -> %d unique join paths (removed %d dupes)", orig_count, len(join_paths), orig_count - len(join_paths))
                    if join_paths:
                        generator = "llm"
                else:
                    logger.info("[enrich] Single request: grouping=%s, %d tables", bool(use_grouping), len(tables))
                    join_paths = await infer_join_paths_with_llm(tables, llm_service, debug_context=debug_context)
                    if join_paths:
                        generator = "llm"
                        logger.info("[enrich] Single request: got %d join paths from LLM", len(join_paths))
                    else:
                        join_paths = _infer_join_paths(tables)
                        logger.info("[enrich] Single request: LLM returned empty, using rules: %d paths", len(join_paths))
                if not join_paths and generator != "llm":
                    join_paths = _infer_join_paths(tables)
                    logger.info("[enrich] Fallback to rules: %d paths", len(join_paths))
            except Exception as e:
                logger.warning("LLM join inference failed, falling back to rules: %s", e)
                join_paths = _infer_join_paths(tables)
        else:
            logger.info("[enrich] No LLM, using rule-based inference for %d tables", len(tables))
            join_paths = _infer_join_paths(tables)
            logger.info("[enrich] Rule-based: %d join paths", len(join_paths))

        er_graph = _build_er_graph(tables, join_paths, table_to_group)
        logger.info("[enrich] Done: generator=%s, %d join_paths, %d nodes, %d edges", generator, len(join_paths), len(er_graph.get("nodes", [])), len(er_graph.get("edges", [])))
        _JOBS[job_id]["progress"] = 0.8

        payload = {
            "tables": tables,
            "join_paths": join_paths,
            "er_graph": er_graph,
            "meta": {
                "schema_extracted_at": datetime.utcnow().isoformat() + "Z",
                "enriched_at": datetime.utcnow().isoformat() + "Z",
                "generator": generator,
                "model": None,
                "version": "1",
            },
        }

        if persist:
            save_knowledge(source_id, payload)

        _JOBS[job_id]["status"] = "succeeded"
        _JOBS[job_id]["progress"] = 1.0
        _JOBS[job_id]["result"] = payload
    except Exception as e:
        logger.exception("Enrich job %s failed: %s", job_id, e)
        _JOBS[job_id]["status"] = "failed"
        _JOBS[job_id]["error"] = str(e)


def create_job(
    connection_id: str,
    source_id: str,
    schema_filter: Optional[str] = None,
    persist: bool = True,
    llm_service: Optional[Any] = None,
    use_grouping: Optional[bool] = None,
) -> str:
    """Create and start an enrich job. Returns job_id."""
    job_id = str(uuid.uuid4())
    _JOBS[job_id] = {
        "status": "pending",
        "progress": 0,
        "result": None,
        "error": None,
    }
    asyncio.create_task(
        _run_enrich_job(
            job_id, connection_id, source_id, schema_filter, persist, llm_service, use_grouping
        )
    )
    return job_id


def read_llm_debug_log(job_id: Optional[str] = None) -> str:
    """Read LLM debug log text. If job_id provided, return only matching blocks."""
    base = os.getenv("MINE_CONFIG_DIR", os.path.expanduser("~/.mine"))
    log_path = Path(base) / "llm_response_debug.log"
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception:
        return ""
    if not job_id:
        return text
    blocks = text.split("\n--- ")
    matched = []
    for i, block in enumerate(blocks):
        if not block.strip():
            continue
        normalized = block if i == 0 else f"--- {block}"
        if f"job_id={job_id}" in normalized:
            matched.append(normalized)
    return "\n".join(matched)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job status and result."""
    return _JOBS.get(job_id)

"""Routes for dynamic datasource config, schema extraction, knowledge CRUD, and vectorize."""

from __future__ import annotations

import asyncio
import logging
from json import dumps
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from mine_agent.api.fastapi.datasources_config import (
    connection_to_datasource_config,
    create_connection,
    delete_connection,
    get_connection,
    load_connections,
    update_connection,
    ConnectionEntry,
)
from mine_agent.api.fastapi.knowledge_context import build_knowledge_chunks
from mine_agent.api.fastapi.knowledge_store import (
    load_embedding_config,
    load_knowledge,
    save_embedding_config,
    save_knowledge,
)
from mine_agent.capabilities.data_source.models import DataSourceType
from mine_agent.integrations.oracle.client import OracleDataSource
from mine_agent.integrations.snowflake.client import SnowflakeDataSource

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["knowledge"])


# --- Request/Response models ---


class ConnectionCreate(BaseModel):
    source_id: str
    source_type: DataSourceType
    options: Dict[str, Any] = Field(default_factory=dict)
    allowed_schemas: Optional[List[str]] = None
    allowed_sql_keywords: Optional[List[str]] = None


class ConnectionUpdate(BaseModel):
    source_id: Optional[str] = None
    source_type: Optional[DataSourceType] = None
    options: Optional[Dict[str, Any]] = None
    allowed_schemas: Optional[List[str]] = None
    allowed_sql_keywords: Optional[List[str]] = None


class SchemaExtractRequest(BaseModel):
    connection_id: str
    schema_filter: Optional[str] = Field(default=None, description="Optional schema/owner filter")


class EnrichAsyncRequest(BaseModel):
    connection_id: str
    schema_filter: Optional[str] = Field(default=None)
    source_id: Optional[str] = Field(default=None, description="Defaults to connection source_id")
    persist: bool = Field(default=True)
    use_grouping: Optional[bool] = Field(
        default=None,
        description="Whether to use grouping flow. When true, group when table count > 3; when false, never group.",
    )


class VectorizeRequest(BaseModel):
    embedding_vendor: str = Field(..., description="厂商: zhipu, openai, deepseek")
    embedding_model: str = Field(..., description="模型名: embedding-3, text-embedding-3-small 等")


def _datasource_from_connection(entry: ConnectionEntry):
    cfg = connection_to_datasource_config(entry)
    if cfg.source_type == DataSourceType.ORACLE:
        return OracleDataSource(
            source_id=cfg.source_id,
            connection_options=cfg.options,
        )
    if cfg.source_type == DataSourceType.SNOWFLAKE:
        return SnowflakeDataSource(
            source_id=cfg.source_id,
            connection_options=cfg.options,
        )
    raise ValueError(f"Unsupported source_type: {cfg.source_type}")


# --- Config CRUD ---


@router.get("/datasources/config")
async def list_datasources_config() -> List[Dict[str, Any]]:
    """List all dynamic connection configs."""
    entries = load_connections()
    return [e.model_dump() for e in entries]


@router.post("/datasources/config", response_model=Dict[str, Any])
async def post_datasource_config(body: ConnectionCreate) -> Dict[str, Any]:
    """Create a new connection config."""
    entry = create_connection(
        source_id=body.source_id,
        source_type=body.source_type,
        options=body.options,
        allowed_schemas=body.allowed_schemas,
        allowed_sql_keywords=body.allowed_sql_keywords,
    )
    return entry.model_dump()


@router.put("/datasources/config/{connection_id}", response_model=Dict[str, Any])
async def put_datasource_config(connection_id: str, body: ConnectionUpdate) -> Dict[str, Any]:
    """Update a connection config."""
    entry = update_connection(
        connection_id,
        source_id=body.source_id,
        source_type=body.source_type,
        options=body.options,
        allowed_schemas=body.allowed_schemas,
        allowed_sql_keywords=body.allowed_sql_keywords,
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Connection not found")
    return entry.model_dump()


@router.delete("/datasources/config/{connection_id}")
async def delete_datasource_config(connection_id: str) -> Dict[str, str]:
    """Delete a connection config."""
    if not delete_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"status": "deleted"}


@router.post("/datasources/config/{connection_id}/test")
async def test_datasource_config(connection_id: str) -> Dict[str, Any]:
    """Test a connection by creating a temporary DataSource and calling test_connection()."""
    entry = get_connection(connection_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        ds = _datasource_from_connection(entry)
        ok = await ds.test_connection()
        return {"ok": ok, "message": "Connected" if ok else "Connection failed"}
    except Exception as e:
        logger.exception("Test connection failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))


# --- Schema extract ---


async def _do_schema_extract(connection_id: str, schema_filter: Optional[str]) -> Dict[str, Any]:
    """Core schema extraction logic. Used by both sync route and enrich job."""
    entry = get_connection(connection_id)
    if not entry:
        raise ValueError("Connection not found")
    ds = _datasource_from_connection(entry)
    effective_schema = schema_filter
    if not effective_schema and entry.source_type == DataSourceType.ORACLE:
        user = entry.options.get("user")
        if user:
            effective_schema = str(user).upper()
    get_all = getattr(ds, "get_all_columns", None)
    if callable(get_all):
        all_cols = await get_all(effective_schema)
        result_tables = [
            {"name": t, "columns": [{"name": c[0], "type": c[1]} for c in cols]}
            for t, cols in sorted(all_cols.items())
        ]
    else:
        tables = await ds.list_tables(schema=effective_schema)
        result_tables = []
        for table_name in tables:
            cols = await ds.get_columns(effective_schema, table_name)
            result_tables.append({
                "name": table_name,
                "columns": [{"name": c[0], "type": c[1]} for c in cols],
            })
    return {"tables": result_tables}


@router.post("/knowledge/schema/extract")
async def schema_extract(body: SchemaExtractRequest) -> Dict[str, Any]:
    """Extract schema (tables + columns) from a configured connection."""
    entry = get_connection(body.connection_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        return await _do_schema_extract(body.connection_id, body.schema_filter)
    except Exception as e:
        logger.exception("Schema extract failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/knowledge/schema/enrich/async")
async def enrich_async(request: Request, body: EnrichAsyncRequest) -> Dict[str, Any]:
    """Start async schema enrichment (extract + infer join_paths + er_graph). Returns job_id."""
    from mine_agent.api.fastapi.enrich_jobs import create_job

    entry = get_connection(body.connection_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Connection not found")
    source_id = body.source_id or entry.source_id
    orchestrator = getattr(request.app.state, "orchestrator", None)
    llm_service = getattr(orchestrator, "_llm_service", None) if orchestrator else None
    job_id = create_job(
        connection_id=body.connection_id,
        source_id=source_id,
        schema_filter=body.schema_filter,
        persist=body.persist,
        llm_service=llm_service,
        use_grouping=body.use_grouping,
    )
    return {"job_id": job_id}


@router.get("/knowledge/jobs/{job_id}")
async def get_job_status(job_id: str) -> Dict[str, Any]:
    """Get enrich job status. Returns status, progress, result (when succeeded), error (when failed)."""
    from mine_agent.api.fastapi.enrich_jobs import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "status": job["status"],
        "progress": job.get("progress", 0),
        "result": job.get("result"),
        "error": job.get("error"),
    }


@router.get("/knowledge/llm-debug")
async def get_llm_debug_log(
    job_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 12000,
) -> Dict[str, Any]:
    """Read LLM debug log text (optionally filtered by job_id) with incremental paging."""
    from mine_agent.api.fastapi.enrich_jobs import read_llm_debug_log

    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 12000
    if limit > 50000:
        limit = 50000
    text = read_llm_debug_log(job_id=job_id)
    if offset > len(text):
        offset = len(text)
    chunk = text[offset: offset + limit]
    next_offset = offset + len(chunk)
    return {
        "job_id": job_id,
        "text": chunk,
        "offset": offset,
        "next_offset": next_offset,
        "has_more": next_offset < len(text),
    }


@router.get("/knowledge/llm-debug/stream")
async def stream_llm_debug_log(
    request: Request,
    job_id: Optional[str] = None,
    from_tail: bool = False,
) -> StreamingResponse:
    """SSE stream for LLM debug logs. Pushes append-only chunks to the client."""
    from mine_agent.api.fastapi.enrich_jobs import read_llm_debug_log

    async def event_stream():
        text = read_llm_debug_log(job_id=job_id)
        offset = len(text) if from_tail else 0
        ready = {"type": "ready", "job_id": job_id, "from_tail": from_tail, "offset": offset}
        yield f"event: ready\ndata: {dumps(ready, ensure_ascii=False)}\n\n"
        while True:
            if await request.is_disconnected():
                break
            full_text = read_llm_debug_log(job_id=job_id)
            if len(full_text) < offset:
                # Log rotated or truncated: reset cursor.
                offset = 0
            if len(full_text) > offset:
                chunk = full_text[offset:]
                offset = len(full_text)
                payload = {"type": "chunk", "job_id": job_id, "text": chunk, "offset": offset}
                yield f"event: chunk\ndata: {dumps(payload, ensure_ascii=False)}\n\n"
            else:
                heartbeat = {"type": "heartbeat", "job_id": job_id, "offset": offset}
                yield f"event: heartbeat\ndata: {dumps(heartbeat, ensure_ascii=False)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Knowledge CRUD ---


@router.get("/knowledge/{source_id}")
async def get_knowledge(source_id: str) -> JSONResponse:
    """Get knowledge JSON for a source_id. Returns 404 if not found."""
    data = load_knowledge(source_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    return JSONResponse(content=data)


@router.put("/knowledge/{source_id}")
async def put_knowledge(source_id: str, body: Dict[str, Any]) -> Dict[str, str]:
    """Create or update knowledge JSON for a source_id."""
    save_knowledge(source_id, body)
    return {"status": "saved", "source_id": source_id}


# --- Embedding options & config ---


@router.get("/knowledge/embedding-options")
async def get_embedding_options(request: Request) -> Dict[str, Any]:
    """返回可用的 embedding 厂商与模型列表，供前端选择。"""
    options = getattr(request.app.state, "embedding_options", [])
    return {"options": options}


@router.get("/knowledge/{source_id}/embedding-config")
async def get_source_embedding_config(source_id: str) -> Dict[str, Any]:
    """返回该知识源已锁定的 embedding 配置；若未锁定则返回空。一旦锁定不可更改。"""
    cfg = load_embedding_config(source_id)
    if cfg is None:
        return {"locked": False, "vendor": None, "model": None}
    return {"locked": True, "vendor": cfg.get("vendor"), "model": cfg.get("model")}


# --- Vectorize ---


@router.post("/knowledge/{source_id}/vectorize")
async def vectorize_knowledge(
    source_id: str,
    request: Request,
    body: VectorizeRequest,
) -> Dict[str, Any]:
    """Vectorize knowledge JSON: chunk, embed, store in VectorStore. 首次选择 vendor+model 后锁定，不可更改。"""
    data = load_knowledge(source_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Knowledge not found. Save knowledge first.")

    services = getattr(request.app.state, "embedding_services", {})
    vector_store = getattr(request.app.state, "vector_store", None)
    if not services or not vector_store:
        raise HTTPException(status_code=501, detail="Embedding or vector store not configured")

    locked_cfg = load_embedding_config(source_id)
    vendor = body.embedding_vendor.strip().lower()
    model = body.embedding_model.strip()

    if locked_cfg:
        if vendor != locked_cfg.get("vendor") or model != locked_cfg.get("model"):
            raise HTTPException(
                status_code=400,
                detail=f"该知识源已锁定 embedding 配置为 {locked_cfg.get('vendor')}/{locked_cfg.get('model')}，不可更改。",
            )
    else:
        save_embedding_config(source_id, vendor, model)

    svc_key = f"{vendor}:{model}"
    embedding_svc = services.get(svc_key)
    if not embedding_svc:
        available = list(services.keys())
        raise HTTPException(
            status_code=400,
            detail=f"未找到 embedding 服务 {svc_key}。可用: {available}。请设置对应 API Key（ZHIPU_API_KEY / OPENAI_API_KEY）。",
        )

    chunks = build_knowledge_chunks(data)
    if not chunks:
        return {"status": "ok", "chunks_embedded": 0, "vendor": vendor, "model": model}

    texts = [t for _, t in chunks]
    try:
        vectors = await asyncio.to_thread(embedding_svc.embed, texts)
    except Exception as e:
        err_msg = str(e)
        if "404" in err_msg or "Not Found" in err_msg:
            raise HTTPException(
                status_code=502,
                detail="Embedding API 返回 404：请确认 model 名称正确。"
                "DeepSeek 使用 deepseek-embedding；OpenAI 使用 text-embedding-3-small 等。"
                "可设置 MINE_EMBEDDING_MODEL 指定模型。",
            ) from e
        raise HTTPException(status_code=502, detail=f"Embedding 调用失败: {err_msg}") from e

    namespace = f"knowledge:{source_id}"
    try:
        store = request.app.state.vector_store
        if hasattr(store, "delete_namespace"):
            try:
                store.delete_namespace(namespace)
            except NotImplementedError:
                pass
    except Exception:
        pass

    for (chunk_id, chunk_text), vec in zip(chunks, vectors):
        vector_store.add(
            namespace=namespace,
            id=chunk_id,
            vector=vec,
            metadata={
                "source_id": source_id,
                "chunk_id": chunk_id,
                "text": chunk_text,
            },
        )

    return {
        "status": "ok",
        "chunks_embedded": len(chunks),
        "namespace": namespace,
        "vendor": vendor,
        "model": model,
    }

"""FastAPI application factory with injectable orchestrator."""

from __future__ import annotations

import logging
import os
import uuid
from json import dumps
from typing import TYPE_CHECKING, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from mine_agent.api.common.auth import validate_bearer_token
from mine_agent.api.common.errors import (
    ApiErrorCode,
    ErrorResponse as CommonErrorResponse,
    orchestrator_not_configured_error,
)
from mine_agent.api.fastapi.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    MetadataResponse,
)
from mine_agent.capabilities.data_source.models import DataSourceType
from mine_agent.capabilities.data_source.router import DataSourceRouter
from mine_agent.config.settings import AppSettings
from mine_agent.core.tool.registry import ToolRegistry
from mine_agent.engine.orchestrator import Orchestrator
from mine_agent.integrations.local.storage import InMemoryConversationStore
from mine_agent.integrations.mock.llm import MockLlmService
from mine_agent.integrations.openai import OpenAILlmService
from mine_agent.integrations.oracle.client import OracleDataSource
from mine_agent.integrations.snowflake.client import SnowflakeDataSource
from mine_agent.observability.logging import configure_logging
from mine_agent.tools.query_data import QueryDataTool

from mine_agent.api.fastapi.datasources_config import (
    connection_to_datasource_config,
    load_connections,
)
from mine_agent.api.fastapi.knowledge_context import build_chat_knowledge_context
from mine_agent.api.fastapi.knowledge_store import load_embedding_config
from mine_agent.api.fastapi.knowledge_routes import router as knowledge_router
from mine_agent.core.embedding.base import EmbeddingService
from mine_agent.core.vector.base import VectorStore
from mine_agent.integrations.embedding.deepseek import DeepSeekEmbeddingService
from mine_agent.integrations.embedding.openai_embedding import OpenAIEmbeddingService
from mine_agent.integrations.embedding.zhipu import ZhiPuEmbeddingService
from mine_agent.integrations.vector.inmemory import InMemoryVectorStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _build_router_from_env() -> DataSourceRouter:
    router = DataSourceRouter()
    datasource_config = AppSettings.datasources_from_env()
    if datasource_config.sources:
        for source in datasource_config.sources:
            options = dict(source.options)
            if source.allowed_schemas is not None and "allowed_schemas" not in options:
                options["allowed_schemas"] = source.allowed_schemas
            if source.allowed_sql_keywords is not None and "allowed_sql_keywords" not in options:
                options["allowed_sql_keywords"] = source.allowed_sql_keywords

            if source.source_type == DataSourceType.ORACLE:
                router.register(OracleDataSource(source_id=source.source_id, connection_options=options))
            elif source.source_type == DataSourceType.SNOWFLAKE:
                router.register(
                    SnowflakeDataSource(source_id=source.source_id, connection_options=options)
                )
            else:
                logger.warning("Skipping unsupported data source type: %s", source.source_type)

    # 合并知识库中创建的动态连接，使 Chat 与知识库使用同一套连接
    for entry in load_connections():
        if entry.source_id in router.list_source_ids():
            continue
        try:
            cfg = connection_to_datasource_config(entry)
            if cfg.source_type == DataSourceType.ORACLE:
                router.register(OracleDataSource(source_id=cfg.source_id, connection_options=cfg.options))
            elif cfg.source_type == DataSourceType.SNOWFLAKE:
                router.register(SnowflakeDataSource(source_id=cfg.source_id, connection_options=cfg.options))
            else:
                logger.warning("Skipping unsupported dynamic connection type: %s", cfg.source_type)
        except Exception as e:
            logger.warning("Failed to register dynamic connection %s: %s", entry.source_id, e)

    return router


def _build_default_orchestrator(
    router: DataSourceRouter, settings: AppSettings
) -> Orchestrator:
    source_ids = router.list_source_ids()
    default_source_id = source_ids[0] if source_ids else "oracle_demo"
    llm_service = _build_default_llm(default_source_id=default_source_id)

    tool_registry = ToolRegistry()
    tool_registry.register(
        QueryDataTool(
            router=router,
            default_limit=settings.default_query_limit,
            allowed_sql_keywords=settings.allowed_sql_keywords,
        )
    )
    return Orchestrator(
        llm_service=llm_service,
        tool_registry=tool_registry,
        conversation_store=InMemoryConversationStore(),
        max_tool_iterations=settings.max_tool_iterations,
    )


def _build_default_llm(default_source_id: str):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return MockLlmService(default_source_id=default_source_id)

    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")
    if not model and base_url and "deepseek" in base_url.lower():
        model = "deepseek-chat"

    try:
        return OpenAILlmService(model=model, api_key=api_key, base_url=base_url)
    except Exception as e:
        logger.warning("Failed to initialize OpenAI LLM, falling back to Mock: %s", e)
        return MockLlmService(default_source_id=default_source_id)


def _build_simple_chunk(
    *,
    text: str,
    conversation_id: str,
    request_id: str,
) -> dict:
    return {
        "type": "assistant_message_chunk",
        "conversation_id": conversation_id,
        "request_id": request_id,
        "simple": {"type": "text", "text": text},
    }


def create_app(
    orchestrator: Optional[Orchestrator] = None,
    settings: Optional[AppSettings] = None,
    router: Optional["DataSourceRouter"] = None,
) -> FastAPI:
    """Create FastAPI application with optional orchestrator and router injection."""
    app_settings = settings or AppSettings.from_env()
    configure_logging()

    if router is None:
        router = _build_router_from_env()

    if orchestrator is None and router is not None and router.list_source_ids():
        orchestrator = _build_default_orchestrator(
            router=router, settings=app_settings
        )

    app = FastAPI(
        title=app_settings.service_name,
        version=app_settings.service_version,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store dependencies for route handlers.
    app.state.orchestrator = orchestrator
    app.state.settings = app_settings
    app.state.router = router

    # Embedding services: 多厂商可配置，key 为 "vendor:model"
    _embedding_services: dict[str, EmbeddingService] = {}
    _embedding_options: list[dict[str, str]] = []

    def _reg(vendor: str, model: str, label: str, svc: EmbeddingService) -> None:
        k = f"{vendor}:{model}"
        _embedding_services[k] = svc
        _embedding_options.append({"vendor": vendor, "model": model, "label": label})

    def _add_zhipu() -> None:
        key = os.getenv("ZHIPU_API_KEY") or os.getenv("MINE_EMBEDDING_API_KEY")
        if not key:
            return
        try:
            dim = os.getenv("MINE_EMBEDDING_DIMENSIONS")
            dim_int = int(dim) if dim and dim.isdigit() else None
            if dim_int is not None and dim_int not in (256, 512, 1024, 2048):
                dim_int = 2048
            svc = ZhiPuEmbeddingService(model="embedding-3", api_key=key, dimensions=dim_int)
            _reg("zhipu", "embedding-3", "智谱 Embedding-3", svc)
        except Exception as e:
            logger.warning("ZhiPu embedding init failed: %s", e)

    def _add_openai() -> None:
        key = os.getenv("MINE_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not key:
            return
        try:
            base = os.getenv("MINE_EMBEDDING_BASE_URL") or "https://api.openai.com/v1"
            for m, lbl in [("text-embedding-3-small", "OpenAI text-embedding-3-small"),
                           ("text-embedding-3-large", "OpenAI text-embedding-3-large")]:
                _reg("openai", m, lbl, OpenAIEmbeddingService(model=m, api_key=key, base_url=base))
        except Exception as e:
            logger.warning("OpenAI embedding init failed: %s", e)

    def _add_deepseek() -> None:
        key = os.getenv("MINE_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
        base = (os.getenv("MINE_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
        if not key or "deepseek" not in base.lower():
            return
        try:
            svc = DeepSeekEmbeddingService(model="deepseek-embedding", api_key=key, base_url=base)
            _reg("deepseek", "deepseek-embedding", "DeepSeek embedding", svc)
        except Exception as e:
            logger.warning("DeepSeek embedding init failed: %s", e)

    try:
        _add_zhipu()
        _add_openai()
        _add_deepseek()
    except ImportError:
        logger.warning("Embedding not available: openai package required. pip install openai")

    app.state.embedding_services = _embedding_services
    app.state.embedding_options = _embedding_options
    app.state.embedding_service = _embedding_services.get("zhipu:embedding-3") or next(iter(_embedding_services.values()), None)
    app.state.vector_store = InMemoryVectorStore()

    app.include_router(knowledge_router)

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(  # type: ignore[no-untyped-def]
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", None)
        if isinstance(exc.detail, dict):
            error_code = exc.detail.get("error_code", ApiErrorCode.BAD_REQUEST.value)
            message = exc.detail.get("message", "Request failed")
        else:
            error_code = ApiErrorCode.BAD_REQUEST.value
            message = str(exc.detail)
        payload = CommonErrorResponse(
            error_code=error_code,
            message=message,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def generic_exception_handler(  # type: ignore[no-untyped-def]
        request: Request, exc: Exception
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", None)
        logger.exception("Unhandled API exception: %s", exc)
        payload = CommonErrorResponse(
            error_code=ApiErrorCode.INTERNAL_ERROR.value,
            message="Internal server error",
            trace_id=trace_id,
        )
        return JSONResponse(status_code=500, content=payload.model_dump())

    @app.get("/v1/health")
    async def health() -> HealthResponse:
        """Health check endpoint."""
        return HealthResponse(status="ok")

    @app.get("/health")
    async def legacy_health() -> HealthResponse:
        """Legacy health endpoint for notebook compatibility."""
        return HealthResponse(status="ok")

    @app.get("/v1/metadata", response_model=MetadataResponse)
    async def metadata() -> MetadataResponse:
        """Metadata endpoint - service info, auth, and data source health."""
        settings = app.state.settings
        router = getattr(app.state, "router", None)
        if router is not None:
            registered_data_sources = router.list_source_ids()
            data_source_health = await router.health_check_all()
        else:
            registered_data_sources = []
            data_source_health = {}
        return MetadataResponse(
            service_name=settings.service_name,
            service_version=settings.service_version,
            environment=settings.environment,
            auth_enabled=settings.api_auth_enabled,
            registered_data_sources=registered_data_sources,
            data_source_health=data_source_health,
        )

    @app.post(
        "/v1/chat",
        response_model=ChatResponse,
        responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    async def chat(
        body: ChatRequest,
        request: Request,
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
    ) -> ChatResponse:
        """Chat endpoint - delegates to orchestrator.chat."""
        validate_bearer_token(authorization=authorization, settings=app.state.settings)
        orch = app.state.orchestrator
        if orch is None:
            raise orchestrator_not_configured_error()

        selected_source_id = body.metadata.get("source_id") if body.metadata else None
        embedding_service = getattr(app.state, "embedding_service", None)
        if selected_source_id:
            locked_cfg = load_embedding_config(selected_source_id)
            if locked_cfg:
                svc_key = f"{locked_cfg.get('vendor')}:{locked_cfg.get('model')}"
                embedding_service = getattr(app.state, "embedding_services", {}).get(
                    svc_key, embedding_service
                )
        schema_context = await build_chat_knowledge_context(
            source_id=selected_source_id,
            user_message=body.user_message,
            embedding_service=embedding_service,
            vector_store=getattr(app.state, "vector_store", None),
        )
        result = await orch.chat(
            conversation_id=body.conversation_id,
            user_message=body.user_message,
            user_id=body.user_id,
            preferred_source_id=selected_source_id,
            schema_context=schema_context,
        )
        logger.info(
            "chat_request_completed",
            extra={
                "trace_id": getattr(request.state, "trace_id", None),
                "conversation_id": body.conversation_id,
            },
        )
        return ChatResponse(
            assistant_content=result["assistant_content"],
            tool_outputs=result["tool_outputs"],
        )

    @app.post("/api/vanna/v2/chat_poll")
    async def legacy_chat_poll(
        body: dict,
        request: Request,
    ) -> JSONResponse:
        """Legacy poll endpoint compatible with vanna notebook frontend."""
        orch = app.state.orchestrator
        if orch is None:
            raise orchestrator_not_configured_error()

        conversation_id = str(body.get("conversation_id") or str(uuid.uuid4()))
        request_id = str(body.get("request_id") or str(uuid.uuid4()))
        user_message = str(body.get("message") or "")
        metadata = body.get("metadata") or {}
        selected_source_id = metadata.get("source_id")
        embedding_service = getattr(app.state, "embedding_service", None)
        if selected_source_id:
            locked_cfg = load_embedding_config(selected_source_id)
            if locked_cfg:
                svc_key = f"{locked_cfg.get('vendor')}:{locked_cfg.get('model')}"
                embedding_service = getattr(app.state, "embedding_services", {}).get(
                    svc_key, embedding_service
                )
        schema_context = await build_chat_knowledge_context(
            source_id=selected_source_id,
            user_message=user_message,
            embedding_service=embedding_service,
            vector_store=getattr(app.state, "vector_store", None),
        )

        result = await orch.chat(
            conversation_id=conversation_id,
            user_message=user_message,
            user_id=None,
            preferred_source_id=selected_source_id,
            schema_context=schema_context,
        )
        chunk = _build_simple_chunk(
            text=result["assistant_content"],
            conversation_id=conversation_id,
            request_id=request_id,
        )
        return JSONResponse(
            {
                "conversation_id": conversation_id,
                "request_id": request_id,
                "chunks": [chunk],
            }
        )

    @app.post("/api/vanna/v2/chat_sse")
    async def legacy_chat_sse(
        body: dict,
        request: Request,
    ) -> StreamingResponse:
        """Legacy SSE endpoint compatible with vanna notebook frontend."""
        orch = app.state.orchestrator
        if orch is None:
            raise orchestrator_not_configured_error()

        conversation_id = str(body.get("conversation_id") or str(uuid.uuid4()))
        request_id = str(body.get("request_id") or str(uuid.uuid4()))
        user_message = str(body.get("message") or "")
        metadata = body.get("metadata") or {}
        selected_source_id = metadata.get("source_id")
        embedding_service = getattr(app.state, "embedding_service", None)
        if selected_source_id:
            locked_cfg = load_embedding_config(selected_source_id)
            if locked_cfg:
                svc_key = f"{locked_cfg.get('vendor')}:{locked_cfg.get('model')}"
                embedding_service = getattr(app.state, "embedding_services", {}).get(
                    svc_key, embedding_service
                )
        schema_context = await build_chat_knowledge_context(
            source_id=selected_source_id,
            user_message=user_message,
            embedding_service=embedding_service,
            vector_store=getattr(app.state, "vector_store", None),
        )

        result = await orch.chat(
            conversation_id=conversation_id,
            user_message=user_message,
            user_id=None,
            preferred_source_id=selected_source_id,
            schema_context=schema_context,
        )
        chunk = _build_simple_chunk(
            text=result["assistant_content"],
            conversation_id=conversation_id,
            request_id=request_id,
        )

        async def event_stream():
            yield f"data: {dumps(chunk, ensure_ascii=True)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app

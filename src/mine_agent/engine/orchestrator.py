from __future__ import annotations

import logging
from typing import Dict, List

from mine_agent.core.llm.base import LlmService
from mine_agent.core.llm.models import LlmMessage, LlmRequest
from mine_agent.core.storage.base import ConversationStore
from mine_agent.core.storage.models import Message
from mine_agent.core.tool.models import ToolContext
from mine_agent.core.tool.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_ITERATIONS = 10
LLM_ERROR_MESSAGE = "调用 LLM 时发生错误，请稍后重试。"
TOOL_ERROR_PREFIX = "[工具执行异常] "


class Orchestrator:
    def __init__(
        self,
        llm_service: LlmService,
        tool_registry: ToolRegistry,
        conversation_store: ConversationStore,
        max_tool_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
    ) -> None:
        self._llm_service = llm_service
        self._tool_registry = tool_registry
        self._conversation_store = conversation_store
        self._max_tool_iterations = max_tool_iterations

    async def chat(
        self,
        conversation_id: str,
        user_message: str,
        user_id: str | None = None,
        preferred_source_id: str | None = None,
        schema_context: str | None = None,
        trace_id: str | None = None,
    ) -> Dict[str, object]:
        await self._conversation_store.append_message(
            conversation_id=conversation_id,
            message=Message(role="user", content=user_message),
        )

        logger.info(
            "chat_turn_start",
            extra={
                "conversation_id": conversation_id,
                "user_id": user_id or "anonymous",
                "user_message_len": len(user_message),
                "trace_id": trace_id,
            },
        )

        history = await self._conversation_store.get_messages(conversation_id=conversation_id)
        llm_messages: List[LlmMessage] = [
            LlmMessage(
                role=msg.role,
                content=msg.content,
                tool_call_id=getattr(msg, "tool_call_id", None),
                tool_calls=getattr(msg, "tool_calls", None),
            )
            for msg in history
        ]
        tool_outputs: List[str] = []
        llm_rounds: List[Dict[str, object]] = []
        tool_results: List[Dict[str, object]] = []
        assistant_content = ""
        iteration = 0

        def _truncate_content(text: str, max_len: int = 2000) -> str:
            if not text:
                return ""
            return text[:max_len] + ("..." if len(text) > max_len else "")

        while iteration < self._max_tool_iterations:
            try:
                request = LlmRequest(
                    messages=llm_messages,
                    tools=self._tool_registry.get_schemas(),
                    tool_choice=None,
                    system_prompt=self._build_system_prompt(
                        preferred_source_id=preferred_source_id,
                        has_tool_history=iteration > 0,
                        schema_context=schema_context,
                    ),
                )
                response = await self._llm_service.send_request(request=request)
            except Exception as e:  # noqa: BLE001
                logger.exception("LLM request failed: %s", e)
                logger.info(
                    "chat_turn_complete",
                    extra={
                        "conversation_id": conversation_id,
                        "user_id": user_id or "anonymous",
                        "iteration": iteration,
                        "tool_calls_count": len(tool_outputs),
                        "final": True,
                        "llm_error": type(e).__name__,
                        "trace_id": trace_id,
                    },
                )
                return {
                    "assistant_content": f"{LLM_ERROR_MESSAGE} ({type(e).__name__}: {e!s})",
                    "tool_outputs": tool_outputs,
                    "llm_rounds": llm_rounds,
                    "tool_results": tool_results,
                }

            tool_calls_list = [
                {"name": tc.name, "arguments": tc.arguments} for tc in (response.tool_calls or [])
            ]
            is_final = not response.tool_calls
            llm_rounds.append({
                "iteration": iteration,
                "assistant_content": response.content or "",
                "tool_calls": tool_calls_list,
                "is_final": is_final,
            })

            if not response.tool_calls:
                assistant_content = response.content or ""
                logger.info(
                    "chat_turn_complete",
                    extra={
                        "conversation_id": conversation_id,
                        "user_id": user_id or "anonymous",
                        "iteration": iteration,
                        "tool_calls_count": 0,
                        "final": True,
                        "trace_id": trace_id,
                    },
                )
                break

            iteration += 1
            tool_names = [tc.name for tc in response.tool_calls]
            logger.info(
                "chat_turn_tool_iter",
                extra={
                    "conversation_id": conversation_id,
                    "user_id": user_id or "anonymous",
                    "iteration": iteration,
                    "tool_calls": tool_names,
                    "tool_calls_count": len(tool_names),
                    "trace_id": trace_id,
                },
            )
            assistant_msg = LlmMessage(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls,
            )
            llm_messages.append(assistant_msg)
            await self._conversation_store.append_message(
                conversation_id=conversation_id,
                message=Message(
                    role="assistant",
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                ),
            )

            context = ToolContext(
                user_id=user_id,
                conversation_id=conversation_id,
                metadata={
                    "default_source_id": preferred_source_id
                }
                if preferred_source_id
                else {},
            )
            for tool_call in response.tool_calls:
                try:
                    result = await self._tool_registry.execute(
                        tool_name=tool_call.name,
                        args=tool_call.arguments,
                        context=context,
                    )
                    output = result.content
                    tool_results.append({
                        "tool_name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "content": _truncate_content(result.content or ""),
                        "metadata_summary": result.metadata if result.metadata else None,
                        "error": None,
                    })
                except Exception as e:  # noqa: BLE001
                    logger.exception("Tool %s failed: %s", tool_call.name, e)
                    output = f"{TOOL_ERROR_PREFIX}{type(e).__name__}: {e!s}"
                    tool_results.append({
                        "tool_name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "content": _truncate_content(output),
                        "metadata_summary": None,
                        "error": f"{type(e).__name__}: {e!s}",
                    })
                tool_outputs.append(output)
                llm_messages.append(
                    LlmMessage(
                        role="tool",
                        content=output,
                        tool_call_id=tool_call.id,
                    )
                )
                await self._conversation_store.append_message(
                    conversation_id=conversation_id,
                    message=Message(
                        role="tool",
                        content=output,
                        tool_call_id=tool_call.id,
                    ),
                )

        if iteration >= self._max_tool_iterations and not assistant_content:
            assistant_content = (
                f"已达到最大工具调用轮数 ({self._max_tool_iterations})，已截断。"
            )
            logger.info(
                "chat_turn_complete",
                extra={
                    "conversation_id": conversation_id,
                    "user_id": user_id or "anonymous",
                    "iteration": iteration,
                    "tool_calls_count": len(tool_outputs),
                    "final": True,
                    "truncated": True,
                    "trace_id": trace_id,
                },
            )

        if assistant_content:
            await self._conversation_store.append_message(
                conversation_id=conversation_id,
                message=Message(role="assistant", content=assistant_content),
            )

        return {
            "assistant_content": assistant_content,
            "tool_outputs": tool_outputs,
            "llm_rounds": llm_rounds,
            "tool_results": tool_results,
        }

    @staticmethod
    def _build_system_prompt(
        preferred_source_id: str | None,
        has_tool_history: bool,
        schema_context: str | None = None,
    ) -> str | None:
        if has_tool_history:
            return (
                "You are a data assistant. "
                "Now continue from tool result, provide a concise user-friendly summary. "
                "Avoid starting new SQL queries unless the user message explicitly asks to refine or rerun."
            )

        base = (
            "You are a data analyst assistant. "
            "Use the available tools to help the user. "
            "When the user asks a question that requires querying data (e.g. statistics, lists, aggregations, filters), "
            "call query_data with a read-only SQL statement. "
            "When the user greets, asks for help, or asks something that does not need database data, "
            "answer directly without calling tools. "
        )
        if preferred_source_id:
            base += (
                f"Use source_id='{preferred_source_id}' as the default data source for SQL. "
            )
        if schema_context:
            # schema_context 由 build_chat_knowledge_context 生成，已为结构化格式
            # （含 ## Candidate Tables / ## Recommended Join Paths / ## Domain Hints / ## SQL Constraints）
            base += f"Use the following schema context to generate accurate SQL. {schema_context} "
        base += (
            "Do not run table/schema exploration unless the user explicitly asks for metadata. "
            "Prefer a single query then summarize results concisely."
        )
        return base

"""Orchestrator resilience tests: LLM errors, tool errors, max_tool_iterations truncation."""

from __future__ import annotations

from typing import List

import pytest

from mine_agent.core.llm.base import LlmService
from mine_agent.core.llm.models import (
    LlmRequest,
    LlmResponse,
    ToolCall,
    ToolSchema,
)
from mine_agent.core.tool.base import Tool
from mine_agent.core.tool.models import ToolContext, ToolResult
from mine_agent.engine.orchestrator import (
    DEFAULT_MAX_TOOL_ITERATIONS,
    LLM_ERROR_MESSAGE,
    TOOL_ERROR_PREFIX,
    Orchestrator,
)
from mine_agent.integrations.local.storage import InMemoryConversationStore
from mine_agent.core.tool.registry import ToolRegistry


class FailingLlmService(LlmService):
    """LLM that always raises on send_request."""

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        raise RuntimeError("LLM service unavailable")

    async def stream_request(self, request: LlmRequest):
        raise NotImplementedError

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return []


class AlwaysToolCallsLlmService(LlmService):
    """LLM that always returns tool_calls until max iterations."""

    def __init__(self, max_returns: int = 10) -> None:
        self._call_count = 0
        self._max_returns = max_returns

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self._call_count += 1
        if self._call_count <= self._max_returns:
            return LlmResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id=f"tc_{self._call_count}",
                        name="failing_tool",
                        arguments={"x": 1},
                    )
                ],
                finish_reason="tool_calls",
            )
        return LlmResponse(
            content="Done.",
            finish_reason="stop",
        )

    async def stream_request(self, request: LlmRequest):
        raise NotImplementedError

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return []


class FailingTool(Tool):
    """Tool that always raises on execute."""

    @property
    def name(self) -> str:
        return "failing_tool"

    @property
    def description(self) -> str:
        return "A tool that always fails"

    def get_args_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
        )

    async def execute(self, args: dict, context: ToolContext) -> ToolResult:
        raise ValueError("Intentional tool failure for testing")


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo_tool"

    @property
    def description(self) -> str:
        return "Return echo content"

    def get_args_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        )

    async def execute(self, args: dict, context: ToolContext) -> ToolResult:
        return ToolResult(content=f"echo:{args['value']}")


class StrictToolSequenceLlmService(LlmService):
    """Reject requests with invalid assistant/tool sequence."""

    def __init__(self) -> None:
        self._call_count = 0

    @staticmethod
    def _validate_tool_sequence(request: LlmRequest) -> None:
        for idx, message in enumerate(request.messages):
            if message.role != "tool":
                continue
            tool_call_id = message.tool_call_id
            if not tool_call_id:
                raise RuntimeError("tool message missing tool_call_id")

            has_preceding_assistant = False
            for prev in request.messages[:idx]:
                if prev.role != "assistant" or not prev.tool_calls:
                    continue
                if any(tc.id == tool_call_id for tc in prev.tool_calls):
                    has_preceding_assistant = True
                    break
            if not has_preceding_assistant:
                raise RuntimeError("tool message without preceding assistant tool_calls")

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self._validate_tool_sequence(request=request)
        self._call_count += 1

        has_any_tool_messages = any(m.role == "tool" for m in request.messages)
        if not has_any_tool_messages:
            return LlmResponse(
                content="running tool",
                tool_calls=[
                    ToolCall(
                        id="tc-seq-1",
                        name="echo_tool",
                        arguments={"value": "ok"},
                    )
                ],
                finish_reason="tool_calls",
            )

        return LlmResponse(content="done", finish_reason="stop")

    async def stream_request(self, request: LlmRequest):
        raise NotImplementedError

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return []


class ToolChoiceCaptureLlmService(LlmService):
    """Capture request metadata and emit a short two-turn flow for assertions."""

    def __init__(self) -> None:
        self.requests: List[LlmRequest] = []

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        if request.tool_choice == "required":
            return LlmResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        name="echo_tool",
                        arguments={"value": "ok"},
                    )
                ],
                finish_reason="tool_calls",
            )

        return LlmResponse(content="done", finish_reason="stop")

    async def stream_request(self, request: LlmRequest):
        raise NotImplementedError

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return []


@pytest.mark.asyncio
async def test_llm_error_returns_readable_response() -> None:
    """LLM 抛错时返回可读响应，不抛出未处理异常。"""
    registry = ToolRegistry()
    orchestrator = Orchestrator(
        llm_service=FailingLlmService(),
        tool_registry=registry,
        conversation_store=InMemoryConversationStore(),
    )
    result = await orchestrator.chat(
        conversation_id="conv-llm-err",
        user_message="hello",
    )
    assert "assistant_content" in result
    assert LLM_ERROR_MESSAGE in result["assistant_content"]
    assert "RuntimeError" in result["assistant_content"]
    assert result["tool_outputs"] == []


@pytest.mark.asyncio
async def test_tool_error_captured_in_tool_outputs() -> None:
    """Tool 抛错时异常被捕获并写入 tool_outputs。"""
    registry = ToolRegistry()
    registry.register(FailingTool())
    orchestrator = Orchestrator(
        llm_service=AlwaysToolCallsLlmService(max_returns=1),
        tool_registry=registry,
        conversation_store=InMemoryConversationStore(),
    )
    result = await orchestrator.chat(
        conversation_id="conv-tool-err",
        user_message="trigger tool",
    )
    assert "assistant_content" in result
    assert len(result["tool_outputs"]) >= 1
    assert TOOL_ERROR_PREFIX in result["tool_outputs"][0]
    assert "ValueError" in result["tool_outputs"][0]
    assert "Intentional tool failure" in result["tool_outputs"][0]


@pytest.mark.asyncio
async def test_max_tool_iterations_truncation() -> None:
    """超过 max_tool_iterations 时截断。"""
    registry = ToolRegistry()
    registry.register(FailingTool())
    max_iter = 3
    llm = AlwaysToolCallsLlmService(max_returns=10)
    orchestrator = Orchestrator(
        llm_service=llm,
        tool_registry=registry,
        conversation_store=InMemoryConversationStore(),
        max_tool_iterations=max_iter,
    )
    result = await orchestrator.chat(
        conversation_id="conv-max-iter",
        user_message="trigger",
    )
    assert "assistant_content" in result
    assert f"已达到最大工具调用轮数 ({max_iter})" in result["assistant_content"]
    assert len(result["tool_outputs"]) == max_iter
    assert llm._call_count == max_iter


@pytest.mark.asyncio
async def test_conversation_persists_assistant_tool_calls_for_next_turn() -> None:
    """Second turn should not fail strict tool/assistant ordering validation."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    llm = StrictToolSequenceLlmService()
    store = InMemoryConversationStore()
    orchestrator = Orchestrator(
        llm_service=llm,
        tool_registry=registry,
        conversation_store=store,
    )

    first = await orchestrator.chat(
        conversation_id="conv-seq",
        user_message="first turn",
        user_id="u1",
    )
    assert first["assistant_content"] == "done"

    second = await orchestrator.chat(
        conversation_id="conv-seq",
        user_message="second turn",
        user_id="u1",
    )
    assert second["assistant_content"] == "done"


@pytest.mark.asyncio
async def test_tool_choice_is_always_none_model_decides() -> None:
    """Orchestrator always sends tool_choice=None so the model decides whether to call tools."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    llm = ToolChoiceCaptureLlmService()
    orchestrator = Orchestrator(
        llm_service=llm,
        tool_registry=registry,
        conversation_store=InMemoryConversationStore(),
    )

    result = await orchestrator.chat(
        conversation_id="conv-model-decides",
        user_message="查询最低工资员工的经理是谁",
        user_id="u2",
    )

    assert llm.requests
    assert llm.requests[0].tool_choice is None
    assert llm.requests[0].system_prompt is not None
    assert "query_data" in llm.requests[0].system_prompt
    assert "answer directly" in llm.requests[0].system_prompt
    assert result["assistant_content"] == "done"


@pytest.mark.asyncio
async def test_greeting_turn_also_uses_tool_choice_none() -> None:
    """Greeting messages use same tool_choice=None; model may answer without tools."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    llm = ToolChoiceCaptureLlmService()
    orchestrator = Orchestrator(
        llm_service=llm,
        tool_registry=registry,
        conversation_store=InMemoryConversationStore(),
    )

    result = await orchestrator.chat(
        conversation_id="conv-greeting",
        user_message="你好",
        user_id="u2",
    )

    assert llm.requests
    assert llm.requests[0].tool_choice is None
    assert result["assistant_content"] == "done"

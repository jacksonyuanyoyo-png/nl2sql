"""E2E test helpers: mock LLM and tools for full-chain testing."""

from __future__ import annotations

from typing import List

from mine_agent.core.llm.base import LlmService
from mine_agent.core.llm.models import (
    LlmRequest,
    LlmResponse,
    ToolCall,
    ToolSchema,
)
from mine_agent.core.tool.base import Tool
from mine_agent.core.tool.models import ToolContext, ToolResult


class ToolCallLlmService(LlmService):
    """LLM that returns tool_calls for the first N requests, then stops."""

    def __init__(self, tool_name: str = "failing_tool", max_returns: int = 1) -> None:
        self._tool_name = tool_name
        self._call_count = 0
        self._max_returns = max_returns

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        self._call_count += 1
        has_tool_messages = any(m.role == "tool" for m in request.messages)
        if has_tool_messages or self._call_count > self._max_returns:
            return LlmResponse(
                content="处理完成。",
                finish_reason="stop",
            )
        return LlmResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id=f"tc_{self._call_count}",
                    name=self._tool_name,
                    arguments={"x": 1},
                )
            ],
            finish_reason="tool_calls",
        )

    async def stream_request(self, request: LlmRequest):
        raise NotImplementedError

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return []


class FailingTool(Tool):
    """Tool that always raises on execute - for resilience testing."""

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
        raise ValueError("Intentional tool failure for E2E testing")

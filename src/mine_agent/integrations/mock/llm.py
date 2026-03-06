from __future__ import annotations

from typing import AsyncGenerator, List

from mine_agent.core.llm.base import LlmService
from mine_agent.core.llm.models import (
    LlmRequest,
    LlmResponse,
    LlmStreamChunk,
    ToolCall,
    ToolSchema,
)


class MockLlmService(LlmService):
    def __init__(self, default_source_id: str = "oracle_demo") -> None:
        self._default_source_id = default_source_id

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        has_tool_messages = any(m.role == "tool" for m in request.messages)
        if has_tool_messages:
            return LlmResponse(
                content="查询已完成。",
                finish_reason="stop",
            )

        latest_user_message = ""
        for message in reversed(request.messages):
            if message.role == "user":
                latest_user_message = message.content
                break

        if "select" in latest_user_message.lower():
            return LlmResponse(
                content="我将调用 query_data 执行查询。",
                tool_calls=[
                    ToolCall(
                        id="tool_call_1",
                        name="query_data",
                        arguments={
                            "source_id": self._default_source_id,
                            "sql": latest_user_message,
                            "limit": 100,
                        },
                    )
                ],
                finish_reason="tool_calls",
            )

        return LlmResponse(content="收到。你可以直接发一条 SQL，我会尝试查询。", finish_reason="stop")

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        response = await self.send_request(request=request)
        if response.content:
            yield LlmStreamChunk(content=response.content)
        if response.tool_calls:
            yield LlmStreamChunk(tool_calls=response.tool_calls, finish_reason=response.finish_reason)
        else:
            yield LlmStreamChunk(finish_reason=response.finish_reason)

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        return []

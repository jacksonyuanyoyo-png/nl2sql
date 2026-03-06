from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator, List

from mine_agent.core.llm.models import (
    LlmRequest,
    LlmResponse,
    LlmStreamChunk,
    ToolSchema,
)


class LlmService(ABC):
    @abstractmethod
    async def send_request(self, request: LlmRequest) -> LlmResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        raise NotImplementedError

    @abstractmethod
    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        raise NotImplementedError

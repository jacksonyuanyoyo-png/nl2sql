from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from mine_agent.core.llm.models import ToolSchema
from mine_agent.core.tool.models import ToolContext, ToolResult


class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    def access_groups(self) -> Optional[List[str]]:
        return None

    @abstractmethod
    def get_args_schema(self) -> ToolSchema:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, args: Dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError

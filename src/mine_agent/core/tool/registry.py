from __future__ import annotations

from typing import Dict, List

from mine_agent.core.llm.models import ToolSchema
from mine_agent.core.tool.base import Tool
from mine_agent.core.tool.models import ToolContext, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_schemas(self) -> List[ToolSchema]:
        return [tool.get_args_schema() for tool in self._tools.values()]

    async def execute(self, tool_name: str, args: dict, context: ToolContext) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool not found: {tool_name}")
        return await tool.execute(args=args, context=context)

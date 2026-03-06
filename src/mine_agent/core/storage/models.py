from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field
from mine_agent.core.llm.models import ToolCall


class Message(BaseModel):
    role: str
    content: str
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class Conversation(BaseModel):
    conversation_id: str
    messages: List[Message] = Field(default_factory=list)

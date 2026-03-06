from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class LlmMessage(BaseModel):
    role: str
    content: str = ""
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class LlmRequest(BaseModel):
    messages: List[LlmMessage]
    tools: Optional[List[ToolSchema]] = None
    system_prompt: Optional[str] = None
    tool_choice: Optional[str] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None


class LlmResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class LlmStreamChunk(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None

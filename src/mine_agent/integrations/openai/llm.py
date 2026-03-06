from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

from mine_agent.core.llm.base import LlmService
from mine_agent.core.llm.models import (
    LlmRequest,
    LlmResponse,
    LlmStreamChunk,
    ToolCall,
    ToolSchema,
)


class OpenAILlmService(LlmService):
    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        try:
            from openai import OpenAI
        except Exception as e:
            raise ImportError(
                "openai package is required. Install with: pip install openai"
            ) from e

        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        base_url = base_url or os.getenv("OPENAI_BASE_URL")

        client_kwargs: Dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)

    async def send_request(self, request: LlmRequest) -> LlmResponse:
        payload = self._build_payload(request=request)
        response = self._client.chat.completions.create(**payload, stream=False)

        if not response.choices:
            return LlmResponse(content=None, tool_calls=None, finish_reason=None)

        choice = response.choices[0]
        content = getattr(choice.message, "content", None)
        tool_calls = self._extract_tool_calls(choice.message)

        usage: Dict[str, int] = {}
        if getattr(response, "usage", None):
            usage = {
                "prompt_tokens": int(getattr(response.usage, "prompt_tokens", 0)),
                "completion_tokens": int(getattr(response.usage, "completion_tokens", 0)),
                "total_tokens": int(getattr(response.usage, "total_tokens", 0)),
            }

        return LlmResponse(
            content=content,
            tool_calls=tool_calls or None,
            finish_reason=getattr(choice, "finish_reason", None),
            usage=usage or None,
        )

    async def stream_request(
        self, request: LlmRequest
    ) -> AsyncGenerator[LlmStreamChunk, None]:
        response = await self.send_request(request=request)
        if response.content:
            yield LlmStreamChunk(content=response.content)
        if response.tool_calls:
            yield LlmStreamChunk(
                tool_calls=response.tool_calls,
                finish_reason=response.finish_reason,
            )
        else:
            yield LlmStreamChunk(finish_reason=response.finish_reason or "stop")

    async def validate_tools(self, tools: List[ToolSchema]) -> List[str]:
        errors: List[str] = []
        for tool in tools:
            if not tool.name:
                errors.append("Tool name is required")
        return errors

    def _build_payload(self, request: LlmRequest) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        for message in request.messages:
            payload: Dict[str, Any] = {
                "role": message.role,
                "content": message.content,
            }
            if message.role == "tool" and message.tool_call_id:
                payload["tool_call_id"] = message.tool_call_id
            elif message.role == "assistant" and message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(tool_call.arguments),
                        },
                    }
                    for tool_call in message.tool_calls
                ]
            messages.append(payload)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": request.temperature,
        }

        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = request.tool_choice or "auto"

        return payload

    def _extract_tool_calls(self, message: Any) -> List[ToolCall]:
        result: List[ToolCall] = []
        raw_tool_calls = getattr(message, "tool_calls", None) or []

        for tool_call in raw_tool_calls:
            fn = getattr(tool_call, "function", None)
            if fn is None:
                continue
            args_raw = getattr(fn, "arguments", "{}")
            try:
                loaded = json.loads(args_raw)
                arguments = loaded if isinstance(loaded, dict) else {"args": loaded}
            except Exception:
                arguments = {"_raw": args_raw}

            result.append(
                ToolCall(
                    id=getattr(tool_call, "id", "tool_call"),
                    name=getattr(fn, "name", "tool"),
                    arguments=arguments,
                )
            )
        return result

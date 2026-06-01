"""
Anthropic Claude provider.

Claude uses content blocks and a `stop_reason == "tool_use"` loop rather than
OpenAI's tool_calls. The system prompt is a top-level kwarg, not a message. The
loop is ported from chat-claude.py. Messages are stored in Claude-native form, so
a conversation should stay with the Claude provider (the conversation row records
its provider).
"""

import time
from typing import Any

from anthropic import Anthropic

from mcp_core import to_claude_tools
from .base import CallTool, OnEvent, Provider

MAX_TOKENS = 4096


class ClaudeProvider(Provider):
    name = "Claude"

    def __init__(self, api_key: str) -> None:
        self.client = Anthropic(api_key=api_key)

    def chat_turn(
        self,
        messages: list[dict[str, Any]],
        mcp_tools: list[dict[str, Any]],
        system_prompt: str,
        model: str,
        call_tool: CallTool,
        on_event: OnEvent = None,
    ) -> str:
        kwargs: dict[str, Any] = {"model": model, "max_tokens": MAX_TOKENS, "messages": messages}
        if system_prompt:
            kwargs["system"] = system_prompt
        tools = to_claude_tools(mcp_tools)
        if tools:
            kwargs["tools"] = tools

        response = self._complete(kwargs, model, "initial_request", on_event)

        while response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": self._serialize(response.content)})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    self._emit(on_event, "tool_call", name=block.name, arguments=block.input)
                    result = call_tool(block.name, block.input)
                    self._emit(on_event, "tool_result", name=block.name, result=result)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})

            response = self._complete(kwargs, model, "tool_followup", on_event)

        final_text = "\n".join(b.text for b in response.content if b.type == "text")
        messages.append({"role": "assistant", "content": self._serialize(response.content)})
        return final_text

    def _complete(self, kwargs: dict, model: str, call_type: str, on_event: OnEvent):
        """Make one API call, emit an llm_call event (tokens + latency), return response."""
        t0 = time.perf_counter()
        response = self.client.messages.create(**kwargs)
        dur_ms = int((time.perf_counter() - t0) * 1000)

        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", None)
        out_tok = getattr(usage, "output_tokens", None)
        total = (in_tok or 0) + (out_tok or 0) if (in_tok is not None or out_tok is not None) else None
        tools_requested = [b.name for b in response.content if b.type == "tool_use"]
        preview = "\n".join(b.text for b in response.content if b.type == "text")[:200]
        self._emit(
            on_event, "llm_call",
            provider=self.name, model=model, call_type=call_type,
            prompt_tokens=in_tok, completion_tokens=out_tok, total_tokens=total,
            duration_ms=dur_ms,
            tools_requested=tools_requested,
            response_preview=preview,
        )
        return response

    @staticmethod
    def _serialize(content) -> list[dict[str, Any]]:
        """Convert Claude content blocks to JSON-serializable dicts for storage."""
        out = []
        for block in content:
            if block.type == "text":
                out.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                out.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return out

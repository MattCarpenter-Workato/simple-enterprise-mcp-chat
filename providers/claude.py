"""
Anthropic Claude provider.

Claude uses content blocks and a `stop_reason == "tool_use"` loop rather than
OpenAI's tool_calls. The system prompt is a top-level kwarg, not a message. The
loop is ported from chat-claude.py. Messages are stored in Claude-native form, so
a conversation should stay with the Claude provider (the conversation row records
its provider).
"""

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

        response = self.client.messages.create(**kwargs)

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

            response = self.client.messages.create(**kwargs)

        final_text = "\n".join(b.text for b in response.content if b.type == "text")
        messages.append({"role": "assistant", "content": self._serialize(response.content)})
        return final_text

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

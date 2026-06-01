"""
OpenAI-compatible provider — serves OpenAI, Ollama, and LM Studio.

All three speak the OpenAI Chat Completions API with `tools`/`tool_calls`. They
differ only in base_url, api_key, and model, so one implementation (using the
`openai` SDK) covers all three. The tool-calling loop is ported from
chat-openai.py.
"""

import json
from typing import Any, Optional

from openai import OpenAI

from mcp_core import to_openai_tools
from .base import CallTool, OnEvent, Provider


class OpenAILikeProvider(Provider):
    def __init__(self, name: str, api_key: str, base_url: Optional[str] = None) -> None:
        self.name = name
        # The OpenAI SDK requires a non-empty api_key even for local servers that
        # ignore it (Ollama, LM Studio).
        self.client = OpenAI(api_key=api_key or "not-needed", base_url=base_url)

    def chat_turn(
        self,
        messages: list[dict[str, Any]],
        mcp_tools: list[dict[str, Any]],
        system_prompt: str,
        model: str,
        call_tool: CallTool,
        on_event: OnEvent = None,
    ) -> str:
        # System prompt is the first message (OpenAI convention). Replace any
        # existing leading system message so prompt changes take effect.
        convo = list(messages)
        if system_prompt:
            convo = [m for m in convo if m.get("role") != "system"]
            convo.insert(0, {"role": "system", "content": system_prompt})

        tools = to_openai_tools(mcp_tools)
        kwargs: dict[str, Any] = {"model": model, "messages": convo}
        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        while msg.tool_calls:
            # Record the assistant's tool request (serializable form).
            convo.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                self._emit(on_event, "tool_call", name=name, arguments=args)
                result = call_tool(name, args)
                self._emit(on_event, "tool_result", name=name, result=result)
                convo.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            response = self.client.chat.completions.create(**kwargs)
            msg = response.choices[0].message

        final_text = msg.content or ""
        # Mirror the new turns (minus the system message) back into the caller's list.
        messages[:] = [m for m in convo if m.get("role") != "system"]
        messages.append({"role": "assistant", "content": final_text})
        return final_text

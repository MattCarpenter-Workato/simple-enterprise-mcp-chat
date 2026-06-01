"""
Provider interface for the chat backend.

A Provider runs one user turn: it sends the conversation to the LLM, executes any
tool calls it requests against MCP (looping until the model produces a final text
answer), and returns that text. The conversation `messages` list is mutated in
place so the caller can persist the full history (including provider-native tool
blocks).

`on_event(kind, payload)` is an optional callback the UI uses to show live
progress; kinds: "tool_call" {name, arguments}, "tool_result" {name, result}.
"""

from typing import Any, Callable, Optional

OnEvent = Optional[Callable[[str, dict], None]]
CallTool = Callable[[str, dict], str]


class Provider:
    """Base class. Subclasses implement chat_turn."""

    #: Human-readable provider name (e.g. "OpenAI", "Claude").
    name: str = "base"

    def chat_turn(
        self,
        messages: list[dict[str, Any]],
        mcp_tools: list[dict[str, Any]],
        system_prompt: str,
        model: str,
        call_tool: CallTool,
        on_event: OnEvent = None,
    ) -> str:
        raise NotImplementedError

    @staticmethod
    def _emit(on_event: OnEvent, kind: str, **payload) -> None:
        if on_event:
            on_event(kind, payload)

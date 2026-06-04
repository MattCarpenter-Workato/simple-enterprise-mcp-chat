"""
Shared turn runner for the Chat and Benchmark pages.

`run_turn` executes one user message against a provider: it wires up the
tool-call logger (latency, returned-data size, success/error, retry attempt) and
the llm_call logger (tokens + latency), measures the end-to-end turn time, and
returns the final answer text plus that total. Both the interactive Chat page and
the Benchmark page go through here so logging stays identical.
"""

import json
import logging
import time
from typing import Any, Callable, Optional

import db

tool_logger = logging.getLogger("mcpchat.toolio")

OnStatus = Optional[Callable[[str], None]]


def server_of(tool_name: str) -> Optional[str]:
    """The MCP server name encoded in a prefixed tool name (`server__tool`)."""
    return tool_name.split("__")[0] if "__" in tool_name else None


def run_turn(
    *,
    client,
    provider,
    provider_name: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    sys_prompt: str,
    user_prompt: str,
    conv_id: int,
    benchmark_run_id: Optional[int] = None,
    debug_io: bool = False,
    on_status: OnStatus = None,
) -> tuple[str, int]:
    """Run one turn. Mutates `messages` in place (provider appends tool/answer
    turns). Returns (final_text, total_ms)."""

    # Nth call of each tool within this turn — attempt>1 marks a retry.
    attempts: dict[str, int] = {}

    def logged_call_tool(name: str, arguments: dict) -> str:
        attempts[name] = attempts.get(name, 0) + 1
        t0 = time.perf_counter()
        result = client.call_tool(name, arguments)
        dur = int((time.perf_counter() - t0) * 1000)
        # MCPClient.call_tool never raises; it returns an "Error..." string on
        # failure (see mcp_core.call_tool).
        text = result or ""
        success = 0 if text.lstrip().startswith("Error") else 1
        db.add_log(
            conv_id, event_type="tool_call", provider=provider_name, model=model,
            duration_ms=dur, data_chars=len(text),
            server=server_of(name), servers=server_of(name), tools=name,
            user_prompt=user_prompt,
            success=success,
            error=text if not success else None,
            attempt=attempts[name],
            benchmark_run_id=benchmark_run_id,
            detail_json=json.dumps({"arguments": arguments,
                                    "result_preview": text[:300]}),
        )
        if debug_io:
            tool_logger.info(
                "TOOL I/O conv=%s tool=%s duration_ms=%s success=%s attempt=%s job_id=%s\n"
                "  ARGS: %s\n  RESP HEADERS: %s\n  RESP BODY: %s",
                conv_id, name, dur, success, attempts[name], client.last_job_id,
                json.dumps(arguments, default=str),
                json.dumps(client.last_response_headers, default=str),
                json.dumps(client.last_response_body, default=str),
            )
        return result

    def on_event(kind: str, payload: dict) -> None:
        if kind == "tool_call":
            if on_status:
                on_status(f"🔧 Calling `{payload['name']}`…")
        elif kind == "tool_result":
            if on_status:
                preview = str(payload["result"])[:120]
                on_status(f"✓ `{payload['name']}` → {preview}")
        elif kind == "llm_call":
            requested = payload.get("tools_requested") or []
            servers = sorted({s for t in requested if (s := server_of(t))})
            db.add_log(
                conv_id, event_type="llm_call",
                provider=payload.get("provider", provider_name),
                model=payload.get("model", model),
                call_type=payload.get("call_type"),
                prompt_tokens=payload.get("prompt_tokens"),
                completion_tokens=payload.get("completion_tokens"),
                total_tokens=payload.get("total_tokens"),
                duration_ms=payload.get("duration_ms"),
                user_prompt=user_prompt, system_prompt=sys_prompt,
                servers=",".join(servers), tools=",".join(requested),
                response_preview=payload.get("response_preview"),
                benchmark_run_id=benchmark_run_id,
            )

    t0 = time.perf_counter()
    final_text = provider.chat_turn(
        messages, tools, sys_prompt, model, logged_call_tool, on_event,
    )
    total_ms = int((time.perf_counter() - t0) * 1000)
    return final_text, total_ms

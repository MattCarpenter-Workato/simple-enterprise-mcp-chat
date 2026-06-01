"""
Shared MCP (Model Context Protocol) client for the web UI.

This is the globals-free extraction of the MCP logic that was duplicated across
chat-claude.py / chat-openai.py / chat-ollama.py / chat-lmstudio.py: connect to
the enabled servers, discover their tools, and route tool calls back to the right
server. Unlike the CLI scripts, server configuration is read from SQLite (db.py),
and OAuth uses the DB-backed handler (oauth_store.py).

Tool names keep the `server__tool` prefix convention so behavior matches the CLI.
Tools are returned in MCP-native form; each provider converts them to its own
schema.
"""

import json
import logging
from typing import Any, Optional

import requests

import db
from oauth_store import get_token_for_server

logger = logging.getLogger(__name__)


class MCPClient:
    """Holds the resolved set of enabled servers and their auth headers."""

    def __init__(self) -> None:
        self.servers: dict[str, str] = {}              # name -> url
        self.headers: dict[str, dict[str, str]] = {}   # name -> http headers
        self.errors: dict[str, str] = {}               # name -> error message
        # Captured from the most recent request() — used for verbose file logging.
        self.last_response_headers: dict[str, str] = {}
        self.last_response_body: Any = None
        self.last_job_id: Optional[str] = None

    # -- connection / auth ----------------------------------------------------

    def load_servers(self) -> dict[str, str]:
        """Resolve enabled servers from the DB, acquiring OAuth tokens as needed."""
        self.servers, self.headers, self.errors = {}, {}, {}

        for s in db.list_servers(enabled_only=True):
            name, url, auth_type = s["name"], s["url"], s["auth_type"]

            if auth_type == "oauth":
                token = get_token_for_server(name, url, s.get("oauth"))
                if not token:
                    self.errors[name] = "OAuth authentication failed"
                    continue
                self.headers[name] = {"Authorization": f"Bearer {token}"}
            elif auth_type == "token":
                # A static bearer token may be stored alongside the server config.
                static = (s.get("oauth") or {}).get("token") if s.get("oauth") else None
                if static:
                    self.headers[name] = {"Authorization": f"Bearer {static}"}

            self.servers[name] = url

        return self.servers

    # -- raw JSON-RPC ---------------------------------------------------------

    def request(self, url: str, method: str, params: Optional[dict] = None,
                headers: Optional[dict] = None) -> dict:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        logger.debug("MCP REQUEST url=%s method=%s", url, method)
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        logger.debug("MCP RESPONSE status=%s", response.status_code)
        self.last_response_headers = dict(response.headers)
        self.last_response_body = data
        return data

    # -- discovery ------------------------------------------------------------

    def discover_tools(self) -> list[dict[str, Any]]:
        """Return MCP-native tool dicts for all enabled servers.

        Each entry: {"name": "server__tool", "description": str, "inputSchema": {...}}
        """
        self.load_servers()
        tools: list[dict[str, Any]] = []

        for name, url in self.servers.items():
            try:
                result = self.request(url, "tools/list", headers=self.headers.get(name))
                for tool in result.get("result", {}).get("tools", []):
                    schema = tool.get("inputSchema", {}) or {}
                    schema.setdefault("type", "object")
                    if not schema.get("properties"):
                        schema["properties"] = {}
                    tools.append({
                        "name": f"{name}__{tool['name']}",
                        "description": tool.get("description", ""),
                        "inputSchema": schema,
                    })
                logger.info("Discovered %d tools from %s", len(tools), name)
            except Exception as e:  # noqa: BLE001 - surface per-server, keep going
                self.errors[name] = str(e)
                logger.error("Failed to discover tools from %s: %s", name, e)

        return tools

    # -- execution ------------------------------------------------------------

    def call_tool(self, name: str, arguments: dict) -> str:
        """Route a prefixed tool call to the right server and return text result."""
        try:
            if "__" not in name:
                return f"Error: Invalid tool name format '{name}'. Expected 'server__tool_name'."

            server_name, tool_name = name.split("__", 1)
            if server_name not in self.servers:
                return (f"Error: Unknown server '{server_name}'. "
                        f"Available servers: {list(self.servers.keys())}")

            self.last_job_id = None
            result = self.request(
                self.servers[server_name],
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                headers=self.headers.get(server_name),
            )
            self.last_job_id = self._detect_job_id(self.last_response_headers, result)
            content = result.get("result", {}).get("content", [])
            if content:
                return content[0].get("text", str(result))
            return str(result.get("result", result))
        except Exception as e:  # noqa: BLE001
            return f"Error calling tool: {e}"

    # Header/body keys (normalized to alphanumerics) that look like a correlation
    # ID we could line up against Workato's job logs.
    _JOB_ID_KEYS = {
        "jobid", "job", "runid", "executionid", "requestid", "traceid",
        "correlationid", "workatojobid", "xrequestid", "xworkatojobid",
        "xcorrelationid", "xtraceid",
    }

    @classmethod
    def _detect_job_id(cls, headers: dict, body: Any) -> Optional[str]:
        """Best-effort scan of response headers + body (including JSON embedded in
        string fields) for anything resembling a Workato job/correlation ID."""
        norm = lambda k: "".join(ch for ch in str(k).lower() if ch.isalnum())

        for k, v in (headers or {}).items():
            if norm(k) in cls._JOB_ID_KEYS:
                return str(v)

        def scan(obj: Any) -> Optional[str]:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if norm(k) in cls._JOB_ID_KEYS and not isinstance(v, (dict, list)):
                        return str(v)
                    found = scan(v)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = scan(item)
                    if found:
                        return found
            elif isinstance(obj, str):
                # MCP wraps the recipe payload as a JSON string — parse and scan it.
                stripped = obj.strip()
                if stripped[:1] in ("{", "["):
                    try:
                        return scan(json.loads(stripped))
                    except (ValueError, TypeError):
                        return None
            return None

        return scan(body)


# -- tool-format converters (used by providers) -------------------------------

def to_openai_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP-native tools to OpenAI / Ollama / LM Studio function format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        }
        for t in mcp_tools
    ]


def to_claude_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert MCP-native tools to Anthropic's tool format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for t in mcp_tools
    ]

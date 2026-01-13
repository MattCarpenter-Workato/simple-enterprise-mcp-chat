"""
Simple MCP Chat - Claude API Integration

This script demonstrates how to connect a Python chatbot to Workato's Enterprise
MCP (Model Context Protocol) servers using Anthropic's Claude API.

What this script does:
1. Loads MCP server configurations from mcp_servers.json
2. Connects to multiple Workato MCP servers simultaneously
3. Discovers what tools are available from each server
4. Lets you chat with Claude that can use those tools to answer your questions

Key Differences from OpenAI:
- Uses Anthropic's SDK and API format (different message structure)
- Claude uses "tools" instead of "functions" terminology
- Tool results are returned as messages with tool_result content

Usage:
- python chat-claude.py
- python chat-claude.py --system-prompt "You are a helpful medical assistant."
- python chat-claude.py -s "You are a concise assistant."

Configuration:
- CLAUDE_API_KEY: Your Anthropic API key (required)
- CLAUDE_MODEL: Claude model to use (default: claude-3-5-sonnet-20241022)
- SYSTEM_PROMPT: Optional default system prompt for guiding Claude's behavior

"""

import os
import json
import requests
import argparse
import logging
from datetime import datetime
from dotenv import load_dotenv
from anthropic import Anthropic
from oauth_handler import get_token_for_server

# =============================================================================
# CONFIGURATION
# =============================================================================

# Load environment variables from .env file
load_dotenv()

# Configure logging based on environment variable
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "")
LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "true").lower() == "true"
TOKEN_LOG_FILE = os.getenv("TOKEN_LOG_FILE", "")

# Create logs directory if logging to file
if LOG_FILE:
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

# Create logs directory for token log file
if TOKEN_LOG_FILE:
    token_log_dir = os.path.dirname(TOKEN_LOG_FILE)
    if token_log_dir and not os.path.exists(token_log_dir):
        os.makedirs(token_log_dir, exist_ok=True)

# Configure logging handlers
handlers = []

# Add file handler if LOG_FILE is specified
if LOG_FILE:
    file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    handlers.append(file_handler)

# Add console handler if LOG_TO_CONSOLE is true
if LOG_TO_CONSOLE:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    handlers.append(console_handler)

# Configure logging with handlers
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    handlers=handlers,
    force=True
)
logger = logging.getLogger(__name__)

# Configure separate token usage logger
token_logger = None
if TOKEN_LOG_FILE:
    token_logger = logging.getLogger("token_usage")
    token_logger.setLevel(logging.INFO)
    token_logger.propagate = False

    token_handler = logging.FileHandler(TOKEN_LOG_FILE, mode='a', encoding='utf-8')
    token_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    token_logger.addHandler(token_handler)

# Initialize the Anthropic client
client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))

# Get the model name from environment
MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

# Get default system prompt from environment variable
DEFAULT_SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "")

# Whether to automatically inject current date/time into each user message
INJECT_CURRENT_DATE = os.getenv("INJECT_CURRENT_DATE", "true").lower() == "true"

# Path to the MCP servers configuration file
MCP_SERVERS_CONFIG = os.path.join(os.path.dirname(__file__), "mcp_servers.json")

# Dictionary to store server name -> URL mappings
MCP_SERVERS = {}

# Dictionary to store server name -> auth headers
MCP_SERVER_HEADERS = {}


def load_mcp_servers() -> dict:
    """
    Load MCP server configurations from the JSON config file.

    Returns:
        Dictionary mapping server names to their URLs
    """
    global MCP_SERVERS

    if not os.path.exists(MCP_SERVERS_CONFIG):
        print(f"Warning: {MCP_SERVERS_CONFIG} not found")
        return {}

    try:
        with open(MCP_SERVERS_CONFIG, 'r') as f:
            config = json.load(f)

        servers = {}
        for server in config.get("servers", []):
            if server.get("enabled", True):
                name = server.get("name")
                url = server.get("url")
                auth_type = server.get("auth_type", "token")

                if not name or not url:
                    continue

                # Handle OAuth authentication
                if auth_type == "oauth":
                    oauth_config = server.get("oauth")
                    access_token = get_token_for_server(name, url, oauth_config)
                    if not access_token:
                        print(f"  - {name}: OAuth authentication failed, skipping")
                        continue

                    MCP_SERVER_HEADERS[name] = {
                        "Authorization": f"Bearer {access_token}"
                    }

                servers[name] = url

        MCP_SERVERS = servers
        return servers

    except Exception as e:
        print(f"Error loading MCP servers config: {e}")
        return {}


# =============================================================================
# MCP SERVER COMMUNICATION
# =============================================================================

def mcp_request(url: str, method: str, params: dict = None, headers: dict | None = None) -> dict: # type: ignore
    """
    Make a JSON-RPC request to an MCP server.

    Args:
        url: The MCP server URL
        method: The MCP method to call
        params: Optional parameters
        headers: Optional HTTP headers

    Returns:
        The JSON response from the server
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }

    logger.debug("=" * 80)
    logger.debug("MCP REQUEST")
    logger.debug(f"URL: {url}")
    logger.debug(f"Method: {method}")
    if headers:
        safe_headers = {k: ("Bearer ***" if k == "Authorization" else v) for k, v in headers.items()}
        logger.debug(f"Headers: {json.dumps(safe_headers, indent=2)}")
    logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    response_data = response.json()

    logger.debug("MCP RESPONSE")
    logger.debug(f"Status Code: {response.status_code}")
    logger.debug(f"Response: {json.dumps(response_data, indent=2)}")
    logger.debug("=" * 80)

    return response_data


# =============================================================================
# TOOL DISCOVERY
# =============================================================================

def discover_tools() -> list:
    """
    Discover available tools from all configured MCP servers.

    Converts MCP tool definitions to Claude's tool format.
    Tool names are prefixed with server name to avoid conflicts.

    Returns:
        A list of tools in Claude's format

    Claude Tool Format:
        {
            "name": "server__tool_name",
            "description": "What the tool does",
            "input_schema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "..."}
                },
                "required": ["param1"]
            }
        }
    """
    servers = load_mcp_servers()

    if not servers:
        return []

    claude_tools = []

    for server_name, server_url in servers.items():
        try:
            logger.info(f"Discovering tools from server: {server_name}")

            headers = MCP_SERVER_HEADERS.get(server_name)
            result = mcp_request(server_url, "tools/list", headers=headers)
            tools = result.get("result", {}).get("tools", [])

            logger.debug(f"Server {server_name} returned {len(tools)} tools")

            for tool in tools:
                schema = tool.get("inputSchema", {})

                # Ensure schema has required "type" field
                if "type" not in schema:
                    schema["type"] = "object"

                # Ensure properties exist
                if "properties" not in schema or not schema["properties"]:
                    schema["properties"] = {}

                # Prefix tool name with server name
                prefixed_name = f"{server_name}__{tool['name']}"

                logger.debug(f"  Discovered tool: {prefixed_name}")

                # Build tool definition in Claude's format
                claude_tool = {
                    "name": prefixed_name,
                    "description": tool.get("description", ""),
                    "input_schema": schema
                }
                claude_tools.append(claude_tool)

            print(f"  - {server_name}: {len(tools)} tools")
            logger.info(f"Successfully discovered {len(tools)} tools from {server_name}")

        except Exception as e:
            print(f"  - {server_name}: Failed to discover tools: {e}")
            logger.error(f"Failed to discover tools from {server_name}: {e}", exc_info=True)

    return claude_tools


# =============================================================================
# TOOL EXECUTION
# =============================================================================

def call_tool(name: str, arguments: dict) -> str:
    """
    Call a tool on the appropriate MCP server and return its result.

    Args:
        name: The prefixed tool name (e.g., "dexcom__Get_Glucose_Values_v1")
        arguments: Dictionary of arguments to pass to the tool

    Returns:
        The tool's result as a string
    """
    try:
        if "__" not in name:
            return f"Error: Invalid tool name format '{name}'. Expected 'server__tool_name'."

        server_name, tool_name = name.split("__", 1)

        if server_name not in MCP_SERVERS:
            return f"Error: Unknown server '{server_name}'. Available servers: {list(MCP_SERVERS.keys())}"

        server_url = MCP_SERVERS[server_name]
        headers = MCP_SERVER_HEADERS.get(server_name)

        result = mcp_request(server_url, "tools/call", {"name": tool_name, "arguments": arguments}, headers=headers)

        content = result.get("result", {}).get("content", [])

        if content and len(content) > 0:
            return content[0].get("text", str(result))

        return str(result.get("result", result))

    except Exception as e:
        return f"Error calling tool: {e}"


# =============================================================================
# MAIN CHAT LOOP
# =============================================================================

def chat(system_prompt: str = ""):
    """
    Main chatbot loop with MCP tool integration using Claude.

    The Tool Calling Flow:
    1. User asks a question
    2. We send it to Claude along with available tools
    3. Claude might respond with text OR request to use tools
    4. If it requests tools, we call them and send results back to Claude
    5. Claude processes the tool results and gives a final answer
    6. We display the answer to the user

    Args:
        system_prompt: Optional system prompt to guide Claude's behavior
    """
    # Keep track of conversation history
    messages = []

    # Discover available MCP tools at startup
    print("Claude MCP Chat - Discovering tools...")
    tools = discover_tools()

    # Display startup message
    if MCP_SERVERS and tools:
        print(f"\nConnected to {len(MCP_SERVERS)} server(s) with {len(tools)} total tools")
    else:
        print("\nSimple Claude Chatbot")
        if not MCP_SERVERS:
            print("(No MCP servers configured in mcp_servers.json)")
        else:
            print("(No tools discovered from MCP servers)")

    if system_prompt:
        print(f"\nSystem prompt: {system_prompt}")
    print("Type 'quit' or 'exit' to end")
    print("-" * 40)

    # Main conversation loop
    while True:
        user_input = input("\nYou: ").strip()

        if not user_input:
            continue

        if user_input.lower() in ['quit', 'exit']:
            print("Goodbye!")
            break

        # Optionally add current date/time context to user message
        if INJECT_CURRENT_DATE:
            current_datetime = datetime.now()
            current_date_str = current_datetime.strftime("%Y-%m-%d")
            current_time_str = current_datetime.strftime("%H:%M:%S")
            current_datetime_formatted = current_datetime.strftime("%Y-%m-%dT%H:%M:%S")

            user_message_with_context = f"[Current date and time: {current_date_str} {current_time_str} (formatted for API: {current_datetime_formatted})]\n\n{user_input}"
        else:
            user_message_with_context = user_input

        # Add user message to conversation history
        messages.append({"role": "user", "content": user_message_with_context})

        try:
            # Build the request to Claude
            kwargs = {
                "model": MODEL,
                "max_tokens": 4096,
                "messages": messages
            }

            # Add system prompt if provided
            if system_prompt:
                kwargs["system"] = system_prompt

            # Include tools if we have any
            if tools:
                kwargs["tools"] = tools

            # Log the Claude request
            logger.debug("=" * 80)
            logger.debug("CLAUDE REQUEST")
            logger.debug(f"Model: {MODEL}")
            logger.debug(f"Messages: {json.dumps(messages, indent=2)}")
            if tools:
                logger.debug(f"Tools: {len(tools)} tools available")
                logger.debug(f"Tool Names: {[t['name'] for t in tools]}")

            # Send to Claude and get response
            response = client.messages.create(**kwargs)

            # Log the Claude response
            logger.debug("CLAUDE RESPONSE")
            logger.debug(f"Stop Reason: {response.stop_reason}")
            # Safely log content blocks
            safe_content = []
            for c in response.content:
                if hasattr(c, 'text'):
                    safe_content.append({'type': c.type, 'text': c.text[:200] + '...' if len(c.text) > 200 else c.text})
                elif hasattr(c, 'name'):
                    safe_content.append({'type': c.type, 'name': c.name})
                else:
                    safe_content.append({'type': c.type})
            logger.debug(f"Content: {json.dumps(safe_content, indent=2)}")
            logger.debug(f"Usage: input_tokens={response.usage.input_tokens}, "
                        f"output_tokens={response.usage.output_tokens}")
            logger.debug("=" * 80)

            # Log token usage to separate token log file
            if token_logger:
                user_prompt = user_input[:100] + "..." if len(user_input) > 100 else user_input
                user_prompt = user_prompt.replace("\n", " ").replace("|", "¦")

                # Check if tools were called
                tools_used = "none"
                servers_used = "none"
                tool_use_blocks = [c for c in response.content if c.type == "tool_use"]
                if tool_use_blocks:
                    tools_used = ", ".join([t.name for t in tool_use_blocks])
                    server_names = set()
                    for t in tool_use_blocks:
                        if "__" in t.name:
                            server_name = t.name.split("__")[0]
                            server_names.add(server_name)
                    servers_used = ", ".join(sorted(server_names)) if server_names else "none"

                # Extract assistant response
                text_blocks = [c.text for c in response.content if c.type == "text"]
                response_text = " ".join(text_blocks) if text_blocks else "[Tool calls only]"
                response_text = response_text[:200] + "..." if len(response_text) > 200 else response_text
                response_text = response_text.replace("\n", " ").replace("|", "¦")

                token_logger.info(f"MODEL={MODEL} | INPUT={response.usage.input_tokens} | "
                                f"OUTPUT={response.usage.output_tokens} | "
                                f"TOTAL={response.usage.input_tokens + response.usage.output_tokens} | "
                                f"TYPE=initial_request | USER_PROMPT={user_prompt} | "
                                f"SERVERS={servers_used} | TOOLS={tools_used} | "
                                f"RESPONSE={response_text}")

            # Handle tool calls
            while response.stop_reason == "tool_use":
                # Add Claude's response to history (includes text and tool_use blocks)
                # Convert content blocks to serializable format
                serializable_content = []
                for block in response.content:
                    if block.type == "text":
                        serializable_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        serializable_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input
                        })
                messages.append({"role": "assistant", "content": serializable_content})

                # Process each tool use
                tool_results = []
                for content_block in response.content:
                    if content_block.type == "tool_use":
                        name = content_block.name
                        args = content_block.input

                        print(f"\n[Calling {name}...]")

                        logger.info(f"Tool Call: {name}")
                        logger.debug(f"Tool Arguments: {json.dumps(args, indent=2)}")

                        # Call the tool on the MCP server
                        result = call_tool(name, args)

                        logger.debug(f"Tool Result: {result[:500]}..." if len(result) > 500 else f"Tool Result: {result}")

                        # Add tool result
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": content_block.id,
                            "content": result
                        })

                # Add tool results to conversation history
                messages.append({"role": "user", "content": tool_results})

                # Log the follow-up request
                logger.debug("=" * 80)
                logger.debug("CLAUDE FOLLOW-UP REQUEST (with tool results)")
                logger.debug(f"Model: {MODEL}")
                logger.debug(f"Number of messages in history: {len(messages)}")

                # Get Claude's next response
                response = client.messages.create(**kwargs)

                # Log the follow-up response
                logger.debug("CLAUDE FOLLOW-UP RESPONSE")
                logger.debug(f"Stop Reason: {response.stop_reason}")
                # Safely log content blocks
                safe_content = []
                for c in response.content:
                    if hasattr(c, 'text'):
                        safe_content.append({'type': c.type, 'text': c.text[:200] + '...' if len(c.text) > 200 else c.text})
                    elif hasattr(c, 'name'):
                        safe_content.append({'type': c.type, 'name': c.name})
                    else:
                        safe_content.append({'type': c.type})
                logger.debug(f"Content: {json.dumps(safe_content, indent=2)}")
                logger.debug(f"Usage: input_tokens={response.usage.input_tokens}, "
                            f"output_tokens={response.usage.output_tokens}")
                logger.debug("=" * 80)

                # Log token usage
                if token_logger:
                    user_prompt = user_input[:100] + "..." if len(user_input) > 100 else user_input
                    user_prompt = user_prompt.replace("\n", " ").replace("|", "¦")

                    tools_used = "none"
                    servers_used = "none"
                    tool_use_blocks = [c for c in response.content if c.type == "tool_use"]
                    if tool_use_blocks:
                        tools_used = ", ".join([t.name for t in tool_use_blocks])
                        server_names = set()
                        for t in tool_use_blocks:
                            if "__" in t.name:
                                server_name = t.name.split("__")[0]
                                server_names.add(server_name)
                        servers_used = ", ".join(sorted(server_names)) if server_names else "none"

                    text_blocks = [c.text for c in response.content if c.type == "text"]
                    response_text = " ".join(text_blocks) if text_blocks else "[Tool calls only]"
                    response_text = response_text[:200] + "..." if len(response_text) > 200 else response_text
                    response_text = response_text.replace("\n", " ").replace("|", "¦")

                    token_logger.info(f"MODEL={MODEL} | INPUT={response.usage.input_tokens} | "
                                    f"OUTPUT={response.usage.output_tokens} | "
                                    f"TOTAL={response.usage.input_tokens + response.usage.output_tokens} | "
                                    f"TYPE=tool_followup | USER_PROMPT={user_prompt} | "
                                    f"SERVERS={servers_used} | TOOLS={tools_used} | "
                                    f"RESPONSE={response_text}")

            # Extract and display final text response
            text_blocks = [c.text for c in response.content if c.type == "text"]
            final_text = "\n".join(text_blocks)

            # Add final response to history
            # Convert content blocks to serializable format
            serializable_content = []
            for block in response.content:
                if block.type == "text":
                    serializable_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    serializable_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })
            messages.append({"role": "assistant", "content": serializable_content})

            print(f"\nAssistant: {final_text}")

        except Exception as e:
            print(f"\nError: {e}")
            # Remove the failed user message from history
            if messages and messages[-1]["role"] == "user":
                messages.pop()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Claude MCP Chat - Chat with Claude using MCP tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python chat-claude.py
  python chat-claude.py --system-prompt "You are a helpful medical assistant."
  python chat-claude.py -s "You are a concise assistant that answers in bullet points."

Environment Variables:
  CLAUDE_API_KEY         Your Anthropic API key (required)
  CLAUDE_MODEL          Claude model to use (default: claude-3-5-sonnet-20241022)
  SYSTEM_PROMPT         Default system prompt (overridden by --system-prompt)
        """
    )
    parser.add_argument(
        "-s", "--system-prompt",
        type=str,
        default=DEFAULT_SYSTEM_PROMPT,
        help="System prompt to guide Claude's behavior (overrides SYSTEM_PROMPT env var)"
    )

    args = parser.parse_args()

    # Run the chat with the specified system prompt
    chat(system_prompt=args.system_prompt)

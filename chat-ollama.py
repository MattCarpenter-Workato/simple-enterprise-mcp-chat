"""
Simple MCP Chat - Ollama Integration

This script demonstrates how to connect a Python chatbot to Workato's Enterprise
MCP (Model Context Protocol) servers using Ollama (local LLM runtime).

What this script does:
1. Loads MCP server configurations from mcp_servers.json
2. Connects to multiple Workato MCP servers simultaneously
3. Discovers what tools are available from each server
4. Lets you chat with Ollama models that can use those tools to answer your questions

Key Features:
- Uses Ollama for local LLM inference (privacy-focused, no cloud API needed)
- Compatible with any Ollama model (llama3, mistral, neural-chat, etc.)
- Function calling support (if the model supports it)
- Same MCP tool integration as OpenAI/Claude versions
- Automatic model preloading on startup to eliminate first-request delays

Usage:
- python chat-ollama.py
- python chat-ollama.py --system-prompt "You are a helpful medical assistant."
- python chat-ollama.py -s "You are a concise assistant."

Configuration:
- OLLAMA_BASE_URL: Ollama server URL (default: http://localhost:11434)
- OLLAMA_MODEL: Model to use (default: llama3.2)
- SYSTEM_PROMPT: Optional default system prompt for guiding model's behavior

Requirements:
- Ollama must be running locally (https://ollama.ai)
- Model must be pulled: `ollama pull llama3.2`
- For tool calling, use models that support function calling (llama3.2, mistral, etc.)

"""

import os
import json
import requests
import argparse
import logging
from datetime import datetime
from dotenv import load_dotenv
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

# Ollama configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

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

    Converts MCP tool definitions to OpenAI-compatible function format
    (which Ollama uses for function calling).
    Tool names are prefixed with server name to avoid conflicts.

    Returns:
        A list of tools in OpenAI function calling format

    OpenAI/Ollama Tool Format:
        {
            "type": "function",
            "function": {
                "name": "server__tool_name",
                "description": "What the tool does",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string", "description": "..."}
                    },
                    "required": ["param1"]
                }
            }
        }
    """
    servers = load_mcp_servers()

    if not servers:
        return []

    ollama_tools = []

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

                # Build tool definition in OpenAI/Ollama format
                ollama_tool = {
                    "type": "function",
                    "function": {
                        "name": prefixed_name,
                        "description": tool.get("description", ""),
                        "parameters": schema
                    }
                }
                ollama_tools.append(ollama_tool)

            print(f"  - {server_name}: {len(tools)} tools")
            logger.info(f"Successfully discovered {len(tools)} tools from {server_name}")

        except Exception as e:
            print(f"  - {server_name}: Failed to discover tools: {e}")
            logger.error(f"Failed to discover tools from {server_name}: {e}", exc_info=True)

    return ollama_tools


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
# OLLAMA API CLIENT
# =============================================================================

def check_model_exists(model: str = OLLAMA_MODEL) -> bool:
    """
    Check if a model exists locally in Ollama.

    Args:
        model: Model name to check

    Returns:
        True if model exists, False otherwise
    """
    base_url = OLLAMA_BASE_URL.rstrip('/')
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]
    url = f"{base_url}/api/tags"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Check if the model exists in the list of models
        models = data.get("models", [])
        for m in models:
            model_name = m.get("name", "")
            # Handle model names with and without tags (e.g., "llama3.2" or "llama3.2:latest")
            if model_name == model or model_name.startswith(f"{model}:"):
                return True

        return False

    except Exception as e:
        logger.error(f"Error checking if model exists: {e}", exc_info=True)
        return False


def pull_model(model: str = OLLAMA_MODEL) -> bool:
    """
    Pull a model from Ollama registry with progress updates.

    Args:
        model: Model name to pull

    Returns:
        True if pull successful, False otherwise
    """
    base_url = OLLAMA_BASE_URL.rstrip('/')
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]
    url = f"{base_url}/api/pull"

    payload = {
        "name": model,
        "stream": True
    }

    try:
        print(f"Pulling model '{model}' from Ollama registry...")
        logger.info(f"Starting pull for model: {model}")

        response = requests.post(url, json=payload, stream=True, timeout=600)  # 10 min timeout
        response.raise_for_status()

        # Track download progress
        last_status = ""
        for line in response.iter_lines():
            if line:
                try:
                    status_data = json.loads(line)
                    status = status_data.get("status", "")

                    # Show progress updates
                    if status != last_status:
                        if status:
                            print(f"  {status}", flush=True)
                        last_status = status

                    # Check for completion
                    if status == "success" or "success" in status.lower():
                        print(f"Successfully pulled model '{model}' ✓")
                        logger.info(f"Successfully pulled model: {model}")
                        return True

                except json.JSONDecodeError:
                    continue

        print(f"Model '{model}' pull completed ✓")
        logger.info(f"Model pull completed: {model}")
        return True

    except requests.exceptions.ConnectionError:
        print(f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. Is Ollama running?")
        logger.error(f"Connection error while pulling model {model}")
        return False

    except requests.exceptions.Timeout:
        print(f"Timeout while pulling model '{model}'.")
        logger.error(f"Timeout while pulling model {model}")
        return False

    except Exception as e:
        print(f"Error pulling model: {e}")
        logger.error(f"Unexpected error while pulling model {model}: {e}", exc_info=True)
        return False


def preload_model(model: str = OLLAMA_MODEL) -> bool:
    """
    Preload an Ollama model into memory to avoid delays on first request.
    If the model doesn't exist locally, it will be pulled first.

    Uses the /api/generate endpoint with an empty request to warm up the model.
    Sets keep_alive=-1 to keep the model loaded in memory indefinitely.

    Args:
        model: Model name to preload

    Returns:
        True if preload successful, False otherwise
    """
    # Check if model exists locally
    print(f"Checking if model '{model}' exists...", end="", flush=True)
    model_exists = check_model_exists(model)

    if not model_exists:
        print(" not found")
        # Try to pull the model
        if not pull_model(model):
            print(f"\nFailed to pull model '{model}'. Please run: ollama pull {model}")
            return False
    else:
        print(" ✓")

    base_url = OLLAMA_BASE_URL.rstrip('/')
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]
    url = f"{base_url}/api/generate"

    payload = {
        "model": model,
        "keep_alive": -1  # Keep model loaded indefinitely
    }

    try:
        print(f"Loading model '{model}' into memory...", end="", flush=True)
        response = requests.post(url, json=payload, timeout=300)  # 5 min timeout for large models
        response.raise_for_status()
        print(" ✓")
        logger.info(f"Successfully preloaded model: {model}")
        return True

    except requests.exceptions.ConnectionError:
        print(" ✗")
        print(f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. Is Ollama running?")
        logger.error(f"Connection error while preloading model {model}")
        return False

    except requests.exceptions.Timeout:
        print(" ✗")
        print(f"Timeout while loading model. The model '{model}' might need to be pulled first.")
        print(f"Try: ollama pull {model}")
        logger.error(f"Timeout while preloading model {model}")
        return False

    except requests.exceptions.HTTPError as e:
        print(" ✗")
        if e.response.status_code == 404:
            print(f"Model '{model}' not found. Pull it first with: ollama pull {model}")
        else:
            print(f"HTTP error: {e}")
        logger.error(f"HTTP error while preloading model {model}: {e}")
        return False

    except Exception as e:
        print(" ✗")
        print(f"Error preloading model: {e}")
        logger.error(f"Unexpected error while preloading model {model}: {e}", exc_info=True)
        return False


def ollama_chat(messages: list, tools: list = None, model: str = OLLAMA_MODEL) -> dict:
    """
    Send a chat request to Ollama API.

    Args:
        messages: List of message dictionaries
        tools: Optional list of tools in OpenAI format
        model: Model name to use

    Returns:
        Response dictionary from Ollama
    """
    # Ensure base URL doesn't end with /v1 to avoid double /v1/v1
    base_url = OLLAMA_BASE_URL.rstrip('/')
    if base_url.endswith('/v1'):
        base_url = base_url[:-3]
    url = f"{base_url}/v1/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }

    # Add tools if provided and model supports function calling
    if tools:
        payload["tools"] = tools

    logger.debug("=" * 80)
    logger.debug("OLLAMA REQUEST")
    logger.debug(f"URL: {url}")
    logger.debug(f"Model: {model}")
    logger.debug(f"Messages: {json.dumps(messages, indent=2)}")
    if tools:
        logger.debug(f"Tools: {len(tools)} tools available")
        logger.debug(f"Tool Names: {[t['function']['name'] for t in tools]}")

    try:
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        response_data = response.json()

        logger.debug("OLLAMA RESPONSE")
        logger.debug(f"Response: {json.dumps(response_data, indent=2)}")
        logger.debug("=" * 80)

        return response_data

    except requests.exceptions.ConnectionError:
        raise Exception(f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. Is Ollama running?")
    except requests.exceptions.Timeout:
        raise Exception("Ollama request timed out. The model might be too large or slow.")
    except Exception as e:
        logger.error(f"Ollama API error: {e}", exc_info=True)
        raise


# =============================================================================
# MAIN CHAT LOOP
# =============================================================================

def chat(system_prompt: str = ""):
    """
    Main chatbot loop with MCP tool integration using Ollama.

    The Tool Calling Flow:
    1. User asks a question
    2. We send it to Ollama along with available tools
    3. Ollama might respond with text OR request to use tools
    4. If it requests tools, we call them and send results back to Ollama
    5. Ollama processes the tool results and gives a final answer
    6. We display the answer to the user

    Args:
        system_prompt: Optional system prompt to guide model's behavior
    """
    # Keep track of conversation history
    messages = []

    # Add system prompt if provided
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Preload model into memory
    print("Ollama MCP Chat")
    print("-" * 40)
    model_loaded = preload_model(OLLAMA_MODEL)

    if not model_loaded:
        print("\nWarning: Model could not be preloaded. First request may be slow.")
        print("The chat will continue, but you may experience delays.")
        print()

    # Discover available MCP tools at startup
    print("Discovering tools...")
    tools = discover_tools()

    # Display startup message
    if MCP_SERVERS and tools:
        print(f"\nConnected to {len(MCP_SERVERS)} server(s) with {len(tools)} total tools")
    else:
        print("\nSimple Ollama Chatbot")
        if not MCP_SERVERS:
            print("(No MCP servers configured in mcp_servers.json)")
        else:
            print("(No tools discovered from MCP servers)")

    print(f"Using model: {OLLAMA_MODEL}")
    if system_prompt:
        # Safely print system prompt, handling Unicode characters
        try:
            print(f"System prompt: {system_prompt}")
        except UnicodeEncodeError:
            print(f"System prompt: {system_prompt.encode('ascii', 'replace').decode('ascii')}")
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
            # Send to Ollama and get response
            response_data = ollama_chat(messages, tools=tools if tools else None)

            # Extract the response message
            response_message = response_data.get("choices", [{}])[0].get("message", {})

            # Log token usage if available
            usage = response_data.get("usage", {})
            if token_logger and usage:
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

                user_prompt = user_input[:100] + "..." if len(user_input) > 100 else user_input
                user_prompt = user_prompt.replace("\n", " ").replace("|", "¦")

                # Check if tools were called
                tools_used = "none"
                servers_used = "none"
                tool_calls = response_message.get("tool_calls", [])
                if tool_calls:
                    tools_used = ", ".join([t["function"]["name"] for t in tool_calls])
                    server_names = set()
                    for t in tool_calls:
                        func_name = t["function"]["name"]
                        if "__" in func_name:
                            server_name = func_name.split("__")[0]
                            server_names.add(server_name)
                    servers_used = ", ".join(sorted(server_names)) if server_names else "none"

                response_text = response_message.get("content", "[Tool calls only]") or "[Tool calls only]"
                response_text = response_text[:200] + "..." if len(response_text) > 200 else response_text
                response_text = response_text.replace("\n", " ").replace("|", "¦")

                token_logger.info(f"MODEL={OLLAMA_MODEL} | INPUT={input_tokens} | "
                                f"OUTPUT={output_tokens} | TOTAL={total_tokens} | "
                                f"TYPE=initial_request | USER_PROMPT={user_prompt} | "
                                f"SERVERS={servers_used} | TOOLS={tools_used} | "
                                f"RESPONSE={response_text}")

            # Handle tool calls
            tool_calls = response_message.get("tool_calls")
            while tool_calls:
                # Add assistant's response to history
                messages.append(response_message)

                # Process each tool call
                for tool_call in tool_calls:
                    function_name = tool_call["function"]["name"]
                    function_args = json.loads(tool_call["function"]["arguments"])

                    print(f"\n[Calling {function_name}...]")

                    logger.info(f"Tool Call: {function_name}")
                    logger.debug(f"Tool Arguments: {json.dumps(function_args, indent=2)}")

                    # Call the tool on the MCP server
                    result = call_tool(function_name, function_args)

                    logger.debug(f"Tool Result: {result[:500]}..." if len(result) > 500 else f"Tool Result: {result}")

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": function_name,
                        "content": result
                    })

                # Get Ollama's next response with tool results
                logger.debug("=" * 80)
                logger.debug("OLLAMA FOLLOW-UP REQUEST (with tool results)")
                logger.debug(f"Number of messages in history: {len(messages)}")

                response_data = ollama_chat(messages, tools=tools if tools else None)
                response_message = response_data.get("choices", [{}])[0].get("message", {})

                # Log token usage for follow-up
                usage = response_data.get("usage", {})
                if token_logger and usage:
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)
                    total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

                    user_prompt = user_input[:100] + "..." if len(user_input) > 100 else user_input
                    user_prompt = user_prompt.replace("\n", " ").replace("|", "¦")

                    tools_used = "none"
                    servers_used = "none"
                    next_tool_calls = response_message.get("tool_calls", [])
                    if next_tool_calls:
                        tools_used = ", ".join([t["function"]["name"] for t in next_tool_calls])
                        server_names = set()
                        for t in next_tool_calls:
                            func_name = t["function"]["name"]
                            if "__" in func_name:
                                server_name = func_name.split("__")[0]
                                server_names.add(server_name)
                        servers_used = ", ".join(sorted(server_names)) if server_names else "none"

                    response_text = response_message.get("content", "[Tool calls only]") or "[Tool calls only]"
                    response_text = response_text[:200] + "..." if len(response_text) > 200 else response_text
                    response_text = response_text.replace("\n", " ").replace("|", "¦")

                    token_logger.info(f"MODEL={OLLAMA_MODEL} | INPUT={input_tokens} | "
                                    f"OUTPUT={output_tokens} | TOTAL={total_tokens} | "
                                    f"TYPE=tool_followup | USER_PROMPT={user_prompt} | "
                                    f"SERVERS={servers_used} | TOOLS={tools_used} | "
                                    f"RESPONSE={response_text}")

                # Check for more tool calls
                tool_calls = response_message.get("tool_calls")

            # Extract and display final text response
            final_text = response_message.get("content", "")

            # Add final response to history
            messages.append(response_message)

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
        description="Ollama MCP Chat - Chat with Ollama using MCP tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python chat-ollama.py
  python chat-ollama.py --system-prompt "You are a helpful medical assistant."
  python chat-ollama.py -s "You are a concise assistant that answers in bullet points."

Environment Variables:
  OLLAMA_BASE_URL       Ollama server URL (default: http://localhost:11434)
  OLLAMA_MODEL         Model to use (default: llama3.2)
  SYSTEM_PROMPT         Default system prompt (overridden by --system-prompt)

Requirements:
  - Ollama must be running: https://ollama.ai
  - Pull a model first: ollama pull llama3.2
  - For function calling, use compatible models (llama3.2, mistral, etc.)
        """
    )
    parser.add_argument(
        "-s", "--system-prompt",
        type=str,
        default=DEFAULT_SYSTEM_PROMPT,
        help="System prompt to guide model's behavior (overrides SYSTEM_PROMPT env var)"
    )

    args = parser.parse_args()

    # Run the chat with the specified system prompt
    chat(system_prompt=args.system_prompt)

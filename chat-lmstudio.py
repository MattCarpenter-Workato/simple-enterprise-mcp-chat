"""
Simple MCP Chat for LM Studio - Local LLM with MCP Tool Integration

This script demonstrates how to connect a Python chatbot to Workato's Enterprise
MCP (Model Context Protocol) servers using a local LLM running in LM Studio.

LM Studio provides an OpenAI-compatible API server, so this script uses the same
OpenAI client library but points to your local LM Studio server instead.

What this script does:
1. Loads MCP server configurations from mcp_servers.json
2. Connects to multiple Workato MCP servers simultaneously
3. Discovers what tools are available from each server
4. Lets you chat with a LOCAL AI that can use those tools to answer your questions

Requirements:
- LM Studio running with a model loaded and server started
- Default LM Studio server runs at http://localhost:1234/v1
- Make sure to load a model that supports function calling for best results

Configuration:
- LMSTUDIO_BASE_URL: The base URL for your LM Studio server (default: http://localhost:1234/v1)
- LMSTUDIO_MODEL: The model to use (default: "local-model" - LM Studio ignores this)

Note: LM Studio uses whatever model you have loaded, so the model parameter is
typically ignored. However, some setups may use it for routing.

"""

import os
import json
import requests
from dotenv import load_dotenv
from openai import OpenAI
from oauth_handler import get_token_for_server

# =============================================================================
# CONFIGURATION
# =============================================================================

# Load environment variables from .env file
# This keeps sensitive data like API keys out of your code
load_dotenv()

# Initialize the OpenAI client pointing to LM Studio's local server
# LM Studio provides an OpenAI-compatible API at http://localhost:1234/v1
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")

client = OpenAI(
    base_url=LMSTUDIO_BASE_URL,
    api_key="lm-studio"  # LM Studio doesn't require an API key, but the client needs something
)

# Get the model name from environment, with a default fallback
# Note: LM Studio typically uses whatever model is loaded, this is often ignored
MODEL = os.getenv("LMSTUDIO_MODEL", "local-model")

# Path to the MCP servers configuration file
MCP_SERVERS_CONFIG = os.path.join(os.path.dirname(__file__), "mcp_servers.json")

# Dictionary to store server name -> URL mappings
# This is populated by load_mcp_servers()
MCP_SERVERS = {}

# Dictionary to store server name -> auth headers
# This is populated by load_mcp_servers() for OAuth servers
MCP_SERVER_HEADERS = {}


def load_mcp_servers() -> dict:
    """
    Load MCP server configurations from the JSON config file.

    The config file (mcp_servers.json) should have this format:
    {
        "servers": [
            {
                "name": "server_name",
                "url": "https://...",
                "enabled": true,
                "auth_type": "token"  // or "oauth"
            }
        ]
    }

    For OAuth-enabled servers, the config should include:
    {
        "name": "server_name",
        "url": "https://...",
        "enabled": true,
        "auth_type": "oauth",
        "oauth": {
            "auth_url": "https://...",
            "token_url": "https://...",
            "client_id": "...",
            "client_secret": "...",
            "scopes": ["scope1", "scope2"],
            "redirect_port": 8080
        }
    }

    Returns:
        Dictionary mapping server names to their URLs (with auth tokens applied)
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
                    # Get optional OAuth configuration
                    oauth_config = server.get("oauth")

                    # Get OAuth token (will prompt user to authenticate in browser if needed)
                    # OAuth endpoints will be auto-discovered from the server URL if not provided
                    access_token = get_token_for_server(name, url, oauth_config)
                    if not access_token:
                        print(f"  - {name}: OAuth authentication failed, skipping")
                        continue

                    # Store Authorization header for OAuth servers
                    MCP_SERVER_HEADERS[name] = {
                        "Authorization": f"Bearer {access_token}"
                    }

                # Add to servers dict
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

    MCP uses JSON-RPC 2.0 protocol, which is a simple way to call remote functions.
    Each request has:
    - jsonrpc: Always "2.0" (the protocol version)
    - id: A unique identifier for matching requests to responses
    - method: The function you want to call (e.g., "tools/list", "tools/call")
    - params: Any parameters the function needs

    Args:
        url: The MCP server URL to send the request to
        method: The MCP method to call (e.g., "tools/list" or "tools/call")
        params: Optional dictionary of parameters for the method
        headers: Optional dictionary of HTTP headers to include

    Returns:
        The JSON response from the server

    Example:
        # List all available tools
        result = mcp_request(server_url, "tools/list")

        # Call a specific tool
        result = mcp_request(server_url, "tools/call", {
            "name": "Get_Glucose_Values_v1",
            "arguments": {"start_date": "2024-01-01", "end_date": "2024-01-07"}
        })
    """
    # Build the JSON-RPC request payload
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }

    # Send the request to the MCP server
    # timeout=30 means we'll wait up to 30 seconds for a response
    response = requests.post(url, json=payload, headers=headers, timeout=30)

    # Raise an error if the request failed (e.g., 404, 500 errors)
    response.raise_for_status()

    # Parse and return the JSON response
    return response.json()


# =============================================================================
# TOOL DISCOVERY
# =============================================================================

def discover_tools() -> list:
    """
    Discover available tools from all configured MCP servers.

    This function:
    1. Loads server configurations from mcp_servers.json
    2. Calls each server's "tools/list" endpoint
    3. Prefixes tool names with server name to avoid conflicts
    4. Converts them to the format OpenAI expects for function calling

    The conversion is necessary because MCP and OpenAI use slightly different
    formats for describing tools/functions.

    Tool names are prefixed with the server name using double underscore:
    e.g., "Get_Glucose_Values_v1" becomes "dexcom__Get_Glucose_Values_v1"

    Returns:
        A list of tools in OpenAI's function calling format

    OpenAI Function Format:
        {
            "type": "function",
            "function": {
                "name": "server__tool_name",
                "description": "What the tool does",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string", "description": "..."}
                    }
                }
            }
        }
    """
    # Load MCP servers from config
    servers = load_mcp_servers()

    # If no servers are configured, return empty list
    if not servers:
        return []

    openai_tools = []

    # Discover tools from each server
    for server_name, server_url in servers.items():
        try:
            # Get auth headers if available
            headers = MCP_SERVER_HEADERS.get(server_name)

            # Ask the MCP server what tools are available
            result = mcp_request(server_url, "tools/list", headers=headers)

            # Extract the tools array from the response
            tools = result.get("result", {}).get("tools", [])

            # Convert MCP tools to OpenAI function format
            for tool in tools:
                # Get the input schema (describes what parameters the tool accepts)
                # Some tools might not have a schema, so we provide defaults
                schema = tool.get("inputSchema", {})

                # Ensure the schema has the required "type" field
                if "type" not in schema:
                    schema["type"] = "object"

                # OpenAI requires a "properties" field, even if empty
                # This handles tools that don't take any parameters
                if "properties" not in schema or not schema["properties"]:
                    schema["properties"] = {}

                # Prefix tool name with server name to avoid conflicts
                # e.g., "Get_Glucose_Values_v1" -> "dexcom__Get_Glucose_Values_v1"
                prefixed_name = f"{server_name}__{tool['name']}"

                # Build the tool definition in OpenAI's format
                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": prefixed_name,
                        "description": tool.get("description", ""),
                        "parameters": schema
                    }
                }
                openai_tools.append(openai_tool)

            print(f"  - {server_name}: {len(tools)} tools")

        except Exception as e:
            # If a server fails, print error but continue with others
            print(f"  - {server_name}: Failed to discover tools: {e}")

    return openai_tools


# =============================================================================
# TOOL EXECUTION
# =============================================================================

def call_tool(name: str, arguments: dict) -> str:
    """
    Call a tool on the appropriate MCP server and return its result.

    When the LLM decides it needs to use a tool, it tells us:
    - Which tool to call (name, prefixed with server name)
    - What parameters to pass (arguments)

    We parse the server name from the tool prefix, route the request to the
    correct MCP server, and return the result.

    Args:
        name: The prefixed tool name (e.g., "dexcom__Get_Glucose_Values_v1")
        arguments: Dictionary of arguments to pass to the tool

    Returns:
        The tool's result as a string (for the LLM to process)

    Example:
        result = call_tool("dexcom__Get_Data_Range_v1", {})
        result = call_tool("dexcom__Get_Glucose_Values_v1", {
            "start_date_time": "2024-01-01T00:00:00",
            "end_date_time": "2024-01-07T23:59:59"
        })
    """
    try:
        # Parse server name and original tool name from prefixed name
        # e.g., "dexcom__Get_Glucose_Values_v1" -> ("dexcom", "Get_Glucose_Values_v1")
        if "__" not in name:
            return f"Error: Invalid tool name format '{name}'. Expected 'server__tool_name'."

        server_name, tool_name = name.split("__", 1)

        # Look up the server URL
        if server_name not in MCP_SERVERS:
            return f"Error: Unknown server '{server_name}'. Available servers: {list(MCP_SERVERS.keys())}"

        server_url = MCP_SERVERS[server_name]

        # Get auth headers if available
        headers = MCP_SERVER_HEADERS.get(server_name)

        # Make the MCP request to call the tool (using original tool name)
        result = mcp_request(server_url, "tools/call", {"name": tool_name, "arguments": arguments}, headers=headers)

        # Extract the content from the MCP response
        # MCP returns results in a specific format with "content" array
        content = result.get("result", {}).get("content", [])

        # Get the text content from the first content item
        if content and len(content) > 0:
            return content[0].get("text", str(result))

        # Fallback: return the raw result as a string
        return str(result.get("result", result))

    except Exception as e:
        # Return error message so the LLM can inform the user
        return f"Error calling tool: {e}"


# =============================================================================
# MAIN CHAT LOOP
# =============================================================================

def chat():
    """
    Main chatbot loop with MCP tool integration using LM Studio.

    This function:
    1. Discovers available tools from the MCP server
    2. Runs an interactive chat loop
    3. Sends user messages to LM Studio
    4. Handles tool calls when the LLM needs external data
    5. Returns the final response to the user

    The Tool Calling Flow:
    1. User asks a question
    2. We send it to LM Studio along with available tools
    3. LM Studio might respond with text OR request to use a tool
    4. If it requests a tool, we call it and send results back to LM Studio
    5. LM Studio processes the tool results and gives a final answer
    6. We display the answer to the user

    Note: Not all models in LM Studio support function calling. For best results,
    use a model that explicitly supports tool/function calling (e.g., models with
    "function calling" or "tool use" in their description).
    """
    # Keep track of conversation history
    # This helps the AI remember previous messages
    messages = []

    # Discover available MCP tools at startup
    print("LM Studio MCP Chat - Discovering tools...")
    tools = discover_tools()

    # Display startup message
    print(f"\nConnected to LM Studio at {LMSTUDIO_BASE_URL}")
    if MCP_SERVERS and tools:
        print(f"Connected to {len(MCP_SERVERS)} MCP server(s) with {len(tools)} total tools")
    else:
        print("Simple LM Studio Chatbot")
        if not MCP_SERVERS:
            print("(No MCP servers configured in mcp_servers.json)")
        else:
            print("(No tools discovered from MCP servers)")

    print("\nNote: Make sure you have a model loaded in LM Studio!")
    print("For best results, use a model that supports function calling.")
    print("Type 'quit' or 'exit' to end")
    print("-" * 40)

    # Main conversation loop
    while True:
        # Get user input
        user_input = input("\nYou: ").strip()

        # Skip empty input
        if not user_input:
            continue

        # Check for exit commands
        if user_input.lower() in ['quit', 'exit']:
            print("Goodbye!")
            break

        # Add user message to conversation history
        messages.append({"role": "user", "content": user_input})

        try:
            # Build the request to LM Studio
            kwargs = {
                "model": MODEL,
                "messages": messages
            }

            # Include tools if we have any
            if tools:
                kwargs["tools"] = tools

            # Send to LM Studio and get response
            response = client.chat.completions.create(**kwargs)
            assistant_message = response.choices[0].message

            # Handle tool calls
            # LM Studio might request one or more tools to be called
            # We keep looping until it gives us a final text response
            while assistant_message.tool_calls:
                # Add the assistant's tool request to history
                messages.append(assistant_message)

                # Process each tool call
                for tool_call in assistant_message.tool_calls:
                    # Extract tool name and arguments
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)

                    # Show the user what tool is being called
                    print(f"\n[Calling {name}...]")

                    # Call the tool on the MCP server
                    result = call_tool(name, args)

                    # Add tool result to conversation history
                    # LM Studio needs this to generate its response
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

                # Get LM Studio's next response (might be another tool call or final answer)
                response = client.chat.completions.create(**kwargs)
                assistant_message = response.choices[0].message

            # Add final response to history and display to user
            messages.append({"role": "assistant", "content": assistant_message.content})
            print(f"\nAssistant: {assistant_message.content}")

        except Exception as e:
            # Handle errors gracefully
            error_msg = str(e)
            if "Connection refused" in error_msg or "connect" in error_msg.lower():
                print(f"\nError: Could not connect to LM Studio at {LMSTUDIO_BASE_URL}")
                print("Make sure LM Studio is running and the server is started.")
            else:
                print(f"\nError: {e}")
            # Remove the failed user message from history
            messages.pop()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Run the chat when script is executed directly
    chat()

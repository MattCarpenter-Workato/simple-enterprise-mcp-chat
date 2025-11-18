"""
Simple MCP Chat - A Beginner's Guide to Enterprise MCP with Python

This script demonstrates how to connect a Python chatbot to Workato's Enterprise
MCP (Model Context Protocol) servers. It's designed to be the simplest possible
example of using MCP tools with OpenAI's function calling feature.

What this script does:
1. Connects to a Workato MCP server
2. Discovers what tools are available (like getting glucose data, alerts, etc.)
3. Lets you chat with an AI that can use those tools to answer your questions

Key Concepts:
- MCP (Model Context Protocol): A standard way for AI models to use external tools
- JSON-RPC: A simple protocol for making remote procedure calls using JSON
- Function Calling: OpenAI's feature that lets the AI decide when to use tools

"""

import os
import json
import requests
from dotenv import load_dotenv
from openai import OpenAI

# =============================================================================
# CONFIGURATION
# =============================================================================

# Load environment variables from .env file
# This keeps sensitive data like API keys out of your code
load_dotenv()

# Initialize the OpenAI client
# This is what we'll use to send messages to GPT and get responses
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Get the model name from environment, with a default fallback
# You can change this to gpt-4o, gpt-3.5-turbo, etc.
MODEL = os.getenv("MODEL", "gpt-4o-mini")

# Path to the MCP servers configuration file
MCP_SERVERS_CONFIG = os.path.join(os.path.dirname(__file__), "mcp_servers.json")

# Dictionary to store server name -> URL mappings
# This is populated by load_mcp_servers()
MCP_SERVERS = {}


def load_mcp_servers() -> dict:
    """
    Load MCP server configurations from the JSON config file.

    The config file (mcp_servers.json) should have this format:
    {
        "servers": [
            {
                "name": "server_name",
                "url": "https://...",
                "enabled": true
            }
        ]
    }

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
                if name and url:
                    servers[name] = url

        MCP_SERVERS = servers
        return servers

    except Exception as e:
        print(f"Error loading MCP servers config: {e}")
        return {}


# =============================================================================
# MCP SERVER COMMUNICATION
# =============================================================================

def mcp_request(url: str, method: str, params: dict = None) -> dict: # type: ignore
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
    response = requests.post(url, json=payload, timeout=30)

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
            # Ask the MCP server what tools are available
            result = mcp_request(server_url, "tools/list")

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

    When OpenAI decides it needs to use a tool, it tells us:
    - Which tool to call (name, prefixed with server name)
    - What parameters to pass (arguments)

    We parse the server name from the tool prefix, route the request to the
    correct MCP server, and return the result.

    Args:
        name: The prefixed tool name (e.g., "dexcom__Get_Glucose_Values_v1")
        arguments: Dictionary of arguments to pass to the tool

    Returns:
        The tool's result as a string (for OpenAI to process)

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

        # Make the MCP request to call the tool (using original tool name)
        result = mcp_request(server_url, "tools/call", {"name": tool_name, "arguments": arguments})

        # Extract the content from the MCP response
        # MCP returns results in a specific format with "content" array
        content = result.get("result", {}).get("content", [])

        # Get the text content from the first content item
        if content and len(content) > 0:
            return content[0].get("text", str(result))

        # Fallback: return the raw result as a string
        return str(result.get("result", result))

    except Exception as e:
        # Return error message so OpenAI can inform the user
        return f"Error calling tool: {e}"


# =============================================================================
# MAIN CHAT LOOP
# =============================================================================

def chat():
    """
    Main chatbot loop with MCP tool integration.

    This function:
    1. Discovers available tools from the MCP server
    2. Runs an interactive chat loop
    3. Sends user messages to OpenAI
    4. Handles tool calls when OpenAI needs external data
    5. Returns the final response to the user

    The Tool Calling Flow:
    1. User asks a question
    2. We send it to OpenAI along with available tools
    3. OpenAI might respond with text OR request to use a tool
    4. If it requests a tool, we call it and send results back to OpenAI
    5. OpenAI processes the tool results and gives a final answer
    6. We display the answer to the user
    """
    # Keep track of conversation history
    # This helps the AI remember previous messages
    messages = []

    # Discover available MCP tools at startup
    print("MCP Chat - Discovering tools...")
    tools = discover_tools()

    # Display startup message
    if MCP_SERVERS and tools:
        print(f"\nConnected to {len(MCP_SERVERS)} server(s) with {len(tools)} total tools")
    else:
        print("\nSimple OpenAI Chatbot")
        if not MCP_SERVERS:
            print("(No MCP servers configured in mcp_servers.json)")
        else:
            print("(No tools discovered from MCP servers)")

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
            # Build the request to OpenAI
            kwargs = {
                "model": MODEL,
                "messages": messages
            }

            # Include tools if we have any
            if tools:
                kwargs["tools"] = tools

            # Send to OpenAI and get response
            response = client.chat.completions.create(**kwargs)
            assistant_message = response.choices[0].message

            # Handle tool calls
            # OpenAI might request one or more tools to be called
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
                    # OpenAI needs this to generate its response
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

                # Get OpenAI's next response (might be another tool call or final answer)
                response = client.chat.completions.create(**kwargs)
                assistant_message = response.choices[0].message

            # Add final response to history and display to user
            messages.append({"role": "assistant", "content": assistant_message.content})
            print(f"\nAssistant: {assistant_message.content}")

        except Exception as e:
            # Handle errors gracefully
            print(f"\nError: {e}")
            # Remove the failed user message from history
            messages.pop()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Run the chat when script is executed directly
    chat()

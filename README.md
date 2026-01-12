# Simple MCP Chat

A beginner-friendly Python chatbot that connects to Workato's Enterprise MCP servers. This is the simplest possible example of using MCP (Model Context Protocol) with OpenAI's function calling feature.

**Now with LM Studio support!** Run your MCP chatbot with local LLMs for privacy and cost savings.

## What Does This Do?

This chatbot can:

1. **Connect** to multiple Workato MCP servers simultaneously
2. **Discover** what tools are available from each server (like CRM data, spreadsheets, project management, etc.)
3. **Chat** with an AI that automatically uses those tools to answer your questions

For example, if you connect to a Salesforce MCP server, you could ask:

- "Show me my open opportunities over $50k"
- "What deals closed last week?"
- "Find contacts at Acme Corp"

Or if you have multiple servers configured (e.g., Salesforce + Google Sheets), you could ask:

- "Pull my pipeline data and add it to my forecast spreadsheet"

The AI will automatically call the right tools from the right servers and give you a natural language response.

## Key Concepts Explained

### What is MCP?

**MCP (Model Context Protocol)** is a standard way for AI models to use external tools and data sources. Think of it like a universal adapter that lets any AI talk to any service.

### What is Workato Enterprise MCP?

Workato provides hosted MCP servers that connect to various enterprise services (like CRMs, databases, productivity tools). You get:

- **Security**: OAuth 2.0 and encrypted credentials
- **Compliance**: Audit logging for enterprise regulations
- **Reliability**: Rate limiting and automatic retries

### What is Function Calling?

When you ask the AI a question, it decides if it needs external data. If so, it:

1. Tells us which tool to call
2. We call the tool on the MCP server
3. We send the result back to the AI
4. The AI gives you a human-readable answer

## Project Structure

```
simple-mcp-chat/
├── chat.py                    # Main application using OpenAI (heavily commented!)
├── chat-lmstudio.py           # LM Studio version for local LLMs
├── oauth_handler.py           # OAuth 2.0 authentication handler with PKCE
├── troubleshoot_openai.py     # OpenAI connection troubleshooter
├── mcp_servers.json           # Your MCP server configs (don't commit this!)
├── mcp_servers.example.json   # Example server configuration
├── .mcp_tokens.json           # OAuth tokens storage (auto-generated, don't commit!)
├── pyproject.toml             # Python dependencies
├── uv.lock                    # Locked dependency versions
├── .env                       # Your API keys (don't commit this!)
├── env.example                # Example environment configuration
├── .gitignore                 # Git ignore rules
└── README.md                  # You're reading it
```

## Prerequisites

Before you start, you'll need:

1. **Python 3.10+** installed on your computer
2. **uv** package manager ([install instructions](https://github.com/astral-sh/uv))
3. **OpenAI API key** from [platform.openai.com](https://platform.openai.com)
4. **Workato MCP URL(s)** from your Workato workspace

## Setup Instructions

### Step 1: Clone or Download

```bash
git clone YOUR_REPO_URL
cd simple-mcp-chat
```

### Step 2: Create Your Configuration Files

Copy the example files:

```bash
cp env.example .env
cp mcp_servers.example.json mcp_servers.json
```

Edit `.env` with your OpenAI API key:

```env
# Your OpenAI API key
OPENAI_API_KEY=sk-proj-...your-key-here...
# Which model to use (gpt-4o-mini is cheap and fast)
MODEL=gpt-4o-mini
```

Edit `mcp_servers.json` to configure your MCP servers. You can use either token-based or OAuth authentication.

**Token-based authentication (simple):**

```json
{
  "servers": [
    {
      "name": "salesforce",
      "url": "https://apim.workato.com/your-workspace/salesforce-mcp?token=YOUR_TOKEN",
      "enabled": true,
      "auth_type": "token"
    },
    {
      "name": "jira",
      "url": "https://apim.workato.com/your-workspace/jira-mcp?token=YOUR_TOKEN",
      "enabled": true,
      "auth_type": "token"
    }
  ]
}
```

**OAuth 2.0 authentication (browser-based)** for servers that require OAuth:

```json
{
  "servers": [
    {
      "name": "sheets",
      "url": "https://2107.apim.mcp.workato.com/",
      "enabled": true,
      "auth_type": "oauth"
    }
  ]
}
```

That's it! Just set `"auth_type": "oauth"` and everything else is automatic. When you run the chatbot, it will:

1. **Auto-discover OAuth endpoints** via `.well-known/oauth-authorization-server`
2. **Auto-register as an OAuth client** using dynamic client registration (RFC 7591)
3. Check if you have a stored, valid OAuth token
4. If not, **open your browser** for authentication
5. Start a local server on port 8080 to receive the OAuth callback
6. Exchange the authorization code for an access token using **PKCE** (Proof Key for Code Exchange, RFC 7636) for security
7. Store the token securely in `.mcp_tokens.json` (excluded from Git)
8. Use **Bearer token authentication** in the Authorization header (standard OAuth practice)
9. Automatically refresh tokens when they expire

**Security Features:**

- **PKCE (RFC 7636)**: Protects against authorization code interception attacks
- **Dynamic Client Registration (RFC 7591)**: No manual OAuth client setup required
- **Automatic OAuth Discovery**: Discovers endpoints from `.well-known/oauth-authorization-server`
- **Token Storage**: Securely stores tokens separately from client credentials
- **Bearer Token Authentication**: Uses standard `Authorization: Bearer <token>` headers

### Optional OAuth Configuration

All OAuth parameters are optional and will be auto-discovered/auto-configured if not provided. You can override defaults if needed:

```json
{
  "name": "sheets",
  "url": "https://2107.apim.mcp.workato.com/",
  "enabled": true,
  "auth_type": "oauth",
  "oauth": {
    "client_id": "custom_client_id",
    "client_secret": "custom_client_secret",
    "scopes": ["mcp.read", "mcp.write"],
    "redirect_port": 8080,
    "auth_url": "https://id.workato.com/oauth/authorize",
    "token_url": "https://id.workato.com/oauth/token"
  }
}
```

**Configuration options for each server:**

| Option | Description |
|--------|-------------|
| `name` | A short identifier (used to prefix tool names) |
| `url` | The full Workato MCP endpoint URL |
| `enabled` | Set to `false` to temporarily disable a server |
| `auth_type` | Either `"token"` (default) or `"oauth"` |

**OAuth options (all optional):**

| Option | Description |
|--------|-------------|
| `client_id` | OAuth client ID - will auto-register via RFC 7591 if not provided |
| `client_secret` | OAuth client secret - will auto-register via RFC 7591 if not provided |
| `scopes` | Array of OAuth scopes to request - uses server defaults if not provided |
| `redirect_port` | Local port for OAuth callback - default is 8080 |
| `auth_url` | Custom authorization endpoint - auto-discovered if not provided |
| `token_url` | Custom token endpoint - auto-discovered if not provided |

**OAuth Auto-Discovery & Auto-Registration Flow:**

1. **Endpoint Discovery**: Fetches `.well-known/oauth-authorization-server` from the server URL to discover authorization endpoint, token endpoint, registration endpoint, and supported grant types/scopes.

2. **Dynamic Client Registration**: If no `client_id` is provided, automatically registers as an OAuth client, generates a client name (`simple-mcp-chat-{server_name}`), sets redirect URI (`http://localhost:{redirect_port}/callback`), and stores client credentials in `.mcp_tokens.json`.

3. **PKCE Flow**: Uses Proof Key for Code Exchange for security by generating a random code verifier, creating SHA256 code challenge, sending challenge with authorization request, and sending verifier with token request.

4. **Token Management**: Stores access tokens and refresh tokens in `.mcp_tokens.json`, tracks token expiration times, automatically refreshes tokens when needed, and separates client credentials from access tokens for security.

### Step 3: Install Dependencies

```bash
uv sync
```

This installs:

- `openai` - For talking to GPT
- `python-dotenv` - For loading your .env file
- `requests` - For making HTTP calls to the MCP server and OAuth authentication

### Step 4: Run the Chat

#### Option A: OpenAI (Cloud)

```bash
uv run python chat.py
```

**With System Prompt:**

```bash
# Using command line argument
uv run python chat.py --system-prompt "You are a helpful medical assistant."

# Or use the short form
uv run python chat.py -s "You are a concise assistant that answers in bullet points."

# View all options
uv run python chat.py --help
```

You should see:

```
MCP Chat - Discovering tools...
  - salesforce: 5 tools
  - jira: 3 tools

Connected to 2 server(s) with 8 total tools
Type 'quit' or 'exit' to end
----------------------------------------

You:
```

If you have OAuth-enabled servers, the first run will include OAuth authentication:

```
MCP Chat - Discovering tools...
  Discovered auth endpoint: https://id.workato.com/oauth/authorize
  Discovered token endpoint: https://id.workato.com/oauth/token
  Registering OAuth client for sheets...
  [OK] Client registered successfully

  Opening browser for OAuth authentication...
  Waiting for authorization...

  [SUCCESS] Authorization code received
  [SUCCESS] Access token obtained
  [SUCCESS] Token stored for future use

  - salesforce: 5 tools
  - sheets: 1 tools

Connected to 2 server(s) with 6 total tools
Type 'quit' or 'exit' to end
----------------------------------------

You:
```

Subsequent runs will use the stored token:

```
MCP Chat - Discovering tools...
Using stored token for sheets
  - salesforce: 5 tools
  - sheets: 1 tools

Connected to 2 server(s) with 6 total tools
```

#### Option B: LM Studio (Local)

For running with a local LLM via LM Studio:

1. **Install and start LM Studio** from [lmstudio.ai](https://lmstudio.ai)
2. **Load a model** that supports function calling (look for models with "function calling" or "tool use" support)
3. **Start the local server** in LM Studio (default: `http://localhost:1234`)
4. **Run the LM Studio chat**:

```bash
uv run python chat-lmstudio.py
```

You should see:

```
LM Studio MCP Chat - Discovering tools...
  - salesforce: 5 tools
  - jira: 3 tools

Connected to LM Studio at http://localhost:1234/v1
Connected to 2 MCP server(s) with 8 total tools

Note: Make sure you have a model loaded in LM Studio!
For best results, use a model that supports function calling.
Type 'quit' or 'exit' to end
----------------------------------------

You:
```

**LM Studio Configuration** (optional, in `.env`):

```env
# Change the LM Studio server URL if needed
LMSTUDIO_BASE_URL=http://localhost:1234/v1

# Model name (usually ignored by LM Studio)
LMSTUDIO_MODEL=local-model

# Optional: Set a default system prompt to guide LLM behavior
SYSTEM_PROMPT=You are a helpful assistant.
```

**Using System Prompts:**

You can customize the LLM's behavior by providing a system prompt either via environment variable or command line:

```bash
# Using environment variable (set in .env)
uv run python chat-lmstudio.py

# Using command line argument
uv run python chat-lmstudio.py --system-prompt "You are a helpful medical assistant."

# Or use the short form
uv run python chat-lmstudio.py -s "You are a concise assistant that answers in bullet points."

# View all options
uv run python chat-lmstudio.py --help
```

System prompts are useful for:

- Setting the tone and style of responses
- Specializing the assistant for specific domains (medical, legal, technical, etc.)
- Enforcing response formats (bullet points, brief answers, detailed explanations)
- Adding custom instructions or constraints

Tool names are automatically prefixed with the server name (e.g., `salesforce__Query_Records`) to avoid conflicts between servers.

## Logging and Debugging

The chatbot includes comprehensive logging to help you debug issues and understand what's happening behind the scenes.

### Enabling Detailed Logging

The chatbot supports flexible logging to both console and file. Add these to your `.env` file:

```env
# Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=DEBUG

# Log to file (optional)
LOG_FILE=logs/chat.log

# Show logs in terminal (true/false)
LOG_TO_CONSOLE=true
```

**Configuration Options:**

| Variable | Description | Example |
|----------|-------------|---------|
| `LOG_LEVEL` | Logging detail level | `DEBUG`, `INFO`, `WARNING` |
| `LOG_FILE` | Path to log file (leave empty to disable) | `logs/chat.log` |
| `LOG_TO_CONSOLE` | Show logs in terminal | `true` or `false` |

**Common Configurations:**

1. **Debug to file only (clean terminal):**
   ```env
   LOG_LEVEL=DEBUG
   LOG_FILE=logs/chat.log
   LOG_TO_CONSOLE=false
   ```

2. **Debug to both file and terminal:**
   ```env
   LOG_LEVEL=DEBUG
   LOG_FILE=logs/chat.log
   LOG_TO_CONSOLE=true
   ```

3. **Console only (no file):**
   ```env
   LOG_LEVEL=DEBUG
   LOG_FILE=
   LOG_TO_CONSOLE=true
   ```

**Logging Levels Explained:**

- **DEBUG**: Shows all communication details including:
  - Complete MCP JSON-RPC requests and responses
  - Full OpenAI API requests and responses
  - Tool discovery process
  - Tool execution details
  - Token usage statistics

- **INFO**: Shows high-level operations:
  - Tool calls and which tools are being invoked
  - Server connection status
  - OAuth authentication flow

- **WARNING**: Shows only warnings and errors

- **ERROR/CRITICAL**: Shows only errors

### Example Debug Output

When `LOG_LEVEL=DEBUG`, you'll see detailed logs like:

```
2026-01-12 10:30:45 - __main__ - DEBUG - ================================================================================
2026-01-12 10:30:45 - __main__ - DEBUG - MCP REQUEST
2026-01-12 10:30:45 - __main__ - DEBUG - URL: https://apim.workato.com/your-workspace/dexcom-mcp
2026-01-12 10:30:45 - __main__ - DEBUG - Method: tools/call
2026-01-12 10:30:45 - __main__ - DEBUG - Headers: {
  "Authorization": "Bearer ***"
}
2026-01-12 10:30:45 - __main__ - DEBUG - Payload: {
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "Get_Glucose_Values_v1",
    "arguments": {
      "start_date_time": "2026-01-01T00:00:00",
      "end_date_time": "2026-01-07T23:59:59"
    }
  }
}
2026-01-12 10:30:46 - __main__ - DEBUG - MCP RESPONSE
2026-01-12 10:30:46 - __main__ - DEBUG - Status Code: 200
2026-01-12 10:30:46 - __main__ - DEBUG - Response: {
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Found 1,234 glucose readings..."
      }
    ]
  }
}
2026-01-12 10:30:46 - __main__ - DEBUG - ================================================================================
2026-01-12 10:30:46 - __main__ - DEBUG - ================================================================================
2026-01-12 10:30:46 - __main__ - DEBUG - OPENAI REQUEST
2026-01-12 10:30:46 - __main__ - DEBUG - Model: gpt-4o-mini
2026-01-12 10:30:46 - __main__ - DEBUG - Messages: [
  {
    "role": "user",
    "content": "What was my average glucose last week?"
  },
  {
    "role": "tool",
    "tool_call_id": "call_abc123",
    "content": "Found 1,234 glucose readings..."
  }
]
2026-01-12 10:30:47 - __main__ - DEBUG - OPENAI RESPONSE
2026-01-12 10:30:47 - __main__ - DEBUG - Finish Reason: stop
2026-01-12 10:30:47 - __main__ - DEBUG - Content: Your average glucose last week was 125 mg/dL...
2026-01-12 10:30:47 - __main__ - DEBUG - Usage: prompt_tokens=523, completion_tokens=87, total_tokens=610
2026-01-12 10:30:47 - __main__ - DEBUG - ================================================================================
```

### What Gets Logged

**MCP Server Communication:**
- Request URL and method
- Request payload (JSON-RPC 2.0 format)
- Authorization headers (masked for security)
- Response status codes
- Complete response data

**OpenAI LLM Communication:**
- Model being used
- Complete message history sent to OpenAI
- Available tools and their names
- OpenAI's response content
- Tool calls requested by OpenAI
- Token usage (prompt, completion, and total tokens)

**Tool Operations:**
- Tool discovery from each server
- Tool names and descriptions
- Tool execution with arguments
- Tool results (truncated if very long)

### Log Files

When `LOG_FILE` is set, logs are saved to the specified file:

- The `logs/` directory is automatically created if it doesn't exist
- Logs are appended to the file (not overwritten)
- The `logs/` directory is excluded from Git (already in `.gitignore`)
- You can use any path: `logs/chat.log`, `logs/debug-2026-01-12.log`, etc.

**Viewing Log Files:**

```bash
# View entire log file
cat logs/chat.log

# Follow log in real-time (like tail -f)
tail -f logs/chat.log

# View last 50 lines
tail -n 50 logs/chat.log

# Search logs for errors
grep "ERROR" logs/chat.log
```

### Security Note

Authorization tokens in the logs are automatically masked to show `Bearer ***` instead of the actual token value. Your API keys remain secure even with DEBUG logging enabled.

## How to Use

Just type natural language questions! The AI will figure out which tools to use.

### Example Conversation

```
You: What open deals do I have over $100k?

[Calling salesforce__Query_Opportunities...]

A: You have 3 open opportunities over $100k:
   1. Acme Corp - Enterprise License ($150,000) - Closing Jan 30
   2. GlobalTech - Platform Deal ($125,000) - Closing Feb 15
   3. Initech - Annual Contract ($110,000) - Closing Feb 28

You: Create a Jira ticket to follow up on the Acme deal

[Calling jira__Create_Issue...]

A: Created SALES-142: "Follow up on Acme Corp Enterprise License opportunity"
```

## Example Prompts

Here are some prompts you can try with different MCP tools:

### CRM (Salesforce, HubSpot)

- "Show me all opportunities closing this month"
- "Find contacts at companies in the healthcare industry"
- "What's the total value of my pipeline?"
- "List accounts I haven't contacted in 30 days"
- "Create a new lead for John Smith at Acme Corp"

### Project Management (Jira, Asana)

- "What tickets are assigned to me?"
- "Show me all high-priority bugs"
- "Create a task to review the Q1 roadmap"
- "What's the status of PROJECT-123?"
- "List all issues updated this week"

### Productivity (Google Sheets, Calendar)

- "Add a row to my sales tracker spreadsheet"
- "What meetings do I have tomorrow?"
- "Find all spreadsheets with 'budget' in the name"
- "Update cell B5 to show the new forecast"

### Communication (Slack, Email)

- "Send a message to #sales-team about the new pricing"
- "Search for emails from our legal team"
- "What unread messages do I have?"

### Multi-Tool Queries

The AI can automatically chain multiple tool calls:

- "Find my biggest deal and create a Jira ticket to prepare the proposal"
- "Get my calendar for tomorrow and send a Slack summary to my team"
- "Pull Q4 sales data and update the forecast spreadsheet"

## Troubleshooting

### OpenAI Connection Troubleshooter

If you're having issues connecting to OpenAI, run the built-in troubleshooter:

```bash
uv run python troubleshoot_openai.py
```

This script diagnoses common issues including:

- Network connectivity to OpenAI servers
- DNS resolution
- Firewall/proxy blocking
- SSL/TLS issues
- API key validation
- Model access

For more detailed output, use the verbose flag:

```bash
uv run python troubleshoot_openai.py --verbose
```

### "No MCP servers configured"

Make sure you have a `mcp_servers.json` file with at least one server configured.

### "No tools discovered"

Check that your server URLs in `mcp_servers.json` are correct and include the authentication token (for token-based auth) or that OAuth authentication succeeded (for OAuth auth).

### "Error calling tool" or "401 Unauthorized"

- For **token-based auth**: Your token might have expired. Check your Workato workspace for a new token.
- For **OAuth auth**: Your stored token might have expired. Delete `.mcp_tokens.json` and restart the application to re-authenticate.

### "Invalid API key"

Make sure your `OPENAI_API_KEY` is correct in the `.env` file.

### One server fails but others work

The chatbot will continue with the servers that succeed. Check the error message for the failing server and verify its URL/token.

### OAuth: "OAuth authentication failed"

Common causes:

- **Port 8080 already in use**: Change `redirect_port` in your OAuth config
- **Browser didn't open**: Manually copy the URL from the terminal into your browser
- **OAuth server doesn't support dynamic registration**: Manually create an OAuth client in Workato and provide `client_id` and `client_secret` in the config

### OAuth: "Code challenge is required"

This should not happen - PKCE is automatically enabled. If you see this, please report it as a bug.

### OAuth: Token stored but still getting 401 errors

The OAuth implementation uses Bearer token authentication. If you're still getting 401 errors:

1. Delete `.mcp_tokens.json`
2. Restart the application
3. Re-authenticate in the browser
4. The new token will use Bearer authentication

### LM Studio: "Could not connect to LM Studio"

Make sure LM Studio is running and the local server is started. Check that the URL matches (default: `http://localhost:1234/v1`).

### LM Studio: Tools not being called

Not all models support function calling. Try a model that explicitly supports tool use, such as:

- Mistral Instruct models
- Llama models with function calling support
- Qwen models with tool support

## License

MIT

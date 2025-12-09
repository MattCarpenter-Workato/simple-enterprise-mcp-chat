# Simple MCP Chat

A beginner-friendly Python chatbot that connects to Workato's Enterprise MCP servers. This is the simplest possible example of using MCP (Model Context Protocol) with OpenAI's function calling feature.

**Now with LM Studio support!** Run your MCP chatbot with local LLMs for privacy and cost savings.

## What Does This Do?

This chatbot can:

1. **Connect** to multiple Workato MCP servers simultaneously
2. **Discover** what tools are available from each server (like getting health data, CRM records, etc.)
3. **Chat** with an AI that automatically uses those tools to answer your questions

For example, if you connect to a Dexcom health MCP server, you could ask:

- "What are my glucose values from last week?"
- "Show me any alerts from yesterday"
- "What devices do I have connected?"

Or if you have multiple servers configured (e.g., Dexcom + Salesforce), you could ask:

- "Show me my glucose data and my recent Salesforce contacts"

The AI will automatically call the right tools from the right servers and give you a natural language response.

## Key Concepts Explained

### What is MCP?

**MCP (Model Context Protocol)** is a standard way for AI models to use external tools and data sources. Think of it like a universal adapter that lets any AI talk to any service.

### What is Workato Enterprise MCP?

Workato provides hosted MCP servers that connect to various enterprise services (like healthcare APIs, CRMs, databases). You get:

- **Security**: OAuth 2.0 and encrypted credentials
- **Compliance**: Audit logging for regulations like HIPAA
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
      "name": "dexcom",
      "url": "https://apim.workato.com/your-workspace/dexcom-mcp?token=YOUR_TOKEN",
      "enabled": true,
      "auth_type": "token"
    },
    {
      "name": "salesforce",
      "url": "https://apim.workato.com/your-workspace/salesforce-mcp?token=YOUR_TOKEN",
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

You should see:

```
MCP Chat - Discovering tools...
  - dexcom: 5 tools
  - salesforce: 3 tools

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

  - dexcom: 5 tools
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
  - dexcom: 5 tools
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
  - dexcom: 5 tools
  - salesforce: 3 tools

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
```

Tool names are automatically prefixed with the server name (e.g., `dexcom__Get_Glucose_Values_v1`) to avoid conflicts between servers.

## How to Use

Just type natural language questions! The AI will figure out which tools to use.

### Example Conversation

```
You: What glucose data do you have available?

[Calling Get_Data_Range_v1...]

A: I have glucose data available from January 15, 2024 to January 22, 2024.

You: Show me my glucose readings from yesterday

[Calling Get_Glucose_Values_v1...]

A: Here are your glucose readings from yesterday...
```

## Example Prompts

Here are some prompts you can try with different MCP tools:

### Health Data (Dexcom)

- "What date range of data do you have?"
- "Show me my glucose values from the last 24 hours"
- "What was my average glucose yesterday?"
- "Were there any high or low alerts this week?"
- "What devices are connected to my account?"
- "Show me any events I logged today"

### General Queries

- "What tools do you have available?"
- "Help me understand my recent health trends"
- "Summarize my data from last week"

### Multi-Tool Queries

The AI can automatically chain multiple tool calls:

- "Compare my glucose levels between Monday and Tuesday"
- "Show me all alerts and their corresponding glucose values"

## Troubleshooting

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

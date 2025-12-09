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

\`\`\`
simple-mcp-chat/
├── chat.py                    # Main application using OpenAI (heavily commented!)
├── chat-lmstudio.py           # LM Studio version for local LLMs
├── mcp_servers.json           # Your MCP server configs (don't commit this!)
├── mcp_servers.example.json   # Example server configuration
├── pyproject.toml             # Python dependencies
├── uv.lock                    # Locked dependency versions
├── .env                       # Your API keys (don't commit this!)
├── env.example                # Example environment configuration
├── .gitignore                 # Git ignore rules
└── README.md                  # You're reading it
\`\`\`

## Prerequisites

Before you start, you'll need:

1. **Python 3.10+** installed on your computer
2. **uv** package manager ([install instructions](https://github.com/astral-sh/uv))
3. **OpenAI API key** from [platform.openai.com](https://platform.openai.com)
4. **Workato MCP URL(s)** from your Workato workspace

## Setup Instructions

### Step 1: Clone or Download

\`\`\`bash
git clone <your-repo-url>
cd simple-mcp-chat
\`\`\`

### Step 2: Create Your Configuration Files

Copy the example files:

\`\`\`bash
cp env.example .env
cp mcp_servers.example.json mcp_servers.json
\`\`\`

Edit \`.env\` with your OpenAI API key:

\`\`\`env
# Your OpenAI API key
OPENAI_API_KEY=sk-proj-...your-key-here...

# Which model to use (gpt-4o-mini is cheap and fast)
MODEL=gpt-4o-mini
\`\`\`

Edit \`mcp_servers.json\` to configure your MCP servers. You can use either token-based or OAuth authentication.

Token-based authentication (simple):

\`\`\`json
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
\`\`\`

OAuth 2.0 authentication (browser-based) for servers that require OAuth:

\`\`\`json
{
  "servers": [
    {
      "name": "sheets",
      "url": "https://apim.workato.com/your-workspace/sheets-mcp",
      "enabled": true,
      "auth_type": "oauth"
    }
  ]
}
\`\`\`

That's it! The OAuth endpoints will be automatically discovered from the server URL. When you run the chatbot, it will:

1. Auto-discover OAuth endpoints (\`/oauth/authorize\` and \`/oauth/token\`)
2. Check if you have a stored, valid OAuth token
3. If not, open your browser for authentication
4. Start a local server on port 8080 to receive the OAuth callback
5. Exchange the authorization code for an access token
6. Store the token securely in \`.mcp_tokens.json\` (excluded from Git)
7. Automatically refresh tokens when they expire

**Optional OAuth Configuration**

If your server requires additional OAuth parameters, you can optionally provide them:

\`\`\`json
{
  "name": "sheets",
  "url": "https://apim.workato.com/your-workspace/sheets-mcp",
  "enabled": true,
  "auth_type": "oauth",
  "oauth": {
    "client_id": "your_client_id",
    "client_secret": "your_client_secret",
    "scopes": ["mcp.read", "mcp.write"],
    "redirect_port": 8080,
    "auth_url": "https://custom.auth.url/authorize",
    "token_url": "https://custom.auth.url/token"
  }
}
\`\`\`

Configuration options for each server:

- **name**: A short identifier (used to prefix tool names)
- **url**: The full Workato MCP endpoint URL
- **enabled**: Set to \`false\` to temporarily disable a server
- **auth_type**: Either \`"token"\` (default) or \`"oauth"\`
- **oauth** (optional): Additional OAuth configuration
  - **client_id** (optional): OAuth client ID
  - **client_secret** (optional): OAuth client secret
  - **scopes** (optional): Array of OAuth scopes to request
  - **redirect_port** (optional): Local port for OAuth callback (default: 8080)
  - **auth_url** (optional): Custom authorization endpoint (auto-discovered if not provided)
  - **token_url** (optional): Custom token endpoint (auto-discovered if not provided)

### Step 3: Install Dependencies

\`\`\`bash
uv sync
\`\`\`

This installs:
- \`openai\` - For talking to GPT
- \`python-dotenv\` - For loading your .env file
- \`requests\` - For making HTTP calls to the MCP server

### Step 4: Run the Chat

#### Option A: OpenAI (Cloud)

\`\`\`bash
uv run python chat.py
\`\`\`

You should see:
\`\`\`
MCP Chat - Discovering tools...
  - dexcom: 5 tools
  - salesforce: 3 tools

Connected to 2 server(s) with 8 total tools
Type 'quit' or 'exit' to end
----------------------------------------

You:
\`\`\`

#### Option B: LM Studio (Local)

For running with a local LLM via LM Studio:

1. **Install and start LM Studio** from [lmstudio.ai](https://lmstudio.ai)
2. **Load a model** that supports function calling (look for models with "function calling" or "tool use" support)
3. **Start the local server** in LM Studio (default: `http://localhost:1234`)
4. **Run the LM Studio chat**:

\`\`\`bash
uv run python chat-lmstudio.py
\`\`\`

You should see:
\`\`\`
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
\`\`\`

**LM Studio Configuration** (optional, in `.env`):
\`\`\`env
# Change the LM Studio server URL if needed
LMSTUDIO_BASE_URL=http://localhost:1234/v1

# Model name (usually ignored by LM Studio)
LMSTUDIO_MODEL=local-model
\`\`\`

Tool names are automatically prefixed with the server name (e.g., \`dexcom__Get_Glucose_Values_v1\`) to avoid conflicts between servers.

## How to Use

Just type natural language questions! The AI will figure out which tools to use.

### Example Conversation

```
You: What glucose data do you have available?

[Calling Get_Data_Range_v1...]

Assistant: I have glucose data available from January 15, 2024 to January 22, 2024.

You: Show me my glucose readings from yesterday

[Calling Get_Glucose_Values_v1...]

Assistant: Here are your glucose readings from yesterday...
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
Check that your server URLs in `mcp_servers.json` are correct and include the authentication token.

### "Error calling tool"
The MCP server might be down or your token might have expired. Check your Workato workspace.

### "Invalid API key"
Make sure your `OPENAI_API_KEY` is correct in the `.env` file.

### One server fails but others work
The chatbot will continue with the servers that succeed. Check the error message for the failing server and verify its URL/token.

### LM Studio: "Could not connect to LM Studio"
Make sure LM Studio is running and the local server is started. Check that the URL matches (default: `http://localhost:1234/v1`).

### LM Studio: Tools not being called
Not all models support function calling. Try a model that explicitly supports tool use, such as:
- Mistral Instruct models
- Llama models with function calling support
- Qwen models with tool support

## License

MIT

# Simple MCP Chat

A beginner-friendly Python chatbot that connects to Workato's Enterprise MCP servers. This is the simplest possible example of using MCP (Model Context Protocol) with OpenAI's function calling feature.

## What Does This Do?

This chatbot can:
1. **Connect** to a Workato MCP server
2. **Discover** what tools are available (like getting health data, alerts, etc.)
3. **Chat** with an AI that automatically uses those tools to answer your questions

For example, if you connect to a Dexcom health MCP server, you could ask:
- "What are my glucose values from last week?"
- "Show me any alerts from yesterday"
- "What devices do I have connected?"

The AI will automatically call the right tools and give you a natural language response.

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
├── chat.py          # Main application (heavily commented!)
├── pyproject.toml   # Python dependencies
├── .env             # Your API keys (don't commit this!)
├── .env.example     # Example configuration
└── README.md        # You're reading it
```

## Prerequisites

Before you start, you'll need:

1. **Python 3.10+** installed on your computer
2. **uv** package manager ([install instructions](https://github.com/astral-sh/uv))
3. **OpenAI API key** from [platform.openai.com](https://platform.openai.com)
4. **Workato MCP URL** from your Workato workspace

## Setup Instructions

### Step 1: Clone or Download

```bash
git clone <your-repo-url>
cd simple-mcp-chat
```

### Step 2: Create Your Environment File

Copy the example environment file:

```bash
cp .env.example .env
```

Then edit `.env` with your actual values:

```env
# Your OpenAI API key
OPENAI_API_KEY=sk-proj-...your-key-here...

# Which model to use (gpt-4o-mini is cheap and fast)
MODEL=gpt-4o-mini

# Your Workato MCP server URL (includes authentication token)
MCP_URL=https://your-workspace.apim.mcp.workato.com/your-project/your-api?wkt_token=your-token
```

### Step 3: Install Dependencies

```bash
uv sync
```

This installs:
- `openai` - For talking to GPT
- `python-dotenv` - For loading your .env file
- `requests` - For making HTTP calls to the MCP server

### Step 4: Run the Chat

```bash
uv run python chat.py
```

You should see:
```
MCP Chat - Connected to 5 tools
Tools: Get_Alerts_v1, Get_Data_Range_v1, Get_Devices_v1, Get_Events_v1, Get_Glucose_Values_v1
Type 'quit' or 'exit' to end
----------------------------------------

You:
```

## How to Use

Just type natural language questions! The AI will figure out which tools to use.

### Example Conversation

```
You: What glucose data do you have available?

[Calling Get_Data_Range_v1...]
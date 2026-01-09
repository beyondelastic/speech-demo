# Voice UI Approach - Complete Voice Interface

A full-featured web-based voice interface for controlling browsers through Microsoft Foundry AI Agents. Features local speech processing, agent communication, and automatic MCP tool approval for seamless browser automation.

## Overview

This approach provides a complete voice-to-browser-automation pipeline:
- Rich web UI for voice interaction
- Azure Speech Services for speech-to-text and text-to-speech
- Microsoft Foundry Agent with GPT-4o for intelligence
- Playwright MCP Server for advanced browser control
- Automatic tool approval for uninterrupted automation

## Features

- 🎙️ **Voice Input**: Record and stream voice messages with real-time recognition
- 🔊 **Voice Output**: Agent responds with natural synthesized speech
- 💬 **Chat Transcript**: Visual conversation history with timestamps
- 🤖 **Auto-Approval**: MCP tool requests automatically approved for seamless execution
- 🔄 **Stateful Conversations**: Persistent thread context across interactions
- 🌐 **Browser Automation**: Full browser control via Playwright (navigate, click, extract data)
- 📡 **WebSocket Streaming**: Real-time audio streaming for faster response
- ⚙️ **Flexible Configuration**: Support for custom speech keys or Foundry integration

## Architecture

```
┌─────────────────┐
│   Browser UI    │  User speaks into microphone
│  (index.html)   │  
└────────┬────────┘
         │ WebM Audio (MediaRecorder API)
         ↓
┌─────────────────┐
│  FastAPI Server │  
│    (main.py)    │
└────────┬────────┘
         ├──> Azure Speech Services
         │    • Speech-to-Text (STT)
         │    • Text-to-Speech (TTS)
         │
         ├──> Microsoft Foundry Agent
         │    • GPT-4o model
         │    • Thread management
         │    • Tool calling
         │
         └──> Auto-Approval System
              • Intercepts MCP tool requests
              • Automatically approves Playwright actions
              • Returns results to agent
                     ↓
              ┌──────────────────┐
              │ Playwright MCP   │  Browser automation
              │ Server (Local)   │  (navigate, click, etc.)
              └──────────────────┘
```

## Prerequisites

### Azure Resources

1. **Microsoft Foundry Project** with:
   - An agent configured with gpt-4o model
   - Playwright MCP server enabled
   - Multi-service AI account (includes Speech Services)

2. **Azure Authentication**:
   - Azure CLI installed and logged in (`az login`)
   - Or appropriate credentials configured

### Local Requirements

- Python 3.8+
- Node.js and npm (for Playwright MCP server)
- ffmpeg (for audio conversion)

## Installation

1. **Navigate to the project**:
   ```bash
   cd voice-ui-approach
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**:
   
   Create a `.env` file in the parent directory:
   
   ```bash
   # Required
   PROJECT_ENDPOINT=https://your-resource.services.ai.azure.com/api/projects/your-project
   MODEL_DEPLOYMENT_NAME=gpt-4o
   
   # Optional (will use PROJECT_ENDPOINT if not provided)
   SPEECH_KEY=your-speech-key
   SPEECH_REGION=swedencentral
   ```

4. **Authenticate with Azure**:
   ```bash
   az login
   ```

## Running the Application

### 1. Start the Playwright MCP Server

The agent requires the Playwright MCP server for browser automation:

```bash
npx @playwright/mcp@latest --port 8931 --host 0.0.0.0
```

Keep this terminal running. The server listens on port 8931.

### 2. Expose Playwright MCP Server via Dev Tunnel

Since the Foundry agent runs in the cloud, it needs access to your local MCP server. Use a dev tunnel:

**First-time setup:**
```bash
# Authenticate
devtunnel user login

# Create tunnel
devtunnel create playwright-mcp-tunnel -a

# Create port mapping for MCP server
devtunnel port create playwright-mcp-tunnel -p 8931
```

**Start the tunnel** (in a separate terminal):
```bash
devtunnel host playwright-mcp-tunnel
```

You'll see output like:
```
Connect via browser: https://playwright-mcp-tunnel-xxx.devtunnels.ms
```

**Configure in Foundry**: Use this URL when configuring the Playwright MCP server in your Microsoft Foundry agent settings.

### 3. Start the FastAPI Server

```bash
python main.py
```

Server starts at `http://localhost:8000`

### 4. Open in Browser

Navigate to `http://localhost:8000`

### 5. Configure Agent in Foundry

**Important**: Configure your Foundry agent with the system prompt from [AGENT_SYSTEM_PROMPT.md](AGENT_SYSTEM_PROMPT.md). This prompt enables:
- Multi-language support (English/German)
- Proper URL and domain handling
- Browser command understanding
- Cookie popup handling

**In the web UI:**
- Enter your **Agent ID** (the name you gave your agent in Foundry)
- Speech credentials are auto-detected from `.env` or Azure
- Click **Save**

### 6. Start Conversation

- Click 🎤 to start recording
- Speak your request
- Click ⏹️ to stop
- Agent responds with voice and text

## Complete Startup Checklist

For a full working setup, you need these running simultaneously:

- [ ] **Terminal 1**: Playwright MCP Server
  ```bash
  npx @playwright/mcp@latest --port 8931 --host 0.0.0.0
  ```

- [ ] **Terminal 2**: Dev Tunnel (for MCP server)
  ```bash
  devtunnel host playwright-mcp-tunnel
  ```

- [ ] **Terminal 3**: FastAPI Backend
  ```bash
  python main.py
  ```

- [ ] **Browser**: http://localhost:8000

- [ ] **Foundry Agent**: Configured with dev tunnel URL for MCP server

## Example Commands

Try saying:
- "Open my browser and navigate to Google"
- "Search for cats"
- "Click on the Images tab"
- "Go to GitHub.com"
- "Open a new tab and go to Wikipedia"

The agent will automatically approve and execute Playwright MCP tool calls to control the browser.

## How It Works

### Speech-to-Text Flow
1. Browser records audio as WebM
2. Backend converts to 16kHz WAV PCM
3. Azure Speech Services transcribes to text

### Agent Interaction
1. Text sent to Foundry agent via Conversations API
2. Agent decides to use tools (e.g., Playwright)
3. MCP approval requests automatically approved
4. Agent executes browser actions
5. Response extracted and returned

### Text-to-Speech Flow
1. Agent response text sent to Azure Speech
2. Audio synthesized as WAV
3. Streamed back to browser for playback

### MCP Auto-Approval
The backend automatically:
- Detects `mcp_approval_request` in agent responses
- Sends `mcp_approval_response` with `approve=True`
- Loops until all tools complete
- Maintains conversation state via `previous_response_id`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve web UI |
| `/api/speech-to-text` | POST | Convert audio to text |
| `/api/agent/chat` | POST | Send message to agent |
| `/api/text-to-speech` | POST | Convert text to audio |
| `/api/agent/thread/{id}` | DELETE | Clear conversation |
| `/health` | GET | Health check |

## Project Structure

```
voice-ui-approach/
├── main.py                  # FastAPI backend
├── index.html               # Web interface
├── app.js                  # Frontend JavaScript
├── requirements.txt         # Python dependencies
├── AGENT_SYSTEM_PROMPT.md  # Foundry agent configuration
├── .env.example            # Environment template
└── README.md               # This file
```

## Configuration Details

### Agent Reference
Agents are referenced by **name** (not ID) in the new Foundry API:
```python
extra_body={"agent": {"name": "playwright-agent", "type": "agent_reference"}}
```

### Conversation State
- Conversations persist across requests using conversation IDs
- `previous_response_id` maintains approval state between turns
- Prevents "pending approval" errors on subsequent messages

### Speech Configuration
The system uses a cascading configuration priority:
1. UI-provided credentials (if entered)
2. Environment variables (SPEECH_KEY, SPEECH_REGION)
3. Multi-service account from PROJECT_ENDPOINT

## Troubleshooting

### "No speech recognized"
- Check microphone permissions in browser
- Speak clearly after clicking the mic button
- Ensure audio is being recorded (check browser console)

### "Missing Foundry configuration"
- Verify `.env` file exists in parent directory
- Check `PROJECT_ENDPOINT` and `MODEL_DEPLOYMENT_NAME` are set

### "Agent communication error"
- Ensure you're logged in: `az login`
- Verify agent name matches exactly
- Check agent has Playwright MCP server enabled

### Browser doesn't open
- Verify Playwright MCP server is configured in Foundry
- Check server logs for MCP approval messages
- Ensure agent has permission to use tools

## Development

### Enable Debug Logging
The application logs to console with prefixes:
- `[STT]` - Speech-to-text events
- `[AGENT]` - Agent messages
- `[MCP]` - Tool approval events
- `[RESPONSE]` - Agent responses
- `[ERROR]` - Errors

### Testing Without Voice
You can test the agent interaction by modifying `app.js` to bypass speech recognition and send text directly to the `/api/agent/chat` endpoint.

## License

MIT

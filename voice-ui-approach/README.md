# Voice UI Approach - OR Voice Assistant

A hands-free voice interface for operating rooms, built on Microsoft Foundry AI Agents. Surgeons and medical staff can control OR lighting and browse the web using voice commands — no hands required.

## Overview

This approach provides three voice-controlled capabilities:
1. **OR Lighting Control** — adjust surgical/ambient lights, activate scene presets, and control individual fixtures via an MCP tool server
2. **Medical Device Control** — control a CO2 insufflator (pressure, flow rate, power) via an on-premises OpenAPI tool
3. **Browser Automation** — navigate websites, search, click elements, and more via Playwright MCP

All are powered by a single Foundry agent that receives voice input and decides which tools to call.

## Features

- 🎙️ **Voice Input**: Record and stream voice messages with real-time recognition
- 🔊 **Voice Output**: Agent responds with natural synthesized speech
- 💡 **OR Lighting Control**: Voice-controlled surgical and ambient lights with scene presets
- 🫁 **Medical Device Control**: Voice-controlled CO2 insufflator with live pressure/flow gauges
- 🏥 **Live OR Visualization**: Real-time light panel and device panel showing states in real time
- 🌐 **Browser Automation**: Full browser control via Playwright (navigate, click, extract data)
- 💬 **Chat Transcript**: Visual conversation history with timestamps
- 🤖 **Auto-Approval**: MCP tool requests automatically approved for seamless execution
- 📡 **WebSocket Streaming**: Real-time binary audio streaming for faster response
- 🌍 **Multi-language**: Supports English and German voice commands

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Browser UI (index.html)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐          │
│  │  Voice Chat   │  │  OR Light    │  │  Device       │          │
│  │  Panel        │  │  Panel       │  │  Panel        │          │
│  └──────┬───────┘  └──────▲───────┘  └───────▲───────┘          │
│         │ WebSocket        │ Polling          │ Polling          │
│         │ Audio            │ :8932            │ :8933            │
│         │                  │ /api/state       │ /api/devices/    │
│         │                  │                  │ state            │
└─────────┼──────────────────┼──────────────────┼─────────────────┘
          ↓                  │                  │
┌─────────────────────────────────────────────┐ │
│           FastAPI Server (main.py)          │ │
│           Port 8000                         │ │
└────────┬────────────────────────────────────┘ │
         │                                      │
         ├──> Azure Speech                      │
         │    • STT / TTS (binary Opus)         │
         │                                      │
         └──> Foundry Agent (cloud)             │
              • GPT-4.1 model                   │
              │                                 │
              ├────────────────┬────────────────┐
              ↓                ↓                ↓
     ┌────────────────┐ ┌──────────────┐ ┌─────────────────┐
     │ Playwright MCP │ │ OR Lights MCP│ │ OR Device API   │
     │ Server :8931   │ │ Server :8932 │ │ Server :8933    │
     │ (browser)      │ │ (lighting)   │ │ (insufflator)   │
     └────────────────┘ └──────────────┘ └─────────────────┘
              ↑ exposed via Dev Tunnel ↑            ↑
```

## Prerequisites

### Azure Resources

1. **Microsoft Foundry Project** with:
   - An agent configured with gpt-4.1 model
   - Playwright MCP server enabled
   - Multi-service AI account (includes Speech Services)

2. **Azure Authentication**:
   - Azure CLI installed and logged in (`az login`)
   - Or appropriate credentials configured

### Local Requirements

- Python 3.10+
- Node.js and npm (for Playwright MCP server)
- ffmpeg (for audio conversion)

## Quick Start

The easiest way to start all services is with the included script:

```bash
cd voice-ui-approach
./start.sh
```

This starts all five services in sequence:
1. **OR Lights MCP Server** (port 8932) — lighting control tools
2. **OR Device API Server** (port 8933) — medical device control (insufflator)
3. **Playwright MCP Server** (port 8931) — browser automation tools
4. **Dev Tunnel** — exposes MCP servers and device API to Foundry cloud
5. **FastAPI Backend** (port 8000) — web UI, speech, agent communication

Press `Ctrl+C` to stop all services.

## Manual Setup

If you prefer to start services individually:

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
   AGENT_ID=your-agent-name
   
   # Optional (will use PROJECT_ENDPOINT if not provided)
   SPEECH_KEY=your-speech-key
   SPEECH_REGION=swedencentral
   ```

4. **Authenticate with Azure**:
   ```bash
   az login
   ```

## Running the Application

### 1. Start the OR Lights MCP Server

```bash
python or_lights_mcp.py --port 8932
```

This server exposes lighting control tools via Streamable HTTP transport. It persists light state to `.or_lights_state.json`.

### 2. Start the OR Device API Server

The device API simulates an on-premises CO2 insufflator controller:
```bash
python or_device_api.py --port 8933
```

This server exposes device control endpoints at `localhost:8933`. It persists state to `.or_devices_state.json`.
Authentication is required for control endpoints (API key: `x-api-key` header or query parameter).

### 3. Start the Playwright MCP Server

The agent requires the Playwright MCP server for browser automation.

**First-time setup (if running in WSL):**
```bash
# Install Chromium browser
npx playwright install chromium

# Install system dependencies for browser to run in WSL
npx playwright install-deps chromium
```

```bash
npx @playwright/mcp@latest --port 8931 --host 0.0.0.0 --browser chromium --shared-browser-context
```

**Important flags:**
- `--browser chromium`: Specifies which browser to use (chromium, firefox, webkit, msedge)
- `--shared-browser-context`: Keeps the browser window open and reuses the same context between agent requests

Keep this terminal running. The server listens on port 8931.

### 4. Expose Services via Dev Tunnel

Since the Foundry agent runs in the cloud, it needs access to your local MCP servers and device API. Use a dev tunnel:

**First-time setup:**
```bash
# Authenticate
devtunnel user login

# Create tunnel
devtunnel create playwright-mcp-tunnel -a

# Create port mappings for MCP servers and device API
devtunnel port create playwright-mcp-tunnel -p 8931
devtunnel port create playwright-mcp-tunnel -p 8932
devtunnel port create playwright-mcp-tunnel -p 8933
```

**Start the tunnel** (in a separate terminal):
```bash
devtunnel host playwright-mcp-tunnel
```

You'll see output with URLs like:
```
https://kk13d7j6-8931.euw.devtunnels.ms   → Playwright MCP
https://kk13d7j6-8932.euw.devtunnels.ms   → OR Lights MCP
https://kk13d7j6-8933.euw.devtunnels.ms   → OR Device API
```

**Configure in Foundry**:
- **Playwright MCP**: Add as MCP tool with dev tunnel URL for port 8931 (SSE endpoint)
- **OR Lights MCP**: Add as MCP tool with dev tunnel URL for port 8932 (SSE endpoint)
- **OR Device API**: Add as OpenAPI tool with dev tunnel URL for port 8933 (uses `devices_openapi.json`)

### 5. Start the FastAPI Server

```bash
python main.py
```

Server starts at `http://localhost:8000`

### 6. Open in Browser

Navigate to `http://localhost:8000`

### 7. Configure Agent in Foundry

**Important**: Configure your Foundry agent with the system prompt from [AGENT_SYSTEM_PROMPT.md](AGENT_SYSTEM_PROMPT.md). This prompt enables:
- Multi-language support (English/German)
- Proper URL and domain handling
- Browser command understanding
- OR lighting control with scene presets
- Medical device control (insufflator)
- Combined OR commands (e.g., "prepare for laparoscopy")
- Cookie popup handling

**In Foundry**, add all tool servers:
- **Playwright MCP**: Use the dev tunnel URL for port 8931 (SSE endpoint)
- **OR Lights MCP**: Use the dev tunnel URL for port 8932 (SSE endpoint)
- **OR Device API**: Import `devices_openapi.json` as an OpenAPI tool, using the dev tunnel URL for port 8933

**In the web UI:**
- Enter your **Agent ID** (the name you gave your agent in Foundry)
- Speech credentials are auto-detected from `.env` or Azure
- Click **Save**

### 8. Start Conversation

- Click 🎤 to start recording
- Speak your request
- Click ⏹️ to stop
- Agent responds with voice and text

## Complete Startup Checklist

For a full working setup, you need these running simultaneously:

- [ ] **Terminal 1**: OR Lights MCP Server
  ```bash
  python or_lights_mcp.py --port 8932
  ```

- [ ] **Terminal 2**: OR Device API Server
  ```bash
  python or_device_api.py --port 8933
  ```

- [ ] **Terminal 3**: Playwright MCP Server
  ```bash
  npx @playwright/mcp@latest --port 8931 --host 0.0.0.0 --browser chromium --shared-browser-context
  ```

- [ ] **Terminal 4**: Dev Tunnel (for MCP servers + device API)
  ```bash
  devtunnel host playwright-mcp-tunnel
  ```

- [ ] **Terminal 5**: FastAPI Backend
  ```bash
  python main.py
  ```

- [ ] **Browser**: http://localhost:8000

- [ ] **Foundry Agent**: Configured with dev tunnel URLs for MCP servers and OpenAPI tool

Or simply run `./start.sh` to start everything at once.

## Example Commands

### Lighting Control
- "Turn on the surgical light"
- "Dim the lights to 50 percent"
- "Switch to laparoscopy mode"
- "Surgery mode"
- "All lights off"
- "Emergency lights"
- "What's the current light status?"

### Medical Device Control
- "Turn on the insufflator"
- "Set pressure to 14 mmHg"
- "Set flow rate to 30 liters per minute"
- "What's the insufflator status?"
- "Turn off the insufflator"

### Combined OR Commands
- "Prepare for laparoscopy" (activates laparoscopy lighting scene + powers on insufflator with standard settings)

### Browser Automation
- "Open a browser and navigate to Google"
- "Search for cats"
- "Click on the Images tab"
- "Go to GitHub.com"
- "Open a new tab and go to Wikipedia"

The agent will automatically execute MCP tool calls to control lights, devices, and browser.

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
2. Audio synthesized as Opus
3. Streamed back to browser for playback

### Tool Execution
The Foundry agent is configured with `require_approval: "never"` on all MCP tools, so tool calls execute immediately without approval round-trips. The backend maintains conversation state via `previous_response_id` and includes retry logic with exponential backoff for rate limits.

## API Endpoints

### FastAPI Backend (port 8000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve web UI |
| `/api/speech-to-text` | POST | Convert audio to text |
| `/api/agent/chat` | POST | Send message to agent |
| `/api/text-to-speech` | POST | Convert text to audio |
| `/api/config` | GET | Get default configuration |
| `/api/agent/thread/{id}` | DELETE | Clear conversation |
| `/health` | GET | Health check |

### OR Device API (port 8933)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/devices/state` | GET | No | Get current device states |
| `/api/devices/insufflator/power` | POST | Yes | Power on/off the insufflator |
| `/api/devices/insufflator/settings` | POST | Yes | Set pressure and flow rate |

## Project Structure

```
voice-ui-approach/
├── main.py                  # FastAPI backend (speech, agent, config API)
├── or_lights_mcp.py         # OR Lights MCP server (Streamable HTTP transport)
├── or_device_api.py         # OR Device API server (insufflator control)
├── devices_openapi.json     # OpenAPI spec for Foundry tool registration
├── index.html               # Web interface (chat + OR light panel + device panel)
├── app.js                   # Frontend JavaScript (voice + light + device visualization)
├── start.sh                 # Auto-start script for all 5 services
├── requirements.txt         # Python dependencies
├── AGENT_SYSTEM_PROMPT.md   # Foundry agent system prompt
├── .env.example             # Environment template
├── .or_lights_state.json    # Light state (auto-generated, gitignored)
├── .or_devices_state.json   # Device state (auto-generated, gitignored)
├── deploy.sh                # Azure Container Apps deployment script
├── Dockerfile               # Container image definition
├── .dockerignore             # Files excluded from Docker build
├── infra/
│   └── main.bicep           # Azure infrastructure (Bicep)
├── architecture.drawio       # Architecture diagram (draw.io)
├── utils/                   # Utility scripts
│   ├── check_old_api_agents.py
│   └── list_agents.py
└── README.md                # This file
```

## Configuration Details

### Agent Reference
Agents are referenced by **name** (not ID) in the new Foundry API:
```python
extra_body={"agent_reference": {"name": "playwright-agent", "type": "agent_reference"}}
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
- Check agent has both MCP servers configured (Playwright + OR Lights)

### Lights not updating in UI
- Verify OR Lights MCP server is running on port 8932
- Check `.or_lights_state.json` exists and is being updated
- Open browser console and check for polling errors on `http://localhost:8932/api/state`

### Browser doesn't open
- Verify Playwright MCP server is running on port 8931
- Check dev tunnel is exposing port 8931
- Ensure agent has Playwright MCP server configured in Foundry

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

## Azure Container Apps Deployment

The backend can be deployed to Azure Container Apps for lower latency and reliable hosting. The local MCP servers still run on your machine (connected via dev tunnel).

### Prerequisites

- Azure CLI logged in (`az login`)
- `.env` file in the repo root with `PROJECT_ENDPOINT`, `SPEECH_KEY`, `SPEECH_REGION`, `AGENT_ID`

### One-Command Deploy

```bash
./deploy.sh
```

This deploys all infrastructure (ACR, Container Apps Environment, Container App) via Bicep, builds the Docker image, and grants the managed identity the required role.

Options:
```bash
./deploy.sh --resource-group myRg    # Custom resource group (default: rg-or-assistant)
./deploy.sh --location westeurope    # Custom location (default: swedencentral)
./deploy.sh --app-name myapp         # Custom app name prefix (default: or-assistant)
```

### What Gets Deployed

| Resource | Purpose |
|----------|---------|
| Azure Container Registry | Stores the backend Docker image |
| Log Analytics Workspace | Container App logging |
| Container Apps Environment | Hosting environment |
| Container App | FastAPI backend with managed identity |

The container app gets a system-assigned managed identity with the **Cognitive Services User** role on your AI Services resource.

### Running with Cloud Backend

After deployment, start only the local MCP servers:

```bash
./start.sh --local-only
```

Then open the container app URL shown in the deployment output.

### Redeploying

Run `./deploy.sh` again — it will build a new image and update the container app. Existing infrastructure is reused.

### Infrastructure Files

```
voice-ui-approach/
├── deploy.sh              # Deployment script
├── Dockerfile             # Container image definition
├── .dockerignore          # Files excluded from image
└── infra/
    └── main.bicep         # Azure infrastructure (Bicep)
```

## License

MIT

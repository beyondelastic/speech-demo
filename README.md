# Speech Demo - Voice-Controlled OR Assistant & Browser Automation

Three different approaches for voice-controlled automation in operating rooms.

## Overview

This repository demonstrates three architectures for hands-free voice control, progressing from cloud-based agents to ultra-low-latency direct API calls:

### 1. **Local API Approach** (`local-api-approach/`)
A lightweight FastAPI server that exposes browser control capabilities to a cloud-based Microsoft Foundry voice agent via HTTP endpoints.

**Architecture:**
```
User Voice → Foundry Voice Agent → HTTP API Call → Local FastAPI → Browser Opens
```

**Key Features:**
- Simple REST API with `/api/open-browser` endpoint
- Designed for cloud-based Foundry voice agents
- Requires public endpoint (e.g., via dev tunnel)
- Minimal local dependencies

### 2. **Voice UI Approach** (`voice-ui-approach/`) ⭐ Recommended
A complete web-based voice interface for operating rooms — surgeons and medical staff can control OR lighting, medical devices, and browse the web hands-free via voice commands.

**Architecture:**
```
Browser UI → Azure Speech (STT) → Local Backend → Foundry Agent ─┬→ OR Lights MCP    → Lighting Control
           ← Azure Speech (TTS) ←                                ├→ OR Device API    → Insufflator Control
                                                                  └→ Playwright MCP   → Browser Control
```

**Key Features:**
- Hands-free OR lighting control with scene presets (surgery, laparoscopy, etc.)
- Medical device control (CO2 insufflator) with live pressure/flow gauges
- Live OR visualization panels showing light and device states in real time
- Rich web interface for voice interaction
- Real-time speech-to-text and text-to-speech
- Full browser automation via Playwright MCP
- Automatic MCP tool execution (no approval round-trips)
- Multi-language support (English/German)

### 3. **Voice Control** (`voice-control/`) ⚡ Fastest
Ultra-low-latency voice control for OR lights and endoscope video recording. Bypasses the Foundry Agent framework entirely — direct Azure OpenAI function calling for **595–765ms** end-to-end latency.

**Architecture:**
```
Browser UI → WebSocket (PCM audio) → FastAPI Backend ─┬→ Azure Speech (streaming STT, 300ms silence)
           ← Text + pre-cached TTS ←                  ├→ Azure OpenAI (GPT-4.1-nano, function calling)
                                                       └→ REST dispatch → OR Lights API / Video API
```

**Key Features:**
- Direct Azure OpenAI function calling (no Foundry Agent / MCP overhead)
- GPT-4.1-nano for minimal LLM latency (~200–350ms)
- Fast path: light-only commands skip 2nd LLM round-trip (~950ms total)
- Wake word activation ("Computer")
- Recording guard: code-level safety net strips spurious recording tool calls
- 5 OR lights, 6 scenes, 4 color presets (light_blue, light_green, red, white)
- Endoscope video recording & snapshots
- Pre-cached TTS for video responses (~5ms vs ~300ms synthesis)
- Bilingual (English / German)

## Quick Start

### Local API Approach
```bash
cd local-api-approach
pip install -r requirements.txt
python main.py
# Expose via dev tunnel for Foundry agent access
```

### Voice UI Approach
```bash
cd voice-ui-approach
pip install -r requirements.txt
# Configure .env with Foundry project details
./start.sh
# Opens http://localhost:8000 — starts all 5 services automatically
```

### Voice Control (Recommended)
```bash
cd voice-control
pip install -r requirements.txt
# Configure .env with Azure OpenAI + Speech credentials
./start.sh
# Starts OR Lights API, Video API, Dev Tunnel, and FastAPI on http://localhost:8000
```

## Project Structure

```
speech-demo/
├── local-api-approach/          # REST API for cloud voice agents
│   ├── main.py                  # FastAPI server with browser control
│   ├── openapi.json             # API specification for Foundry
│   ├── requirements.txt         # Minimal dependencies
│   └── README.md                # Detailed setup guide
│
├── voice-ui-approach/           # OR voice assistant (recommended)
│   ├── main.py                  # FastAPI backend (speech, agent, config)
│   ├── or_lights_mcp.py         # OR Lights MCP server (Streamable HTTP)
│   ├── or_device_api.py         # OR Device API server (insufflator)
│   ├── devices_openapi.json     # OpenAPI spec for Foundry tool
│   ├── index.html               # Web UI (chat + light panel + device panel)
│   ├── app.js                   # Frontend logic
│   ├── start.sh                 # Auto-start all 5 services
│   ├── deploy.sh                # Azure Container Apps deployment script
│   ├── Dockerfile               # Container image definition
│   ├── .dockerignore            # Files excluded from Docker build
│   ├── infra/
│   │   └── main.bicep           # Azure infrastructure (Bicep)
│   ├── architecture.drawio      # Architecture diagram (draw.io)
│   ├── AGENT_SYSTEM_PROMPT.md   # Foundry agent system prompt
│   ├── requirements.txt         # Full dependencies
│   └── README.md                # Detailed documentation
│
├── voice-control/               # Ultra-low-latency OR assistant (fastest)
│   ├── main.py                  # FastAPI backend (WebSocket STT, OpenAI function calling)
│   ├── or_lights_api.py         # OR Lights REST API (port 8932)
│   ├── video_api.py             # Endoscope Video REST API (port 8933)
│   ├── index.html               # Web UI (voice chat + light panel + video panel)
│   ├── app.js                   # Frontend (audio pipeline, WebSocket, polling)
│   ├── SYSTEM_PROMPT.md         # LLM system prompt (bilingual)
│   ├── start.sh                 # Auto-start all services + dev tunnel
│   ├── architecture.drawio      # Architecture diagram (draw.io)
│   ├── fine-tuning/             # GPT-4.1-nano fine-tuning dataset (198 examples)
│   ├── .env.example             # Environment variable template
│   ├── requirements.txt         # Dependencies
│   └── README.md                # Detailed documentation
│
├── docs/                        # Future improvement plans
└── README.md                    # This file
```

## Comparison

| Feature | Local API Approach | Voice UI Approach | Voice Control |
|---------|-------------------|-------------------|---------------|
| **Voice Processing** | Cloud (Foundry) | Local (Azure Speech) | Local (Azure Speech) |
| **Agent / LLM** | Cloud (Foundry Agent) | Cloud (Foundry Agent) | Direct Azure OpenAI |
| **Model** | — | GPT-4.1 | GPT-4.1-nano |
| **Browser Control** | Direct (webbrowser) | MCP Server (Playwright) | — |
| **Lighting Control** | — | MCP Server (OR Lights) | REST API (direct) |
| **Video Recording** | — | — | REST API (direct) |
| **Device Control** | — | OpenAPI Tool (Insufflator) | — |
| **UI** | None (API only) | Web-based (chat + OR panels) | Web-based (chat + light + video) |
| **Complexity** | Low | Medium | Low |
| **Latency** | Cloud-dependent | ~1.5–3s | **~595–765ms** |
| **Setup** | FastAPI + tunnel | FastAPI + Azure + MCP + tunnel | FastAPI + Azure OpenAI + tunnel |
| **Use Case** | Simple URL opening | OR lighting + browser automation | **OR lighting + video (fastest)** |

## Requirements

**Common:**
- Python 3.10+
- Azure subscription
- Dev tunnel (`devtunnel` CLI)
- Azure CLI (`az login`)

**Voice UI Approach** (additional):
- Foundry project with configured agent
- MCP servers (Playwright + OR Lights)
- Node.js and npm (for Playwright MCP server)
- ffmpeg (for audio processing)

**Voice Control** (additional):
- Azure OpenAI resource with GPT-4.1-nano deployed
- Azure Speech Service

## Documentation

- [voice-ui-approach/README.md](voice-ui-approach/README.md) — Detailed setup, configuration, and troubleshooting
- [voice-control/README.md](voice-control/README.md) — Ultra-low-latency voice control setup and features

## Example Usage

### OR Lighting Control
**You**: "Switch to laparoscopy mode"
**Agent**: *Activates laparoscopy scene preset* "Switched to laparoscopy mode. Surgical lights off, monitors at full brightness."

**You**: "Dim the surgical light to 50 percent"
**Agent**: *Adjusts light* "Surgical light dimmed to 50 percent."

### Browser Automation
**You**: "Open my browser and navigate to Google"
**Agent**: *Opens browser, navigates to google.com* "I've opened your browser and navigated to Google.com."

**You**: "Search for Python tutorials"
**Agent**: *Types in search box, presses enter* "I've searched for Python tutorials."

All MCP tool calls are automatically approved — no manual intervention needed.

## Architecture

**Voice UI Approach:**
- **Frontend**: Vanilla JS with MediaRecorder API + OR Light visualization panel
- **Backend**: FastAPI with Azure AI SDK
- **Speech**: Azure Speech Services (STT/TTS)
- **Agent**: Microsoft Foundry with GPT-4o
- **Tools**: Playwright MCP (browser) + OR Lights MCP (lighting)
- **Transport**: SSE for MCP, WebSocket for audio streaming

**Voice Control:**
- **Frontend**: Vanilla JS with WebSocket audio pipeline + OR Light + Video panels
- **Backend**: FastAPI with direct Azure OpenAI (AsyncAzureOpenAI)
- **Speech**: Azure Speech SDK (streaming STT, 300ms silence timeout)
- **LLM**: GPT-4.1-nano with function calling (no agent framework)
- **Tools**: 7 tools (get_lights, set_light, set_zone, activate_scene, start/stop_recording, take_snapshot)
- **Transport**: WebSocket for audio, REST for device APIs

## License

MIT

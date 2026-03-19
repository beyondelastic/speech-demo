# Speech Demo - Voice-Controlled OR Assistant & Browser Automation

Two different approaches for voice-controlled automation using Microsoft Foundry AI Agents.

## Overview

This repository demonstrates two different architectures for hands-free voice control using Microsoft Foundry AI Agents:

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
├── docs/                        # Future improvement plans
└── README.md                    # This file
```

## Comparison

| Feature | Local API Approach | Voice UI Approach |
|---------|-------------------|-------------------|
| **Voice Processing** | Cloud (Foundry) | Local (Azure Speech) |
| **Agent Location** | Cloud (Foundry) | Cloud (Foundry) |
| **Browser Control** | Direct (webbrowser) | MCP Server (Playwright) |
| **Lighting Control** | — | MCP Server (OR Lights) |
| **Device Control** | — | OpenAPI Tool (Insufflator) |
| **UI** | None (API only) | Web-based (chat + OR panels) |
| **Complexity** | Low | Medium |
| **Setup** | FastAPI + tunnel | FastAPI + Azure + MCP + tunnel |
| **Use Case** | Simple URL opening | OR lighting + browser automation |

## Requirements

- Python 3.10+
- Azure subscription with Foundry project
- Agent configured with MCP servers (Playwright + OR Lights)
- Node.js and npm (for Playwright MCP server)
- ffmpeg (for audio processing)
- Dev tunnel (for exposing MCP servers to cloud)
- Azure CLI (`az login`)

## Documentation

See [voice-ui-approach/README.md](voice-ui-approach/README.md) for detailed setup, configuration, and troubleshooting.

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

- **Frontend**: Vanilla JS with MediaRecorder API + OR Light visualization panel
- **Backend**: FastAPI with Azure AI SDK
- **Speech**: Azure Speech Services (STT/TTS)
- **Agent**: Microsoft Foundry with GPT-4o
- **Tools**: Playwright MCP (browser) + OR Lights MCP (lighting)
- **Transport**: SSE for MCP, WebSocket for audio streaming

## License

MIT

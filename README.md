# Speech Demo - Voice-Controlled Browser Automation

Two different approaches for voice-controlled browser automation using Microsoft Foundry AI Agents.

## Overview

This repository demonstrates two different architectures for controlling a local browser through voice commands using Microsoft Foundry AI Agents:

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

### 2. **Voice UI Approach** (`voice-ui-approach/`)
A complete web-based voice interface with local speech processing, agent interaction, and automatic MCP tool approval for browser control.

**Architecture:**
```
Browser UI → Azure Speech (STT) → Local Backend → Foundry Agent → Playwright MCP → Browser Control
           ← Azure Speech (TTS) ←
```

**Key Features:**
- Rich web interface for voice interaction
- Real-time speech-to-text and text-to-speech
- Automatic MCP tool approval for seamless automation
- Conversation history and context management
- WebSocket support for streaming audio

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
python main.py
# Open http://localhost:8000 and start talking
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
├── voice-ui-approach/           # Complete voice interface solution
│   ├── main.py                  # FastAPI backend with speech & agent
│   ├── index.html               # Voice interface UI
│   ├── app.js                   # Frontend logic
│   ├── requirements.txt         # Full dependencies
│   └── README.md                # Detailed documentation
│
└── README.md                    # This file
```

## Comparison

| Feature | Local API Approach | Voice UI Approach |
|---------|-------------------|-------------------|
| **Voice Processing** | Cloud (Foundry) | Local (Azure Speech) |
| **Agent Location** | Cloud (Foundry) | Cloud (Foundry) |
| **Browser Control** | Direct (webbrowser) | MCP Server (Playwright) |
| **UI** | None (API only) | Web-based interface |
| **Complexity** | Low | Medium |
| **Setup** | FastAPI + tunnel | FastAPI + Azure + Foundry |
| **Use Case** | Simple URL opening | Complex browser automation |

## Requirements

- Python 3.8+
- Azure subscription with Foundry project
- Agent configured with Playwright MCP server
- ffmpeg (for audio processing)
- Azure CLI (`az login`)

## Documentation

See [voice-ui-approach/README.md](voice-ui-approach/README.md) for detailed setup, configuration, and troubleshooting.

## Example Usage

**You**: "Open my browser and navigate to Google"
**Agent**: *Opens browser, navigates to google.com* "I've opened your browser and navigated to Google.com."

**You**: "Search for Python tutorials"
**Agent**: *Types in search box, presses enter* "I've searched for Python tutorials."

**You**: "Click the first result"
**Agent**: *Clicks link* "I've clicked the first result."

All MCP tool calls are automatically approved - no manual intervention needed!

## Architecture

- **Frontend**: Vanilla JS with MediaRecorder API
- **Backend**: FastAPI with Azure AI SDK
- **Speech**: Azure Speech Services (STT/TTS)
- **Agent**: Microsoft Foundry with Conversations API
- **Tools**: Playwright MCP server (browser automation)

## License

MIT

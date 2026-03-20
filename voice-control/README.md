# Voice Control — Ultra-Low-Latency OR Assistant

Voice-controlled operating room lights + endoscope video recording. Target latency: **500–1000ms** from end-of-speech to action complete.

## Architecture

```
Browser (index.html + app.js)
├── Voice Chat Panel
├── OR Light Panel
└── Video Recording Panel
    │  WebSocket (binary PCM + JSON)
    ↓
FastAPI Backend (main.py)
├── STT: Azure Speech SDK (streaming, 300ms silence timeout)
├── LLM: Azure OpenAI direct (GPT-4.1-nano, function calling)
│   └── No Foundry Agent, no MCP, no approval loops
├── TTS: Pre-cached audio blobs for video responses
└── Tool Dispatch: httpx → REST APIs
    │  Dev Tunnel
    ↓
On-Premises
├── OR Lights API :8932 (or_lights_api.py)
└── Video Recording API :8933 (video_api.py)
```

## Key Difference from voice-ui-approach

| Aspect | voice-ui-approach | voice-control |
|--------|-------------------|---------------|
| LLM | Foundry Agent + MCP | Direct Azure OpenAI function calling |
| Tool transport | MCP over SSE | JSON function calls → REST dispatch |
| Overhead | ~400-800ms agent framework | ~0ms (direct API call) |
| TTS for lights | Full synthesis | Skipped (text-only) |
| TTS for video | Runtime synthesis | Pre-cached audio blobs |
| Silence timeout | 500ms | 300ms |
| Model | GPT-4.1 | GPT-4.1-nano |

## Latency Budget

| Step | Time | Notes |
|------|------|-------|
| Silence timeout | 300ms | Configurable via SILENCE_TIMEOUT_MS |
| STT finalization | ~50ms | SDK processing |
| Azure OpenAI (nano) | ~200-350ms | Function calling, same region |
| REST dispatch | ~40-60ms | Via dev tunnel |
| Pre-cached TTS | ~5ms | Binary blob from memory |
| **Total** | **~595-765ms** | ✅ Within target |

## Setup

```bash
# Install dependencies (uses shared venv)
cd voice-control
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example ../.env  # .env lives in repo root

# Start all services
./start.sh

# Or start without local FastAPI (when backend runs in Azure)
./start.sh --local-only
```

## Files

| File / Dir | Purpose |
|------------|---------|
| main.py | FastAPI backend — WebSocket STT, Azure OpenAI function calling, TTS |
| or_lights_api.py | REST API simulating OR lights (port 8932) |
| video_api.py | REST API simulating endoscope video recorder (port 8933) |
| index.html | Web UI — voice chat + light panel + video panel |
| app.js | Frontend — audio pipeline, WebSocket, panel polling |
| SYSTEM_PROMPT.md | LLM system prompt (bilingual, ultra-concise) |
| start.sh | Launch script — starts all 4 services |
| .env.example | Environment variable template |
| fine-tuning/ | GPT-4.1-nano fine-tuning dataset (198 examples, JSONL) |

## Wake Word

Say **"Computer"** to activate the assistant (text-based detection on STT output). Configurable via `WAKE_WORD` and `WAKE_WORD_ENABLED` env vars.

## Voice Commands

**English:**
- "Surgery mode" / "Laparoscopy mode" / "Prep mode"
- "Dim lights to 50%" / "All lights off" / "Brighter"
- "Set lights to blue" / "Make it light green" (colors: light_blue, light_green, red, white)
- "Start recording" / "Stop recording" / "Take a snapshot"
- "Prepare for laparoscopy" (lights + recording)

**German:**
- "Chirurgiemodus" / "Laparoskopie" / "Standby"
- "Lichter auf 50%" / "Alle Lichter aus" / "Heller"
- "Lichter auf blau" / "Hellgrün bitte" (Farben: light_blue, light_green, red, white)
- "Aufnahme starten" / "Aufnahme stoppen" / "Foto machen"
- "Laparoskopie vorbereiten" (Lichter + Aufnahme)

## Recording Guard

A code-level safety net prevents the LLM from spuriously calling `start_recording` / `stop_recording` when the user didn't mention recording. The guard checks user text for explicit keywords (e.g. "recording", "aufnahme", "video", "laparoscopy") and strips unwanted recording tool calls. Zero latency overhead.

## Test Endpoint

```bash
curl -s -X POST http://localhost:8000/api/test-chat \
  -H "Content-Type: application/json" \
  -d '{"text":"Dim lights to 40 percent"}'
```

Returns JSON with `text`, `tools`, `llm_ms`, and `total_ms` — useful for testing without voice.

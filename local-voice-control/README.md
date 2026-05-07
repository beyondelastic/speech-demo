# Local Voice Control — OR Assistant

Voice-controlled operating room assistant running locally with:
- **Foundry Local** (Phi-4-mini) for LLM / tool calling
- **Azure Speech containers** (connected mode) for STT and TTS
- **FastAPI** backend with WebSocket audio streaming

> All inference runs on-device. Internet is only required for Azure Speech billing connectivity.

## Prerequisites

- Python 3.12+ with venv at `/home/aullah/git/speech-demo/.venv`
- Docker (for speech containers)
- Azure Speech resource (S0 tier) with API key

## Startup Steps

### 1. Activate the virtual environment

```bash
cd /home/aullah/git/speech-demo/local-voice-control
source /home/aullah/git/speech-demo/.venv/bin/activate
```

### 2. Start Azure Speech containers

```bash
docker compose up -d
```

This starts:
- **STT** container on port `5000`
- **TTS** container on port `5001`

Verify with `docker ps` — both containers should be running.

### 3. Start the LLM server (Foundry Local)

```bash
python llm_server.py --port 5273
```

Wait until you see:
```
[LLM] OpenAI-compatible API running at: http://127.0.0.1:5273
```

> Keep this terminal open — the LLM server must remain running.

### 4. Start the device APIs

In a new terminal (with venv activated):

```bash
python or_lights_api.py --port 8932 &
python video_api.py --port 8933 &
```

### 5. Start the main application

In a new terminal (with venv activated):

```bash
python main.py
```

Wait until you see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 6. Open the UI

Navigate to **http://localhost:8000** in your browser.

Click the microphone button and say "Computer, turn off the lights" (or any supported command).

## Service Summary

| Service | Port | Purpose |
|---------|------|---------|
| STT container | 5000 | Speech-to-text |
| TTS container | 5001 | Text-to-speech |
| Foundry Local LLM | 5273 | LLM inference (Phi-4-mini, CPU) |
| Lights API | 8932 | Simulated OR lights |
| Video API | 8933 | Simulated video system |
| Main app (FastAPI) | 8000 | Web UI + WebSocket pipeline |

## Configuration

All settings are in `.env`. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SPEECH_KEY` | — | Azure Speech resource API key |
| `SPEECH_REGION` | `westeurope` | Azure region |
| `SPEECH_CONTAINER_HOST` | `ws://localhost:5000` | STT container endpoint |
| `TTS_CONTAINER_HOST` | `ws://localhost:5001` | TTS container endpoint |
| `FOUNDRY_LOCAL_ENDPOINT` | `http://localhost:5273/v1` | LLM server URL |
| `MODEL_NAME` | `Phi-4-mini-instruct-generic-cpu:5` | Model ID |
| `WAKE_WORD` | `computer` | Wake word to activate processing |
| `WAKE_WORD_ENABLED` | `true` | Enable/disable wake word |
| `SILENCE_TIMEOUT_MS` | `300` | Silence before processing speech |

## Notes

- **Performance**: On CPU, LLM responses take ~25 seconds. With a CUDA GPU, use a GPU model variant for much faster inference.
- **Wake word**: Say "Computer" before your command. The wake word is detected from STT partial results (text-based, not keyword spotting).
- **TTS feedback**: Audio responses are generated only for certain actions (recording start/stop, snapshots). Simple light switches respond with text only.
- **First request**: The first LLM call after startup may be slower due to model warmup.

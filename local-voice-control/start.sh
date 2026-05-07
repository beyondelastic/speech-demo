#!/bin/bash
# =============================================================================
# Start Script for Local Voice Control
# Starts: Speech Containers, LLM Server, OR Lights API, Video API, FastAPI
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/.venv"
LIGHTS_PORT=8932
VIDEO_PORT=8933
LLM_PORT=5273
FASTAPI_PORT=8000

PIDS=()

cleanup() {
    echo ""
    echo -e "${YELLOW}[Shutdown] Stopping all services...${NC}"
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
        fi
    done
    for i in 1 2 3; do
        all_dead=true
        for pid in "${PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then all_dead=false; break; fi
        done
        if $all_dead; then break; fi
        sleep 1
    done
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
        fi
    done
    echo -e "${GREEN}[Shutdown] All services stopped.${NC}"
    echo -e "${YELLOW}[Note] Docker speech containers are still running. Stop with: docker compose down${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# --- Preflight ---
echo -e "${CYAN}[Preflight] Checking prerequisites...${NC}"

# Activate venv
if [[ -f "$VENV_DIR/bin/activate" ]]; then
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}  ✓ Virtual environment activated${NC}"
else
    echo -e "${RED}[Error] Virtual environment not found at $VENV_DIR${NC}"
    echo -e "${RED}        Create with: python3 -m venv $VENV_DIR && pip install -r requirements.txt${NC}"
    exit 1
fi

PYTHON_CMD="python"

# Check Docker
if ! command -v docker &>/dev/null; then
    echo -e "${RED}[Error] Docker not found. Required for speech containers.${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ Docker available${NC}"

# Check .env
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
    echo -e "${RED}[Error] No .env file found. Copy .env.example → .env and configure.${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ .env file found${NC}"

echo -e "${GREEN}[Preflight] OK.${NC}"
echo ""

# --- 1. Speech Containers (Docker) ---
echo -e "${CYAN}[1/5] Checking Azure Speech containers...${NC}"
cd "$SCRIPT_DIR"

STT_RUNNING=$(docker ps --filter "ancestor=mcr.microsoft.com/azure-cognitive-services/speechservices/speech-to-text" --format "{{.ID}}" 2>/dev/null)
TTS_RUNNING=$(docker ps --filter "ancestor=mcr.microsoft.com/azure-cognitive-services/speechservices/neural-text-to-speech" --format "{{.ID}}" 2>/dev/null)

if [[ -n "$STT_RUNNING" && -n "$TTS_RUNNING" ]]; then
    echo -e "${GREEN}[1/5] Speech containers already running.${NC}"
else
    echo -e "${YELLOW}[1/5] Starting speech containers via docker compose...${NC}"
    docker compose up -d
    sleep 5
    echo -e "${GREEN}[1/5] Speech containers started (STT :5000, TTS :5001).${NC}"
fi

# --- 2. LLM Server (Foundry Local) ---
echo -e "${CYAN}[2/5] Starting Foundry Local LLM server on port ${LLM_PORT}...${NC}"
cd "$SCRIPT_DIR"

# Check if already running
if curl -s "http://127.0.0.1:${LLM_PORT}/v1/models" >/dev/null 2>&1; then
    echo -e "${GREEN}[2/5] LLM server already running on port ${LLM_PORT}.${NC}"
else
    "$PYTHON_CMD" llm_server.py --port "$LLM_PORT" &
    PIDS+=($!)

    # Wait for model to load (can take 10-30s on first run)
    echo -e "${YELLOW}      Waiting for model to load (this may take a moment)...${NC}"
    for i in $(seq 1 60); do
        if curl -s "http://127.0.0.1:${LLM_PORT}/v1/models" >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done

    if ! curl -s "http://127.0.0.1:${LLM_PORT}/v1/models" >/dev/null 2>&1; then
        echo -e "${RED}[Error] LLM server failed to start within 120s.${NC}"
        cleanup
    fi
    echo -e "${GREEN}[2/5] LLM server running (PID ${PIDS[-1]}).${NC}"
fi

# --- 3. OR Lights API ---
echo -e "${CYAN}[3/5] Starting OR Lights API on port ${LIGHTS_PORT}...${NC}"
cd "$SCRIPT_DIR"
"$PYTHON_CMD" or_lights_api.py --port "$LIGHTS_PORT" &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] OR Lights API failed to start.${NC}"
    cleanup
fi
echo -e "${GREEN}[3/5] OR Lights API running (PID ${PIDS[-1]}).${NC}"

# --- 4. Video Recording API ---
echo -e "${CYAN}[4/5] Starting Video API on port ${VIDEO_PORT}...${NC}"
cd "$SCRIPT_DIR"
"$PYTHON_CMD" video_api.py --port "$VIDEO_PORT" &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] Video API failed to start.${NC}"
    cleanup
fi
echo -e "${GREEN}[4/5] Video API running (PID ${PIDS[-1]}).${NC}"

# --- 5. FastAPI Backend ---
echo -e "${CYAN}[5/5] Starting FastAPI backend on port ${FASTAPI_PORT}...${NC}"
cd "$SCRIPT_DIR"
"$PYTHON_CMD" main.py &
PIDS+=($!)
sleep 3

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] FastAPI backend failed to start.${NC}"
    cleanup
fi
echo -e "${GREEN}[5/5] FastAPI backend running (PID ${PIDS[-1]}).${NC}"

# --- Summary ---
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Local Voice Control — All Services Running${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "  Web UI:       ${CYAN}http://localhost:${FASTAPI_PORT}${NC}"
echo -e "  Lights API:   ${CYAN}http://localhost:${LIGHTS_PORT}${NC}"
echo -e "  Video API:    ${CYAN}http://localhost:${VIDEO_PORT}${NC}"
echo -e "  LLM Server:   ${CYAN}http://localhost:${LLM_PORT}${NC} (Phi-4-mini)"
echo -e "  STT:          ${CYAN}http://localhost:5000${NC} (Speech container)"
echo -e "  TTS:          ${CYAN}http://localhost:5001${NC} (Speech container)"
echo -e ""
echo -e "  ${YELLOW}Press Ctrl+C to stop all services.${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"

# Wait for all
wait

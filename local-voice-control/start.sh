#!/bin/bash
# =============================================================================
# Start Script for Local Voice Control
# Starts: OR Lights API, Video API, Foundry Local LLM, and FastAPI Backend
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIGHTS_PORT=8932
VIDEO_PORT=8933
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
    exit 0
}

trap cleanup SIGINT SIGTERM

# --- Preflight ---
echo -e "${CYAN}[Preflight] Checking prerequisites...${NC}"

PYTHON_CMD=$(command -v python3 || command -v python)
if [[ -z "$PYTHON_CMD" ]]; then
    echo -e "${RED}[Error] Python not found.${NC}"
    exit 1
fi

# Check for .env
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
    echo -e "${YELLOW}[Warning] No .env file found. Copy .env.example → .env and configure.${NC}"
fi

echo -e "${GREEN}[Preflight] OK.${NC}"
echo ""

# --- 1. OR Lights API ---
echo -e "${CYAN}[1/4] Starting OR Lights API on port ${LIGHTS_PORT}...${NC}"
cd "$SCRIPT_DIR"
"$PYTHON_CMD" or_lights_api.py --port "$LIGHTS_PORT" &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] OR Lights API failed to start.${NC}"
    cleanup
fi
echo -e "${GREEN}[1/4] OR Lights API running (PID ${PIDS[-1]}).${NC}"

# --- 2. Video Recording API ---
echo -e "${CYAN}[2/4] Starting Video API on port ${VIDEO_PORT}...${NC}"
cd "$SCRIPT_DIR"
"$PYTHON_CMD" video_api.py --port "$VIDEO_PORT" &
PIDS+=($!)
sleep 1

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] Video API failed to start.${NC}"
    cleanup
fi
echo -e "${GREEN}[2/4] Video API running (PID ${PIDS[-1]}).${NC}"

# --- 3. Foundry Local LLM Server ---
echo -e "${CYAN}[3/4] Starting Foundry Local LLM server...${NC}"
echo -e "${YELLOW}      NOTE: If foundry CLI is not installed, start manually:${NC}"
echo -e "${YELLOW}        foundry model run phi-4-mini-instruct${NC}"
echo -e "${YELLOW}      Or use Python SDK web server mode (see README).${NC}"

if command -v foundry &>/dev/null; then
    foundry model run phi-4-mini-instruct &
    PIDS+=($!)
    sleep 5
    echo -e "${GREEN}[3/4] Foundry Local LLM server started (PID ${PIDS[-1]}).${NC}"
else
    echo -e "${YELLOW}[3/4] Foundry CLI not found. Ensure LLM server is running at FOUNDRY_LOCAL_ENDPOINT.${NC}"
    echo -e "${YELLOW}      On Linux without CLI, use: python -c 'from foundry_local_sdk import ...' (see README)${NC}"
fi

# --- 4. FastAPI Backend ---
echo -e "${CYAN}[4/4] Starting FastAPI backend on port ${FASTAPI_PORT}...${NC}"
cd "$SCRIPT_DIR"
"$PYTHON_CMD" -m uvicorn main:app --host 0.0.0.0 --port "$FASTAPI_PORT" &
PIDS+=($!)
sleep 2

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] FastAPI backend failed to start.${NC}"
    cleanup
fi
echo -e "${GREEN}[4/4] FastAPI backend running (PID ${PIDS[-1]}).${NC}"

# --- Summary ---
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Local Voice Control — All Services Running${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "  Web UI:       ${CYAN}http://localhost:${FASTAPI_PORT}${NC}"
echo -e "  Lights API:   ${CYAN}http://localhost:${LIGHTS_PORT}${NC}"
echo -e "  Video API:    ${CYAN}http://localhost:${VIDEO_PORT}${NC}"
echo -e "  LLM:          ${CYAN}Foundry Local (phi-4-mini-instruct)${NC}"
echo -e "  Speech:       ${CYAN}Azure Speech Container (docker-compose up)${NC}"
echo -e ""
echo -e "  ${YELLOW}Press Ctrl+C to stop all services.${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"

# Wait for all
wait

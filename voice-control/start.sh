#!/bin/bash
# =============================================================================
# Start Script for Voice Control Demo (Local Development)
# Starts: OR Lights API, Video API, Dev Tunnel, and FastAPI Backend
# =============================================================================

set -e

export PATH="$HOME/bin:$PATH"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUNNEL_NAME="voice-control-tunnel"
LIGHTS_PORT=8932
VIDEO_PORT=8933
FASTAPI_PORT=8000

LOCAL_ONLY=false
if [[ "$1" == "--local-only" ]]; then
    LOCAL_ONLY=true
fi

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

if ! command -v devtunnel &>/dev/null; then
    echo -e "${RED}[Error] devtunnel not found. Install: curl -sL https://aka.ms/DevTunnelCliInstall | bash${NC}"
    exit 1
fi

PYTHON_CMD=$(command -v python3 || command -v python)
if [[ -z "$PYTHON_CMD" ]]; then
    echo -e "${RED}[Error] Python not found.${NC}"
    exit 1
fi

echo -e "${GREEN}[Preflight] OK.${NC}"

# --- 1. OR Lights API ---
echo -e "${CYAN}[1/4] Starting OR Lights API on port ${LIGHTS_PORT}...${NC}"
cd "$SCRIPT_DIR"
"$PYTHON_CMD" or_lights_api.py --port "$LIGHTS_PORT" &
PIDS+=($!)
sleep 2

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
sleep 2

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] Video API failed to start.${NC}"
    cleanup
fi
echo -e "${GREEN}[2/4] Video API running (PID ${PIDS[-1]}).${NC}"

# --- 3. Dev Tunnel ---
echo -e "${CYAN}[3/4] Setting up Dev Tunnel '${TUNNEL_NAME}'...${NC}"

if ! devtunnel show "$TUNNEL_NAME" &>/dev/null; then
    echo -e "${YELLOW}[3/4] Creating tunnel...${NC}"
    devtunnel create "$TUNNEL_NAME" -a
    devtunnel port create "$TUNNEL_NAME" -p "$LIGHTS_PORT"
    devtunnel port create "$TUNNEL_NAME" -p "$VIDEO_PORT"
fi

# Ensure ports are configured
devtunnel port create "$TUNNEL_NAME" -p "$LIGHTS_PORT" 2>/dev/null || true
devtunnel port create "$TUNNEL_NAME" -p "$VIDEO_PORT" 2>/dev/null || true

devtunnel host "$TUNNEL_NAME" &
PIDS+=($!)
sleep 3

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] Dev Tunnel failed to start.${NC}"
    cleanup
fi
echo -e "${GREEN}[3/4] Dev Tunnel running (PID ${PIDS[-1]}).${NC}"

# --- 4. FastAPI Backend ---
if [[ "$LOCAL_ONLY" == true ]]; then
    echo -e "${YELLOW}[4/4] Skipping FastAPI (--local-only, backend runs in Azure).${NC}"
else
    echo -e "${CYAN}[4/4] Starting FastAPI on port ${FASTAPI_PORT}...${NC}"
    cd "$SCRIPT_DIR"
    "$PYTHON_CMD" main.py &
    PIDS+=($!)
    sleep 2

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo -e "${RED}[Error] FastAPI failed to start.${NC}"
        cleanup
    fi
    echo -e "${GREEN}[4/4] FastAPI running (PID ${PIDS[-1]}).${NC}"
fi

# --- Ready ---
echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  All services started!${NC}"
echo -e "${GREEN}=============================================${NC}"
echo -e "  OR Lights API : http://localhost:${LIGHTS_PORT}"
echo -e "  Video API     : http://localhost:${VIDEO_PORT}"
echo -e "  Dev Tunnel    : devtunnel host ${TUNNEL_NAME}"
if [[ "$LOCAL_ONLY" == true ]]; then
    echo -e "  FastAPI       : ${YELLOW}Running in Azure${NC}"
else
    echo -e "  FastAPI UI    : http://localhost:${FASTAPI_PORT}"
fi
echo ""
echo -e "${YELLOW}  Press Ctrl+C to stop all services.${NC}"
echo -e "${GREEN}=============================================${NC}"

wait

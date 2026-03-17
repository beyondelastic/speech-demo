#!/bin/bash
# =============================================================================
# Start Script for Voice UI Demo (Local Development)
# Starts: OR Lights MCP, Playwright MCP, Dev Tunnel, and FastAPI Backend
#
# For cloud deployment, the FastAPI backend runs on Azure Container Apps.
# In that case, only run this script with --local-only to start MCP servers
# and dev tunnel (skip step 4).
# =============================================================================

set -e

# Ensure ~/bin is on PATH (devtunnel install location)
export PATH="$HOME/bin:$PATH"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUNNEL_NAME="playwright-mcp-tunnel"
MCP_PORT=8931
OR_LIGHTS_PORT=8932
FASTAPI_PORT=8000

# Parse --local-only flag (skip FastAPI when backend is in Azure)
LOCAL_ONLY=false
if [[ "$1" == "--local-only" ]]; then
    LOCAL_ONLY=true
fi

# Track background PIDs for cleanup
PIDS=()

cleanup() {
    echo ""
    echo -e "${YELLOW}[Shutdown] Stopping all services...${NC}"

    # Send SIGTERM first
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
        fi
    done

    # Wait up to 3 seconds for graceful shutdown
    for i in 1 2 3; do
        all_dead=true
        for pid in "${PIDS[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                all_dead=false
                break
            fi
        done
        if $all_dead; then break; fi
        sleep 1
    done

    # Force-kill anything still running
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${YELLOW}[Shutdown] Force-killing PID $pid...${NC}"
            kill -9 "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
        fi
    done

    echo -e "${GREEN}[Shutdown] All services stopped.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# --- Preflight checks ---
echo -e "${CYAN}[Preflight] Checking prerequisites...${NC}"

if ! command -v npx &>/dev/null; then
    echo -e "${RED}[Error] npx not found. Install Node.js first.${NC}"
    exit 1
fi

if ! command -v devtunnel &>/dev/null; then
    echo -e "${RED}[Error] devtunnel not found. Install with: curl -sL https://aka.ms/DevTunnelCliInstall | bash${NC}"
    exit 1
fi

if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
    echo -e "${RED}[Error] Python not found.${NC}"
    exit 1
fi

PYTHON_CMD=$(command -v python3 || command -v python)

echo -e "${GREEN}[Preflight] All prerequisites found.${NC}"

# --- Pre-install Chromium so the agent doesn't need to call browser_install ---
echo -e "${CYAN}[Preflight] Ensuring Chromium is installed...${NC}"
npx playwright install chromium 2>/dev/null
echo -e "${GREEN}[Preflight] Chromium ready.${NC}"

# --- 1. Start OR Lights MCP Server ---
echo -e "${CYAN}[1/4] Starting OR Lights MCP Server on port ${OR_LIGHTS_PORT}...${NC}"
cd "$SCRIPT_DIR"
"$PYTHON_CMD" or_lights_mcp.py --port "$OR_LIGHTS_PORT" &
PIDS+=($!)
sleep 2

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] OR Lights MCP Server failed to start.${NC}"
    cleanup
    exit 1
fi
echo -e "${GREEN}[1/4] OR Lights MCP Server running (PID ${PIDS[-1]}).${NC}"

# --- 2. Start Playwright MCP Server ---
echo -e "${CYAN}[2/4] Starting Playwright MCP Server on port ${MCP_PORT}...${NC}"
npx @playwright/mcp@latest --port "$MCP_PORT" --host 0.0.0.0 --browser chromium --shared-browser-context &
PIDS+=($!)
sleep 3

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] Playwright MCP Server failed to start.${NC}"
    cleanup
    exit 1
fi
echo -e "${GREEN}[2/4] Playwright MCP Server running (PID ${PIDS[-1]}).${NC}"

# --- 3. Start Dev Tunnel ---
echo -e "${CYAN}[3/4] Setting up Dev Tunnel '${TUNNEL_NAME}'...${NC}"

# Check if tunnel exists, create if not
if ! devtunnel show "$TUNNEL_NAME" &>/dev/null; then
    echo -e "${YELLOW}[3/4] Tunnel '${TUNNEL_NAME}' not found, creating...${NC}"
    devtunnel create "$TUNNEL_NAME" -a
    devtunnel port create "$TUNNEL_NAME" -p "$MCP_PORT"
    echo -e "${GREEN}[3/4] Tunnel created.${NC}"
else
    echo -e "${GREEN}[3/4] Tunnel '${TUNNEL_NAME}' already exists.${NC}"
fi

# Add OR lights port to tunnel if not already configured
devtunnel port create "$TUNNEL_NAME" -p "$OR_LIGHTS_PORT" 2>/dev/null || true

echo -e "${CYAN}[3/4] Starting Dev Tunnel...${NC}"
devtunnel host "$TUNNEL_NAME" &
PIDS+=($!)
sleep 3

if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
    echo -e "${RED}[Error] Dev Tunnel failed to start.${NC}"
    cleanup
    exit 1
fi
echo -e "${GREEN}[3/4] Dev Tunnel running (PID ${PIDS[-1]}).${NC}"

# --- 4. Start FastAPI Server (skip if --local-only) ---
if [[ "$LOCAL_ONLY" == true ]]; then
    echo -e "${YELLOW}[4/4] Skipping FastAPI server (--local-only mode, backend runs in Azure).${NC}"
    TOTAL_STEPS=3
else
    echo -e "${CYAN}[4/4] Starting FastAPI server on port ${FASTAPI_PORT}...${NC}"
    cd "$SCRIPT_DIR"
    "$PYTHON_CMD" main.py &
    PIDS+=($!)
    sleep 2

    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
        echo -e "${RED}[Error] FastAPI server failed to start.${NC}"
        cleanup
        exit 1
    fi
    echo -e "${GREEN}[4/4] FastAPI server running (PID ${PIDS[-1]}).${NC}"
    TOTAL_STEPS=4
fi

# --- Ready ---
echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}  All services started successfully!${NC}"
echo -e "${GREEN}=============================================${NC}"
echo -e "  OR Lights MCP   : http://localhost:${OR_LIGHTS_PORT}"
echo -e "  Playwright MCP  : http://localhost:${MCP_PORT}"
echo -e "  Dev Tunnel      : devtunnel host ${TUNNEL_NAME}"
if [[ "$LOCAL_ONLY" == true ]]; then
    echo -e "  FastAPI Backend  : ${YELLOW}Running in Azure Container Apps${NC}"
    echo -e ""
    echo -e "  ${CYAN}MCP servers and tunnel are running locally.${NC}"
    echo -e "  ${CYAN}Open the Azure Container Apps URL in your browser.${NC}"
else
    echo -e "  FastAPI UI      : http://localhost:${FASTAPI_PORT}"
fi
echo -e ""
echo -e "${YELLOW}  Press Ctrl+C to stop all services.${NC}"
echo -e "${GREEN}=============================================${NC}"

# Wait for all background processes
wait

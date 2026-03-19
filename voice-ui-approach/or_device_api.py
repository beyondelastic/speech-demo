"""
OR Medical Device API Server
A simple REST API simulating an on-premises medical device controller.
Exposes endpoints for controlling an insufflator (CO2 insufflation for laparoscopic surgery).
Designed to be registered as an OpenAPI tool in Microsoft Foundry.
"""

import argparse
import json
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

API_KEY = os.getenv("DEVICE_API_KEY", "or-device-key-2026")


def verify_api_key(
    x_api_key: Optional[str] = Header(default=None),
    api_key: Optional[str] = Query(default=None, alias="x-api-key"),
):
    key = x_api_key or api_key
    if not key or key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

app = FastAPI(
    title="OR Medical Device Controller",
    description="On-premises API for controlling operating room medical devices",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Device State ---

DEVICES = {
    "insufflator": {
        "name": "CO2 Insufflator",
        "model": "CO2 Insufflator",
        "power": False,
        "target_pressure_mmhg": 12,
        "flow_rate_lpm": 20,
        "actual_pressure_mmhg": 0,
        "status": "STANDBY",
        "description": "CO2 insufflation system for laparoscopic procedures",
    }
}

device_state: dict = {}
STATE_FILE = Path(__file__).parent / ".or_devices_state.json"


def reset_devices():
    """Reset devices to default state."""
    global device_state
    device_state = {k: dict(v) for k, v in DEVICES.items()}
    _persist_state()


def _persist_state():
    """Write current device state to file for frontend polling."""
    STATE_FILE.write_text(json.dumps(_get_public_state()))


def _get_public_state():
    """Get the public-facing state of all devices."""
    result = {}
    for dev_id, state in device_state.items():
        result[dev_id] = {
            "name": state["name"],
            "model": state["model"],
            "power": "ON" if state["power"] else "OFF",
            "target_pressure_mmhg": state["target_pressure_mmhg"],
            "flow_rate_lpm": state["flow_rate_lpm"],
            "actual_pressure_mmhg": state["actual_pressure_mmhg"],
            "status": state["status"],
        }
    return result


reset_devices()


# --- Pydantic Models ---

class PowerRequest(BaseModel):
    power: bool


class SettingsRequest(BaseModel):
    target_pressure_mmhg: Optional[int] = None
    flow_rate_lpm: Optional[int] = None


# --- API Endpoints ---

@app.get("/api/devices/state")
async def get_device_state(
    x_api_key: Optional[str] = Header(default=None),
    api_key: Optional[str] = Query(default=None, alias="x-api-key"),
):
    """Get the current status of all medical devices in the operating room.
    Returns each device's power state, pressure settings, flow rate, and operational status."""
    # Allow unauthenticated access for UI polling, but validate if key is provided
    key = x_api_key or api_key
    if key and key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return _get_public_state()


@app.post("/api/devices/insufflator/power")
async def set_insufflator_power(req: PowerRequest, _=Depends(verify_api_key)):
    """Turn the CO2 insufflator on or off.

    When turned on, the insufflator begins pressurizing to the target pressure.
    When turned off, pressure returns to 0 and the device enters standby mode.
    """
    state = device_state["insufflator"]
    state["power"] = req.power

    if req.power:
        state["status"] = "ACTIVE"
        state["actual_pressure_mmhg"] = state["target_pressure_mmhg"]
    else:
        state["status"] = "STANDBY"
        state["actual_pressure_mmhg"] = 0

    _persist_state()

    return {
        "device": state["name"],
        "action": "powered ON" if req.power else "powered OFF",
        "status": state["status"],
        "actual_pressure_mmhg": state["actual_pressure_mmhg"],
    }


@app.post("/api/devices/insufflator/settings")
async def set_insufflator_settings(req: SettingsRequest, _=Depends(verify_api_key)):
    """Adjust the CO2 insufflator settings.

    Args:
        target_pressure_mmhg: Target abdominal pressure in mmHg (8-20). Standard is 12-15 mmHg.
        flow_rate_lpm: CO2 flow rate in liters per minute (1-45). Standard is 15-20 L/min.
    """
    state = device_state["insufflator"]
    changes = []

    if req.target_pressure_mmhg is not None:
        pressure = max(8, min(20, req.target_pressure_mmhg))
        state["target_pressure_mmhg"] = pressure
        if state["power"]:
            state["actual_pressure_mmhg"] = pressure
        changes.append(f"target_pressure={pressure} mmHg")

    if req.flow_rate_lpm is not None:
        flow = max(1, min(45, req.flow_rate_lpm))
        state["flow_rate_lpm"] = flow
        changes.append(f"flow_rate={flow} L/min")

    _persist_state()

    return {
        "device": state["name"],
        "changes": changes,
        "current_state": {
            "power": "ON" if state["power"] else "OFF",
            "target_pressure_mmhg": state["target_pressure_mmhg"],
            "flow_rate_lpm": state["flow_rate_lpm"],
            "actual_pressure_mmhg": state["actual_pressure_mmhg"],
            "status": state["status"],
        },
    }


# --- Entrypoint ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OR Medical Device API Server")
    parser.add_argument("--port", type=int, default=8933, help="Port to listen on (default: 8933)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    print(f"[Devices] Starting device API on {args.host}:{args.port}")
    print(f"[Devices] Devices: {', '.join(device_state.keys())}")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)

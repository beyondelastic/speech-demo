"""
OR Light Control REST API
Plain FastAPI server simulating operating room lighting control.
No MCP protocol — direct HTTP for minimal latency.
"""

import json
import argparse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Light State ---

# Named color presets → RGB hex
COLOR_MAP = {
    "light_blue": "#ADD8E6",
    "light_green": "#90EE90",
    "red": "#FF4444",
    "warm_white": None,   # reset to color_temp
    "white": None,        # reset to color_temp
}

LIGHTS = {
    "surgical_main": {
        "name": "Surgical Main Light",
        "zone": "surgical",
        "power": True,
        "brightness": 100,
        "color_temp": 4500,
        "color": None,
    },
    "surgical_secondary": {
        "name": "Surgical Secondary Light",
        "zone": "surgical",
        "power": True,
        "brightness": 80,
        "color_temp": 4500,
        "color": None,
    },
    "ambient_ceiling": {
        "name": "Ambient Ceiling Light",
        "zone": "ambient",
        "power": True,
        "brightness": 60,
        "color_temp": 4000,
        "color": None,
    },
    "ambient_wall": {
        "name": "Ambient Wall Light",
        "zone": "ambient",
        "power": True,
        "brightness": 40,
        "color_temp": 3500,
        "color": None,
    },
    "task_monitor": {
        "name": "Monitor Backlight",
        "zone": "task",
        "power": True,
        "brightness": 70,
        "color_temp": 5000,
        "color": None,
    },
}

SCENE_PRESETS = {
    "full_surgery": {
        "name": "Full Surgery",
        "description": "Maximum surgical lighting, reduced ambient for focus",
        "settings": {
            "surgical_main": {"power": True, "brightness": 100, "color_temp": 4500},
            "surgical_secondary": {"power": True, "brightness": 90, "color_temp": 4500},
            "ambient_ceiling": {"power": True, "brightness": 30, "color_temp": 3500},
            "ambient_wall": {"power": True, "brightness": 20, "color_temp": 3500},
            "task_monitor": {"power": True, "brightness": 70, "color_temp": 5000},
        },
    },
    "laparoscopy": {
        "name": "Laparoscopy Mode",
        "description": "Dimmed room for optimal monitor visibility, blue ambient",
        "settings": {
            "surgical_main": {"power": False, "brightness": 0, "color_temp": 4500},
            "surgical_secondary": {"power": False, "brightness": 0, "color_temp": 4500},
            "ambient_ceiling": {"power": True, "brightness": 10, "color_temp": 3000, "color": "light_blue"},
            "ambient_wall": {"power": True, "brightness": 10, "color_temp": 3000, "color": "light_blue"},
            "task_monitor": {"power": True, "brightness": 100, "color_temp": 5000},
        },
    },
    "prep": {
        "name": "Preparation Mode",
        "description": "Full brightness for patient preparation",
        "settings": {
            "surgical_main": {"power": True, "brightness": 100, "color_temp": 5000},
            "surgical_secondary": {"power": True, "brightness": 100, "color_temp": 5000},
            "ambient_ceiling": {"power": True, "brightness": 100, "color_temp": 5000},
            "ambient_wall": {"power": True, "brightness": 100, "color_temp": 5000},
            "task_monitor": {"power": True, "brightness": 80, "color_temp": 5000},
        },
    },
    "closing": {
        "name": "Closing Mode",
        "description": "Moderate surgical light with comfortable ambient",
        "settings": {
            "surgical_main": {"power": True, "brightness": 80, "color_temp": 4000},
            "surgical_secondary": {"power": True, "brightness": 60, "color_temp": 4000},
            "ambient_ceiling": {"power": True, "brightness": 50, "color_temp": 3500},
            "ambient_wall": {"power": True, "brightness": 40, "color_temp": 3500},
            "task_monitor": {"power": True, "brightness": 60, "color_temp": 5000},
        },
    },
    "emergency": {
        "name": "Emergency Mode",
        "description": "All lights maximum brightness",
        "settings": {
            "surgical_main": {"power": True, "brightness": 100, "color_temp": 5500},
            "surgical_secondary": {"power": True, "brightness": 100, "color_temp": 5500},
            "ambient_ceiling": {"power": True, "brightness": 100, "color_temp": 5500},
            "ambient_wall": {"power": True, "brightness": 100, "color_temp": 5500},
            "task_monitor": {"power": True, "brightness": 100, "color_temp": 5500},
        },
    },
    "standby": {
        "name": "Standby Mode",
        "description": "Minimal lighting when OR is not in active use",
        "settings": {
            "surgical_main": {"power": False, "brightness": 0, "color_temp": 4500},
            "surgical_secondary": {"power": False, "brightness": 0, "color_temp": 4500},
            "ambient_ceiling": {"power": True, "brightness": 20, "color_temp": 3000},
            "ambient_wall": {"power": True, "brightness": 15, "color_temp": 3000},
            "task_monitor": {"power": False, "brightness": 0, "color_temp": 5000},
        },
    },
}

light_state: dict = {}
STATE_FILE = Path(__file__).parent / ".or_lights_state.json"


def _reset():
    global light_state
    light_state = {k: dict(v) for k, v in LIGHTS.items()}
    _persist()


def _persist():
    result = {}
    for lid, s in light_state.items():
        result[lid] = {
            "name": s["name"],
            "zone": s["zone"],
            "power": "ON" if s["power"] else "OFF",
            "brightness": s["brightness"],
            "color_temp_kelvin": s["color_temp"],
            "color": s.get("color"),
            "color_hex": COLOR_MAP.get(s.get("color"), None) if s.get("color") else None,
        }
    STATE_FILE.write_text(json.dumps(result))


_reset()

# --- FastAPI ---

app = FastAPI(title="OR Light Control API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SetLightRequest(BaseModel):
    light_id: str
    power: Optional[bool] = None
    brightness: Optional[int] = None
    color_temp: Optional[int] = None
    color: Optional[str] = None


class SetZoneRequest(BaseModel):
    zone: str
    power: Optional[bool] = None
    brightness: Optional[int] = None
    color_temp: Optional[int] = None
    color: Optional[str] = None


class SceneRequest(BaseModel):
    scene: str


def _apply_light(light_id: str, power=None, brightness=None, color_temp=None, color=None):
    if light_id not in light_state:
        return {"error": f"Unknown light: {light_id}"}
    s = light_state[light_id]
    changes = []
    if power is not None:
        s["power"] = power
        changes.append(f"power={'ON' if power else 'OFF'}")
        # Auto-set brightness to 50% when turning on a light that's at 0%
        if power and s["brightness"] == 0 and brightness is None:
            s["brightness"] = 50
            changes.append("brightness=50% (auto)")
    if brightness is not None:
        brightness = max(0, min(100, brightness))
        s["brightness"] = brightness
        changes.append(f"brightness={brightness}%")
        if brightness > 0 and not s["power"]:
            s["power"] = True
            changes.append("power=ON (auto)")
    if color_temp is not None:
        color_temp = max(3000, min(6000, color_temp))
        s["color_temp"] = color_temp
        changes.append(f"color_temp={color_temp}K")
    if color is not None:
        if color in ("white", "warm_white"):
            s["color"] = None
            changes.append("color=white (reset)")
        elif color in COLOR_MAP:
            s["color"] = color
            changes.append(f"color={color}")
        else:
            changes.append(f"unknown color: {color}")
    return {"light": s["name"], "changes": changes, "power": "ON" if s["power"] else "OFF", "brightness": s["brightness"]}


@app.get("/api/lights/state")
async def get_state():
    result = {}
    for lid, s in light_state.items():
        result[lid] = {
            "name": s["name"],
            "zone": s["zone"],
            "power": "ON" if s["power"] else "OFF",
            "brightness": s["brightness"],
            "color_temp_kelvin": s["color_temp"],
            "color": s.get("color"),
            "color_hex": COLOR_MAP.get(s.get("color"), None) if s.get("color") else None,
        }
    return result


@app.post("/api/lights/set")
async def set_light(req: SetLightRequest):
    result = _apply_light(req.light_id, req.power, req.brightness, req.color_temp, req.color)
    _persist()
    return result


@app.post("/api/lights/zone")
async def set_zone(req: SetZoneRequest):
    results = []
    for lid, s in light_state.items():
        if req.zone == "all" or s["zone"] == req.zone:
            results.append(_apply_light(lid, req.power, req.brightness, req.color_temp, req.color))
    _persist()
    if not results:
        return {"error": f"No lights in zone: {req.zone}"}
    return {"zone": req.zone, "lights_updated": len(results), "results": results}


@app.post("/api/lights/scene")
async def activate_scene(req: SceneRequest):
    if req.scene not in SCENE_PRESETS:
        return {"error": f"Unknown scene: {req.scene}. Available: {', '.join(SCENE_PRESETS.keys())}"}
    preset = SCENE_PRESETS[req.scene]
    for lid, settings in preset["settings"].items():
        if lid in light_state:
            light_state[lid]["power"] = settings["power"]
            light_state[lid]["brightness"] = settings["brightness"]
            light_state[lid]["color_temp"] = settings["color_temp"]
            light_state[lid]["color"] = settings.get("color")  # apply scene color or reset to None
    _persist()
    return {"scene": preset["name"], "description": preset["description"], "lights_configured": len(preset["settings"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8932)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()
    print(f"[OR Lights] REST API on {args.host}:{args.port}")
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)

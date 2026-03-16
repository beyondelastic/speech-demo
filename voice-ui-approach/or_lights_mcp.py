"""
OR Light Control MCP Server
A Model Context Protocol server that simulates operating room lighting control.
Exposes tools for controlling surgical lights, ambient lights, and scene presets.
Runs as a Streamable HTTP MCP server on a configurable port.
"""

import json
import asyncio
import argparse
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# --- Light State ---

# Default light configuration for the OR
LIGHTS = {
    "surgical_main": {
        "name": "Surgical Main Light",
        "zone": "surgical",
        "power": True,
        "brightness": 100,
        "color_temp": 4500,  # Kelvin
        "description": "Primary overhead surgical light"
    },
    "surgical_secondary": {
        "name": "Surgical Secondary Light",
        "zone": "surgical",
        "power": True,
        "brightness": 80,
        "color_temp": 4500,
        "description": "Secondary surgical light for shadow reduction"
    },
    "ambient_ceiling": {
        "name": "Ambient Ceiling Light",
        "zone": "ambient",
        "power": True,
        "brightness": 60,
        "color_temp": 4000,
        "description": "General ceiling ambient lighting"
    },
    "ambient_wall": {
        "name": "Ambient Wall Light",
        "zone": "ambient",
        "power": True,
        "brightness": 40,
        "color_temp": 3500,
        "description": "Wall-mounted ambient lighting"
    },
    "task_monitor": {
        "name": "Monitor Backlight",
        "zone": "task",
        "power": True,
        "brightness": 70,
        "color_temp": 5000,
        "description": "Backlight behind monitoring displays"
    }
}

# Scene presets for common OR scenarios
SCENE_PRESETS = {
    "full_surgery": {
        "name": "Full Surgery",
        "description": "Maximum surgical lighting, reduced ambient for focus",
        "settings": {
            "surgical_main": {"power": True, "brightness": 100, "color_temp": 4500},
            "surgical_secondary": {"power": True, "brightness": 90, "color_temp": 4500},
            "ambient_ceiling": {"power": True, "brightness": 30, "color_temp": 3500},
            "ambient_wall": {"power": True, "brightness": 20, "color_temp": 3500},
            "task_monitor": {"power": True, "brightness": 70, "color_temp": 5000}
        }
    },
    "laparoscopy": {
        "name": "Laparoscopy Mode",
        "description": "Dimmed room for optimal monitor visibility during laparoscopic procedures",
        "settings": {
            "surgical_main": {"power": False, "brightness": 0, "color_temp": 4500},
            "surgical_secondary": {"power": False, "brightness": 0, "color_temp": 4500},
            "ambient_ceiling": {"power": True, "brightness": 10, "color_temp": 3000},
            "ambient_wall": {"power": True, "brightness": 10, "color_temp": 3000},
            "task_monitor": {"power": True, "brightness": 100, "color_temp": 5000}
        }
    },
    "prep": {
        "name": "Preparation Mode",
        "description": "Full brightness everywhere for patient preparation and setup",
        "settings": {
            "surgical_main": {"power": True, "brightness": 100, "color_temp": 5000},
            "surgical_secondary": {"power": True, "brightness": 100, "color_temp": 5000},
            "ambient_ceiling": {"power": True, "brightness": 100, "color_temp": 5000},
            "ambient_wall": {"power": True, "brightness": 100, "color_temp": 5000},
            "task_monitor": {"power": True, "brightness": 80, "color_temp": 5000}
        }
    },
    "closing": {
        "name": "Closing Mode",
        "description": "Moderate surgical light with comfortable ambient for wound closing",
        "settings": {
            "surgical_main": {"power": True, "brightness": 80, "color_temp": 4000},
            "surgical_secondary": {"power": True, "brightness": 60, "color_temp": 4000},
            "ambient_ceiling": {"power": True, "brightness": 50, "color_temp": 3500},
            "ambient_wall": {"power": True, "brightness": 40, "color_temp": 3500},
            "task_monitor": {"power": True, "brightness": 60, "color_temp": 5000}
        }
    },
    "emergency": {
        "name": "Emergency Mode",
        "description": "All lights maximum brightness - emergency situation",
        "settings": {
            "surgical_main": {"power": True, "brightness": 100, "color_temp": 5500},
            "surgical_secondary": {"power": True, "brightness": 100, "color_temp": 5500},
            "ambient_ceiling": {"power": True, "brightness": 100, "color_temp": 5500},
            "ambient_wall": {"power": True, "brightness": 100, "color_temp": 5500},
            "task_monitor": {"power": True, "brightness": 100, "color_temp": 5500}
        }
    },
    "standby": {
        "name": "Standby Mode",
        "description": "Minimal lighting when OR is not in active use",
        "settings": {
            "surgical_main": {"power": False, "brightness": 0, "color_temp": 4500},
            "surgical_secondary": {"power": False, "brightness": 0, "color_temp": 4500},
            "ambient_ceiling": {"power": True, "brightness": 20, "color_temp": 3000},
            "ambient_wall": {"power": True, "brightness": 15, "color_temp": 3000},
            "task_monitor": {"power": False, "brightness": 0, "color_temp": 5000}
        }
    }
}

# Mutable state
light_state: dict[str, dict[str, Any]] = {}

STATE_FILE = Path(__file__).parent / ".or_lights_state.json"


def reset_lights():
    """Reset lights to default state."""
    global light_state
    light_state = {k: dict(v) for k, v in LIGHTS.items()}
    _persist_state()


def _persist_state():
    """Write current light state to shared file for the frontend to read."""
    result = {}
    for light_id, state in light_state.items():
        result[light_id] = {
            "name": state["name"],
            "zone": state["zone"],
            "power": "ON" if state["power"] else "OFF",
            "brightness": state["brightness"],
            "color_temp_kelvin": state["color_temp"]
        }
    STATE_FILE.write_text(json.dumps(result))


reset_lights()


# --- MCP Server ---

mcp = FastMCP(
    "OR Light Control",
    instructions=(
        "You control operating room lights. Available lights: "
        "surgical_main, surgical_secondary, ambient_ceiling, ambient_wall, task_monitor. "
        "Available scene presets: full_surgery, laparoscopy, prep, closing, emergency, standby. "
        "Always confirm actions clearly so the doctor hears verbal feedback."
    )
)


@mcp.tool()
def get_all_lights() -> str:
    """Get the current status of all lights in the operating room.
    Returns each light's power state, brightness (0-100), and color temperature in Kelvin."""
    result = {}
    for light_id, state in light_state.items():
        result[light_id] = {
            "name": state["name"],
            "zone": state["zone"],
            "power": "ON" if state["power"] else "OFF",
            "brightness": state["brightness"],
            "color_temp_kelvin": state["color_temp"]
        }
    return json.dumps(result, indent=2)


@mcp.tool()
def set_light(light_id: str, power: bool | None = None, brightness: int | None = None, color_temp: int | None = None) -> str:
    """Control a specific light in the operating room.

    Args:
        light_id: The light to control. One of: surgical_main, surgical_secondary, ambient_ceiling, ambient_wall, task_monitor
        power: Turn light on (true) or off (false). Omit to keep current state.
        brightness: Set brightness from 0 to 100. Omit to keep current value.
        color_temp: Set color temperature in Kelvin (3000-6000). Omit to keep current value.
    """
    if light_id not in light_state:
        return json.dumps({"error": f"Unknown light: {light_id}. Valid lights: {', '.join(light_state.keys())}"})

    state = light_state[light_id]
    changes = []

    if power is not None:
        state["power"] = power
        changes.append(f"power={'ON' if power else 'OFF'}")

    if brightness is not None:
        brightness = max(0, min(100, brightness))
        state["brightness"] = brightness
        changes.append(f"brightness={brightness}%")
        if brightness > 0 and not state["power"]:
            state["power"] = True
            changes.append("power=ON (auto)")

    if color_temp is not None:
        color_temp = max(3000, min(6000, color_temp))
        state["color_temp"] = color_temp
        changes.append(f"color_temp={color_temp}K")

    _persist_state()

    return json.dumps({
        "light": state["name"],
        "changes": changes,
        "current_state": {
            "power": "ON" if state["power"] else "OFF",
            "brightness": state["brightness"],
            "color_temp_kelvin": state["color_temp"]
        }
    })


@mcp.tool()
def set_light_zone(zone: str, power: bool | None = None, brightness: int | None = None, color_temp: int | None = None) -> str:
    """Control all lights in a zone at once.

    Args:
        zone: The zone to control. One of: surgical, ambient, task, all
        power: Turn lights on (true) or off (false). Omit to keep current state.
        brightness: Set brightness from 0 to 100. Omit to keep current value.
        color_temp: Set color temperature in Kelvin (3000-6000). Omit to keep current value.
    """
    results = []
    for light_id, state in light_state.items():
        if zone == "all" or state["zone"] == zone:
            result = set_light(light_id, power=power, brightness=brightness, color_temp=color_temp)
            results.append(json.loads(result))

    if not results:
        return json.dumps({"error": f"No lights found in zone: {zone}. Valid zones: surgical, ambient, task, all"})

    return json.dumps({"zone": zone, "lights_updated": len(results), "results": results})


@mcp.tool()
def activate_scene(scene: str) -> str:
    """Activate a predefined lighting scene preset for the operating room.

    Args:
        scene: The scene preset to activate. One of: full_surgery, laparoscopy, prep, closing, emergency, standby
    """
    if scene not in SCENE_PRESETS:
        return json.dumps({"error": f"Unknown scene: {scene}. Available scenes: {', '.join(SCENE_PRESETS.keys())}"})

    preset = SCENE_PRESETS[scene]
    for light_id, settings in preset["settings"].items():
        if light_id in light_state:
            light_state[light_id]["power"] = settings["power"]
            light_state[light_id]["brightness"] = settings["brightness"]
            light_state[light_id]["color_temp"] = settings["color_temp"]

    _persist_state()

    return json.dumps({
        "scene": preset["name"],
        "description": preset["description"],
        "lights_configured": len(preset["settings"])
    })


@mcp.tool()
def list_scenes() -> str:
    """List all available lighting scene presets for the operating room."""
    scenes = {}
    for scene_id, preset in SCENE_PRESETS.items():
        scenes[scene_id] = {
            "name": preset["name"],
            "description": preset["description"]
        }
    return json.dumps(scenes, indent=2)


# --- Entrypoint ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OR Light Control MCP Server")
    parser.add_argument("--port", type=int, default=8932, help="Port to listen on (default: 8932)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    print(f"[OR Lights] Starting MCP server on {args.host}:{args.port}")
    print(f"[OR Lights] Lights: {', '.join(light_state.keys())}")
    print(f"[OR Lights] Scenes: {', '.join(SCENE_PRESETS.keys())}")

    # Build a custom Starlette app with routes that match Foundry's URL resolution.
    # Foundry takes the configured URL path (/sse) and prepends it to the
    # message path the SSE server returns. So if SSE returns "messages/?session_id=...",
    # Foundry posts to /sse/messages/?session_id=...
    # We set the SseServerTransport endpoint to "messages/" (relative) so the SSE
    # stream returns that, and mount the handler at /sse/messages/ where Foundry posts.
    import uvicorn
    import anyio
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from starlette.requests import Request
    from starlette.responses import Response
    from mcp.server.sse import SseServerTransport

    sse_transport = SseServerTransport("messages/")

    async def handle_sse(request: Request) -> Response:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0],
                streams[1],
                mcp._mcp_server.create_initialization_options(),
            )
        return Response()

    starlette_app = Starlette(
        debug=False,
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/sse/messages/", app=sse_transport.handle_post_message),
        ],
    )

    config = uvicorn.Config(
        starlette_app,
        host=args.host,
        port=args.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    anyio.run(server.serve)

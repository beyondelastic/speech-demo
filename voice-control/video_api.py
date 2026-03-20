"""
Simulated Endoscope Video Recording API
REST API simulating an on-premises endoscope video recorder.
Supports start/stop recording and snapshot capture.
"""

import argparse
import json
import time
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="OR Video Recording API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- State ---

STATE_FILE = Path(__file__).parent / ".or_video_state.json"

video_state = {
    "recording": False,
    "recording_start_time": None,
    "duration_seconds": 0,
    "snapshots": [],
    "total_recordings": 0,
}


def _persist():
    STATE_FILE.write_text(json.dumps(_public_state()))


def _public_state():
    s = dict(video_state)
    if s["recording"] and s["recording_start_time"]:
        s["duration_seconds"] = round(time.time() - s["recording_start_time"], 1)
    return {
        "recording": s["recording"],
        "duration_seconds": s["duration_seconds"],
        "snapshot_count": len(s["snapshots"]),
        "total_recordings": s["total_recordings"],
        "last_snapshot": s["snapshots"][-1] if s["snapshots"] else None,
    }


_persist()


# --- Endpoints ---

@app.get("/api/video/state")
async def get_state():
    return _public_state()


@app.post("/api/video/record/start")
async def start_recording():
    if video_state["recording"]:
        return {"status": "already_recording", "message": "Recording is already in progress"}
    video_state["recording"] = True
    video_state["recording_start_time"] = time.time()
    video_state["duration_seconds"] = 0
    _persist()
    return {"status": "started", "message": "Recording started"}


@app.post("/api/video/record/stop")
async def stop_recording():
    if not video_state["recording"]:
        return {"status": "not_recording", "message": "No recording in progress"}
    duration = round(time.time() - video_state["recording_start_time"], 1)
    video_state["recording"] = False
    video_state["recording_start_time"] = None
    video_state["duration_seconds"] = duration
    video_state["total_recordings"] += 1
    _persist()
    return {"status": "stopped", "duration_seconds": duration, "message": f"Recording stopped ({duration}s)"}


@app.post("/api/video/snapshot")
async def take_snapshot():
    ts = datetime.now(timezone.utc).isoformat()
    video_state["snapshots"].append(ts)
    _persist()
    return {"status": "captured", "snapshot_number": len(video_state["snapshots"]), "timestamp": ts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8933)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()
    print(f"[Video] REST API on {args.host}:{args.port}")
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)

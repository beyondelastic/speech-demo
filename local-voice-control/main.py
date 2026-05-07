"""
Local Voice Control Backend — Edge OR Assistant
Azure Speech Container (STT/TTS) + Foundry Local (LLM with tool calling).
Target: Low-latency, runs on laptop. Internet only needed for speech billing.
"""

import os
import json
import re
import time
import asyncio
import threading
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import azure.cognitiveservices.speech as speechsdk
from openai import AsyncOpenAI
import httpx
from xml.sax.saxutils import escape as xml_escape

# Load .env from parent directory
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)
# Also load local .env if present
local_env = Path(__file__).parent / ".env"
if local_env.exists():
    load_dotenv(dotenv_path=local_env, override=True)

app = FastAPI(title="Local Voice Control Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Globals ---
_openai_client: Optional[AsyncOpenAI] = None
_http_client: Optional[httpx.AsyncClient] = None
_system_prompt: str = ""
_cached_synthesizers: dict = {}
_precached_tts: dict = {}

LIGHTS_API = os.getenv("LIGHTS_API_URL", "http://localhost:8932")
VIDEO_API = os.getenv("VIDEO_API_URL", "http://localhost:8933")
MODEL_NAME = os.getenv("MODEL_NAME", "Phi-4-mini-instruct-generic-cpu:5")
SILENCE_TIMEOUT_MS = int(os.getenv("SILENCE_TIMEOUT_MS", "300"))
MAX_CONVERSATION_MESSAGES = 12
WAKE_WORD = os.getenv("WAKE_WORD", "computer").lower()
WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "true").lower() == "true"
_WAKE_VARIANTS = {WAKE_WORD}

# Speech container config
SPEECH_CONTAINER_HOST = os.getenv("SPEECH_CONTAINER_HOST", "ws://localhost:5000")
TTS_CONTAINER_HOST = os.getenv("TTS_CONTAINER_HOST", "http://localhost:5001")
SPEECH_KEY = os.getenv("SPEECH_KEY", "")
SPEECH_REGION = os.getenv("SPEECH_REGION", "")

# Foundry Local endpoint (OpenAI-compatible server mode)
FOUNDRY_LOCAL_ENDPOINT = os.getenv("FOUNDRY_LOCAL_ENDPOINT", "http://localhost:5273/v1")

static_path = Path(__file__).parent

# --- Tool Definitions (same format as OpenAI function calling) ---

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_lights",
            "description": "Get current state of all OR lights",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_light",
            "description": "Control a single specific light. Only changes the parameters you provide — other lights are NOT affected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "light_id": {"type": "string", "enum": ["surgical_main", "surgical_secondary", "ambient_ceiling", "ambient_wall", "task_monitor"]},
                    "power": {"type": "boolean", "description": "Turn on/off"},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
                    "color_temp": {"type": "integer", "minimum": 3000, "maximum": 6000, "description": "Kelvin"},
                    "color": {"type": "string", "enum": ["light_blue", "light_green", "red", "white"], "description": "Named color preset. Use 'white' to reset to normal."},
                },
                "required": ["light_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_zone",
            "description": "Control all lights in one zone. Only changes lights in the specified zone — other zones are NOT affected. Only changes the parameters you provide.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone": {"type": "string", "enum": ["surgical", "ambient", "task", "all"]},
                    "power": {"type": "boolean"},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
                    "color_temp": {"type": "integer", "minimum": 3000, "maximum": 6000},
                    "color": {"type": "string", "enum": ["light_blue", "light_green", "red", "white"], "description": "Named color preset. Use 'white' to reset to normal."},
                },
                "required": ["zone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "activate_scene",
            "description": "Activate a lighting scene preset. This changes ALL lights at once to predefined values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene": {"type": "string", "enum": ["full_surgery", "laparoscopy", "prep", "closing", "emergency", "standby"]},
                },
                "required": ["scene"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_recording",
            "description": "Start endoscope video recording. ONLY call this when user explicitly says 'start recording', 'Aufnahme starten', or 'prepare for laparoscopy'. Never call for prep/preparation/standby/closing commands.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_recording",
            "description": "Stop endoscope video recording",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_snapshot",
            "description": "Take a still image from the endoscope",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# Tools that need the full LLM round-trip (not fast path)
VIDEO_TOOLS = {"start_recording", "stop_recording"}
FULL_LLM_TOOLS = VIDEO_TOOLS | {"get_lights"}

# Keywords that justify recording tool calls
_RECORDING_KEYWORDS = {"recording", "record", "aufnahme", "video", "laparoscopy", "laparoskopie", "end procedure", "eingriff beenden"}

def _user_wants_recording(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in _RECORDING_KEYWORDS)


# --- Startup ---

@app.on_event("startup")
async def startup():
    global _openai_client, _http_client, _system_prompt

    # Load system prompt
    prompt_file = static_path / "SYSTEM_PROMPT.md"
    if prompt_file.exists():
        _system_prompt = prompt_file.read_text()

    # Foundry Local OpenAI-compatible client
    _openai_client = AsyncOpenAI(
        base_url=FOUNDRY_LOCAL_ENDPOINT,
        api_key="foundry-local",  # placeholder, not validated locally
    )
    print(f"[Startup] Foundry Local client initialized ({FOUNDRY_LOCAL_ENDPOINT}, model={MODEL_NAME})")

    # Warmup LLM
    try:
        t = time.time()
        await _openai_client.chat.completions.create(
            model=MODEL_NAME, messages=[{"role": "user", "content": "hi"}], max_tokens=1
        )
        print(f"[Startup] LLM warmup done ({(time.time()-t)*1000:.0f}ms)")
    except Exception as e:
        print(f"[Startup] LLM warmup failed (is Foundry Local running?): {e}")

    # HTTP client for device APIs
    _http_client = httpx.AsyncClient(timeout=10.0)

    # Speech credentials check
    if SPEECH_KEY:
        print(f"[Startup] Speech credentials configured (region: {SPEECH_REGION})")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _warmup_and_precache_tts)
    else:
        print("[Startup] Warning: No SPEECH_KEY set — TTS/STT will not work")


@app.on_event("shutdown")
async def shutdown():
    if _http_client:
        await _http_client.aclose()


# --- Speech Helpers (using Azure Speech container) ---

def _get_speech_config():
    """Speech config for STT (recognition) — points to STT container."""
    if not SPEECH_KEY:
        raise ValueError("No speech credentials (SPEECH_KEY not set)")
    if SPEECH_CONTAINER_HOST:
        config = speechsdk.SpeechConfig(host=SPEECH_CONTAINER_HOST, subscription=SPEECH_KEY)
    else:
        config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    return config


def _get_tts_speech_config():
    """Speech config for TTS (synthesis) — points to TTS container."""
    if not SPEECH_KEY:
        raise ValueError("No speech credentials (SPEECH_KEY not set)")
    if TTS_CONTAINER_HOST:
        config = speechsdk.SpeechConfig(host=TTS_CONTAINER_HOST, subscription=SPEECH_KEY)
    else:
        config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    return config


def _get_synthesizer(voice_name: str):
    if voice_name not in _cached_synthesizers:
        cfg = _get_tts_speech_config()
        cfg.speech_synthesis_voice_name = voice_name
        cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Ogg24Khz16BitMonoOpus)
        _cached_synthesizers[voice_name] = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    return _cached_synthesizers[voice_name]


def _synthesize(text: str, voice: str = None) -> Optional[bytes]:
    if not voice:
        voice = "de-DE-KatjaNeural" if _detect_german(text) else "en-US-AriaNeural"
    synth = _get_synthesizer(voice)
    lang = "de-DE" if "de-DE" in voice else "en-US"
    ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
            f'<voice name="{voice}">{xml_escape(text)}</voice></speak>')
    result = synth.speak_ssml_async(ssml).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    return None


def _warmup_and_precache_tts():
    phrases = {
        "en:recording_started": ("Recording started.", "en-US-AriaNeural"),
        "en:recording_stopped": ("Recording stopped.", "en-US-AriaNeural"),
        "en:snapshot_taken": ("Snapshot taken.", "en-US-AriaNeural"),
        "de:recording_started": ("Aufnahme gestartet.", "de-DE-KatjaNeural"),
        "de:recording_stopped": ("Aufnahme gestoppt.", "de-DE-KatjaNeural"),
        "de:snapshot_taken": ("Foto aufgenommen.", "de-DE-KatjaNeural"),
    }
    for key, (text, voice) in phrases.items():
        audio = _synthesize(text, voice)
        if audio:
            _precached_tts[key] = audio
            print(f"[TTS] Pre-cached: {key} ({len(audio)} bytes)")
        else:
            print(f"[TTS] Failed to pre-cache: {key}")
    print(f"[TTS] Pre-cached {len(_precached_tts)} audio blobs")


def _detect_german(text: str) -> bool:
    words = text.lower().split()
    german = {"der", "die", "das", "und", "ist", "ein", "eine", "ich", "du", "sie",
              "bitte", "auf", "zu", "von", "mit", "für", "nicht", "haben", "sein",
              "öffne", "alle", "licht", "lichter", "heller", "dunkler", "aufnahme",
              "starten", "stoppen", "foto", "machen", "vorbereiten", "beenden"}
    has_words = any(w in german for w in words)
    has_umlauts = any(c in text.lower() for c in "äöüß")
    return has_words or has_umlauts


# --- Tool Dispatch ---

async def dispatch_tool(name: str, args: dict) -> str:
    try:
        if name == "get_lights":
            r = await _http_client.get(f"{LIGHTS_API}/api/lights/state")
        elif name == "set_light":
            r = await _http_client.post(f"{LIGHTS_API}/api/lights/set", json=args)
        elif name == "set_zone":
            r = await _http_client.post(f"{LIGHTS_API}/api/lights/zone", json=args)
        elif name == "activate_scene":
            r = await _http_client.post(f"{LIGHTS_API}/api/lights/scene", json=args)
        elif name == "start_recording":
            r = await _http_client.post(f"{VIDEO_API}/api/video/record/start")
        elif name == "stop_recording":
            r = await _http_client.post(f"{VIDEO_API}/api/video/record/stop")
        elif name == "take_snapshot":
            r = await _http_client.post(f"{VIDEO_API}/api/video/snapshot")
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
        r.raise_for_status()
        return r.text
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Quick confirmation for light-only commands (skip 2nd LLM call) ---

_LIGHT_CONFIRMS = {
    "set_light": {"en": "Done.", "de": "Erledigt."},
    "set_zone": {"en": "Done.", "de": "Erledigt."},
    "take_snapshot": {"en": "Snapshot taken.", "de": "Foto aufgenommen."},
    "activate_scene": {
        "en": {"laparoscopy": "Laparoscopy mode.", "full_surgery": "Full surgery mode.",
               "prep": "Prep mode.", "closing": "Closing mode.", "emergency": "Emergency!",
               "standby": "Standby mode."},
        "de": {"laparoscopy": "Laparoskopie-Modus.", "full_surgery": "Voller OP-Modus.",
               "prep": "Vorbereitungs-Modus.", "closing": "Abschluss-Modus.", "emergency": "Notfall!",
               "standby": "Standby-Modus."},
    },
    "get_lights": {"en": "Here's the current state.", "de": "Aktueller Status."},
}

def _detect_language(text: str) -> str:
    de_markers = ["ä", "ö", "ü", "ß", "licht", "dimm", "modus", "heller", "dunkler",
                  "aufnahme", "starten", "stoppen", "foto", "machen", "bitte",
                  "hoch", "runter", "ein", "aus", "prozent"]
    return "de" if any(m in text.lower() for m in de_markers) else "en"


def _quick_confirm(tool_names: list, user_text: str, first_args: dict = None) -> str:
    lang = _detect_language(user_text)
    name = tool_names[0] if tool_names else "set_light"
    confirm = _LIGHT_CONFIRMS.get(name, _LIGHT_CONFIRMS["set_light"])
    if isinstance(confirm.get(lang), dict):
        scene = (first_args or {}).get("scene", "")
        return confirm[lang].get(scene, "Done." if lang == "en" else "Erledigt.")
    return confirm.get(lang, "Done.")


# --- LLM (Foundry Local via OpenAI-compatible API) ---

async def process_llm(conversation: list, ws: WebSocket, tts_voice: str, pipeline_start: float = None):
    t_start = time.time()
    has_video_tool = False
    last_user_text = ""
    for m in reversed(conversation):
        if m.get("role") == "user":
            last_user_text = m.get("content", "")
            break
    lang = _detect_language(last_user_text)
    lang_hint = "Respond in German." if lang == "de" else "Respond in English."
    messages = [{"role": "system", "content": _system_prompt + f"\n\n## CURRENT LANGUAGE\n{lang_hint}"}] + conversation[-MAX_CONVERSATION_MESSAGES:]

    first_call = True
    for _ in range(3):
        t_llm = time.time()
        # SLM needs "required" to reliably call tools on first pass;
        # after tool results are in, switch to "none" to get text summary.
        if first_call:
            tc_mode = "required"
        else:
            tc_mode = "none"
        response = await _openai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=TOOLS if first_call else None,
            tool_choice=tc_mode if first_call else None,
        )
        first_call = False
        choice = response.choices[0]
        msg = choice.message
        print(f"[LLM] Response ({(time.time()-t_llm)*1000:.0f}ms): finish={choice.finish_reason}")

        messages.append(msg.model_dump(exclude_none=True))

        if choice.finish_reason == "tool_calls" and msg.tool_calls:
            # Guard: strip recording tools when user didn't mention recording
            filtered_calls = msg.tool_calls
            if not _user_wants_recording(last_user_text):
                filtered_calls = [tc for tc in msg.tool_calls if tc.function.name not in VIDEO_TOOLS]
                if len(filtered_calls) < len(msg.tool_calls):
                    print(f"[Guard] Stripped recording tools — user said: {last_user_text!r}")
                if not filtered_calls:
                    fallback = _quick_confirm([], conversation[-1].get("content", ""), None)
                    conversation.append({"role": "assistant", "content": fallback})
                    await ws.send_json({"type": "agent_response_chunk", "text": fallback})
                    pipeline_ms = round((time.time() - pipeline_start) * 1000) if pipeline_start else None
                    await ws.send_json({"type": "agent_response_complete", "full_text": fallback, "pipeline_ms": pipeline_ms})
                    return fallback

            tool_names = []
            tool_args_list = []
            tool_tasks = []
            for tc in filtered_calls:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                print(f"[Tool] {tc.function.name}({args})")
                tool_names.append(tc.function.name)
                tool_args_list.append(args)
                if tc.function.name in VIDEO_TOOLS:
                    has_video_tool = True
                tool_tasks.append((tc, asyncio.create_task(dispatch_tool(tc.function.name, args))))

            # Fast path: simple commands
            if not any(name in FULL_LLM_TOOLS for name in tool_names):
                for tc, task in tool_tasks:
                    result = await task
                    print(f"[Tool] {tc.function.name} → {result[:120]}")
                confirm = _quick_confirm(tool_names, conversation[-1].get("content", ""), tool_args_list[0] if tool_args_list else None)
                print(f"[Fast] Light confirm ({(time.time()-t_start)*1000:.0f}ms): {confirm}")
                conversation.append({"role": "assistant", "content": confirm})
                await ws.send_json({"type": "agent_response_chunk", "text": confirm})
                pipeline_ms = round((time.time() - pipeline_start) * 1000) if pipeline_start else None
                await ws.send_json({"type": "agent_response_complete", "full_text": confirm, "pipeline_ms": pipeline_ms})
                return confirm

            # Video path
            for tc in filtered_calls:
                await ws.send_json({"type": "agent_thinking", "message": f"Using: {tc.function.name}"})
            for tc, task in tool_tasks:
                result = await task
                print(f"[Tool] {tc.function.name} → {result[:120]}")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue

        # Final response
        assistant_text = msg.content or ""
        print(f"[LLM] Total ({(time.time()-t_start)*1000:.0f}ms): {assistant_text}")
        conversation.append({"role": "assistant", "content": assistant_text})
        await ws.send_json({"type": "agent_response_chunk", "text": assistant_text})
        pipeline_ms = round((time.time() - pipeline_start) * 1000) if pipeline_start else None
        await ws.send_json({"type": "agent_response_complete", "full_text": assistant_text, "pipeline_ms": pipeline_ms})

        # TTS for video responses
        if has_video_tool and assistant_text:
            lang_prefix = "de" if tts_voice.startswith("de") else "en"
            cache_key = _match_precached(assistant_text, lang_prefix)
            if cache_key and cache_key in _precached_tts:
                await ws.send_bytes(_precached_tts[cache_key])
                print(f"[TTS] Sent pre-cached: {cache_key}")
            else:
                loop = asyncio.get_event_loop()
                audio = await loop.run_in_executor(None, _synthesize, assistant_text, tts_voice)
                if audio:
                    await ws.send_bytes(audio)
                    print(f"[TTS] Sent synthesized ({len(audio)} bytes)")
        return assistant_text

    return ""


def _match_precached(text: str, lang: str) -> Optional[str]:
    t = text.lower().strip().rstrip(".")
    mappings = {
        "recording_started": ["recording started", "aufnahme gestartet"],
        "recording_stopped": ["recording stopped", "aufnahme gestoppt", "aufnahme beendet"],
        "snapshot_taken": ["snapshot taken", "foto aufgenommen", "bild aufgenommen", "snapshot aufgenommen"],
    }
    for key, patterns in mappings.items():
        if any(p in t for p in patterns):
            return f"{lang}:{key}"
    return None


# --- WebSocket STT + Agent Pipeline ---

@app.websocket("/ws/speech-stream")
async def speech_stream_ws(websocket: WebSocket):
    await websocket.accept()
    print("[WS] Client connected")

    speech_recognizer = None
    stream = None
    recognition_active = False
    is_processing = False
    wake_detected_early = False
    ws_alive = True
    conversation: list = []

    try:
        config_msg = await websocket.receive_json()
        if config_msg.get("type") != "config":
            await websocket.send_json({"type": "error", "message": "First message must be config"})
            await websocket.close()
            return

        speech_config = _get_speech_config()
        speech_config.set_property(speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, str(SILENCE_TIMEOUT_MS))
        speech_config.set_property(speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, "Continuous")
        speech_config.output_format = speechsdk.OutputFormat.Detailed

        # State
        message_queue: asyncio.Queue = asyncio.Queue()
        ws_loop = asyncio.get_event_loop()
        user_text_parts: list = []
        detected_language = "en-US"
        silence_event = asyncio.Event()

        def setup_recognizer():
            nonlocal stream, speech_recognizer
            auto_detect = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=["de-DE", "en-US"])
            fmt = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
            stream = speechsdk.audio.PushAudioInputStream(fmt)
            audio_cfg = speechsdk.audio.AudioConfig(stream=stream)
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config, audio_config=audio_cfg,
                auto_detect_source_language_config=auto_detect,
            )
            # Phrase hints
            grammar = speechsdk.PhraseListGrammar.from_recognizer(speech_recognizer)
            for phrase in [
                "Computer",
                "Bitte in Standby Modus wechseln",
                "Bitte in Laparoskopie Modus wechseln",
                "Bitte in Vorbereitungsmodus wechseln",
                "Bitte in Abschlussmodus wechseln",
                "Bitte in Notfallmodus wechseln",
                "In Standby Modus wechseln",
                "In Laparoskopie Modus wechseln",
                "Wechseln zu Standby",
                "Wechseln zu Laparoskopie",
                "Licht auf 50 Prozent dimmen",
                "Licht ausschalten", "Licht einschalten",
                "Lichter ausschalten", "Lichter einschalten",
                "Alle Lichter aus", "Alle Lichter an",
                "Aufnahme starten", "Aufnahme stoppen",
                "Foto machen", "Bild aufnehmen",
                "Bitte", "wechseln", "Modus", "Prozent",
                "Laparoskopie", "Standby Modus",
                "Notfall", "Notfallmodus",
                "heller", "dunkler", "dimmen", "ausschalten", "einschalten",
                "Licht", "Lichter", "Aufnahme", "Snapshot",
                "Computer switch to laparoscopy mode",
                "Computer switch to standby mode",
                "Computer dim lights",
                "Computer start recording",
                "Computer take a snapshot",
                "Switch to laparoscopy mode", "Switch to standby mode",
                "Switch to closing mode", "Switch to emergency mode",
                "Dim lights", "Turn off the lights", "Turn on the lights",
                "Start recording", "Stop recording", "Take a snapshot",
                "Lichter blau", "Lichter grün", "Lichter rot",
                "Lichter auf blau", "Lichter auf grün",
                "Lichter wieder normal", "Lichter wieder weiß",
                "Lights blue", "Lights green", "Lights red",
                "Set lights to blue", "Lights back to normal",
            ]:
                grammar.addPhrase(phrase)

            def recognizing_cb(evt):
                nonlocal wake_detected_early
                if is_processing:
                    return
                if evt.result.text:
                    if WAKE_WORD_ENABLED and not wake_detected_early:
                        lower = evt.result.text.strip().lower()
                        for variant in _WAKE_VARIANTS:
                            if lower.startswith(variant):
                                wake_detected_early = True
                                ws_loop.call_soon_threadsafe(message_queue.put_nowait, {"type": "wake_word_detected"})
                                print(f"[Wake] Early detection in partial: {evt.result.text[:40]}")
                                break
                    ws_loop.call_soon_threadsafe(message_queue.put_nowait, {"type": "recognizing", "text": evt.result.text})

            def recognized_cb(evt):
                nonlocal detected_language
                if is_processing:
                    return
                if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                    user_text_parts.append(evt.result.text)
                    lang_result = speechsdk.AutoDetectSourceLanguageResult(evt.result)
                    if lang_result.language:
                        detected_language = lang_result.language
                    ws_loop.call_soon_threadsafe(message_queue.put_nowait, {"type": "recognized", "text": evt.result.text})
                    ws_loop.call_soon_threadsafe(silence_event.set)

            def canceled_cb(evt):
                if evt.result.reason == speechsdk.ResultReason.Canceled:
                    details = evt.result.cancellation_details
                    print(f"[STT] Canceled: reason={details.reason}, code={details.error_code}, details={details.error_details}")
                    ws_loop.call_soon_threadsafe(message_queue.put_nowait,
                        {"type": "error", "message": f"STT canceled: {details.reason} — {details.error_details}"})

            speech_recognizer.recognizing.connect(recognizing_cb)
            speech_recognizer.recognized.connect(recognized_cb)
            speech_recognizer.canceled.connect(canceled_cb)

        setup_recognizer()
        speech_recognizer.start_continuous_recognition()
        recognition_active = True
        await websocket.send_json({"type": "ready"})
        if WAKE_WORD_ENABLED:
            await websocket.send_json({"type": "wake_word_waiting", "wake_word": WAKE_WORD.capitalize()})
            print(f"[Wake] Wake word mode active: '{WAKE_WORD.capitalize()}'")

        # Background: forward queued messages to WS
        async def sender():
            while ws_alive or not message_queue.empty():
                try:
                    msg = await asyncio.wait_for(message_queue.get(), timeout=0.5)
                    await websocket.send_json(msg)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

        sender_task = asyncio.create_task(sender())

        # Silence monitor: detect end-of-speech → process with LLM
        async def silence_monitor():
            nonlocal is_processing, wake_detected_early
            wake_primed = False
            wake_primed_at = 0.0
            WAKE_PRIME_TIMEOUT = 5.0

            while ws_alive:
                await silence_event.wait()
                silence_event.clear()
                if not ws_alive or is_processing:
                    continue
                if not user_text_parts:
                    continue

                is_processing = True
                t0 = time.time()
                full_text = " ".join(user_text_parts)
                user_text_parts.clear()

                # Wake word gate
                if WAKE_WORD_ENABLED:
                    stripped = full_text.strip()
                    lower = stripped.lower()

                    matched_variant = None
                    for variant in _WAKE_VARIANTS:
                        if lower.startswith(variant):
                            matched_variant = variant
                            break

                    if matched_variant:
                        command_text = stripped[len(matched_variant):].lstrip(" ,.:!?")
                        if not command_text:
                            wake_primed = True
                            wake_primed_at = time.time()
                            await websocket.send_json({"type": "wake_word_detected"})
                            print("[Wake] Primed — waiting for command")
                            is_processing = False
                            wake_detected_early = False
                            continue
                        full_text = command_text
                        wake_primed = False
                        await websocket.send_json({"type": "wake_word_detected"})
                    elif wake_primed and (time.time() - wake_primed_at) < WAKE_PRIME_TIMEOUT:
                        full_text = stripped
                        wake_primed = False
                        print(f"[Wake] Primed follow-up: {full_text[:60]}")
                    else:
                        wake_primed = False
                        is_processing = False
                        wake_detected_early = False
                        print(f"[Wake] Ignored (no wake word): {stripped[:60]}")
                        continue

                tts_voice = "de-DE-KatjaNeural" if detected_language.startswith("de") else "en-US-AriaNeural"
                await websocket.send_json({"type": "processing", "text": full_text})
                conversation.append({"role": "user", "content": full_text})

                await process_llm(conversation, websocket, tts_voice, pipeline_start=t0)
                print(f"[Timing] Full pipeline: {(time.time()-t0)*1000:.0f}ms")

                user_text_parts.clear()
                silence_event.clear()
                is_processing = False
                wake_detected_early = False
                await websocket.send_json({"type": "ready_for_next"})
                if WAKE_WORD_ENABLED:
                    await websocket.send_json({"type": "wake_word_waiting", "wake_word": WAKE_WORD.capitalize()})

        silence_task = asyncio.create_task(silence_monitor())

        # Main loop: receive audio
        while True:
            message = await websocket.receive()
            if "text" in message:
                try:
                    msg = json.loads(message["text"])
                    if msg.get("type") == "stop":
                        break
                except (json.JSONDecodeError, KeyError):
                    pass
            elif "bytes" in message:
                if message["bytes"]:
                    try:
                        stream.write(message["bytes"])
                    except Exception:
                        pass

    except WebSocketDisconnect:
        print("[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        ws_alive = False
        recognition_active = False
        if "sender_task" in locals():
            sender_task.cancel()
            try: await sender_task
            except asyncio.CancelledError: pass
        if "silence_task" in locals():
            silence_task.cancel()
            try: await silence_task
            except asyncio.CancelledError: pass
        if speech_recognizer:
            try: speech_recognizer.stop_continuous_recognition()
            except Exception: pass
        if stream:
            try: stream.close()
            except Exception: pass
        try: await websocket.close()
        except Exception: pass


# --- HTTP Endpoints ---

@app.get("/")
async def root():
    return FileResponse(static_path / "index.html")


@app.get("/app.js")
async def serve_js():
    return FileResponse(static_path / "app.js", media_type="application/javascript")


@app.get("/api/config")
async def get_config():
    return {"silenceTimeoutMs": SILENCE_TIMEOUT_MS, "model": MODEL_NAME, "wakeWord": WAKE_WORD.capitalize() if WAKE_WORD_ENABLED else None}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/test-chat")
async def test_chat(body: dict):
    """Text-based test endpoint: POST {"text": "dim lights to 40%"}"""
    text = body.get("text", "")
    t_start = time.time()
    lang = _detect_language(text)
    lang_hint = "Respond in German." if lang == "de" else "Respond in English."
    messages = [{"role": "system", "content": _system_prompt + f"\n\n## CURRENT LANGUAGE\n{lang_hint}"}, {"role": "user", "content": text}]
    tool_log = []
    first_call = True
    for _ in range(3):
        t_llm = time.time()
        if first_call:
            resp = await _openai_client.chat.completions.create(
                model=MODEL_NAME, messages=messages, tools=TOOLS, tool_choice="required",
            )
        else:
            resp = await _openai_client.chat.completions.create(
                model=MODEL_NAME, messages=messages,
            )
        first_call = False
        choice = resp.choices[0]
        msg = choice.message
        llm_ms = (time.time() - t_llm) * 1000
        messages.append(msg.model_dump(exclude_none=True))
        if choice.finish_reason == "tool_calls" and msg.tool_calls:
            filtered_calls = msg.tool_calls
            if not _user_wants_recording(text):
                filtered_calls = [tc for tc in msg.tool_calls if tc.function.name not in VIDEO_TOOLS]
                if len(filtered_calls) < len(msg.tool_calls):
                    print(f"[Guard] Stripped recording tools — user said: {text!r}")
                if not filtered_calls:
                    confirm = _quick_confirm([], text, None)
                    return {
                        "text": confirm, "tools": tool_log,
                        "llm_ms": round(llm_ms), "total_ms": round((time.time() - t_start) * 1000),
                        "fast_path": True, "guard_stripped": True,
                    }

            tool_names = []
            tool_args_list = []
            for tc in filtered_calls:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_names.append(tc.function.name)
                tool_args_list.append(args)
                result = await dispatch_tool(tc.function.name, args)
                tool_log.append({"tool": tc.function.name, "args": args, "result": json.loads(result) if result.startswith("{") or result.startswith("[") else result})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            if not any(name in FULL_LLM_TOOLS for name in tool_names):
                confirm = _quick_confirm(tool_names, text, tool_args_list[0] if tool_args_list else None)
                return {
                    "text": confirm, "tools": tool_log,
                    "llm_ms": round(llm_ms), "total_ms": round((time.time() - t_start) * 1000),
                    "fast_path": True,
                }
            continue
        return {
            "text": msg.content or "",
            "tools": tool_log,
            "llm_ms": round(llm_ms),
            "total_ms": round((time.time() - t_start) * 1000),
            "fast_path": False,
        }
    return {"text": "", "tools": tool_log, "total_ms": round((time.time() - t_start) * 1000), "fast_path": False}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

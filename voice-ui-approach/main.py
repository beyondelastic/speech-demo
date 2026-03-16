"""
Voice Agent Backend - FastAPI Server
This server handles:
1. Speech-to-text conversion using Azure Speech Services
2. Communication with Microsoft Foundry Agent
3. Text-to-speech conversion for agent responses
"""

import os
import uuid
import json
import base64
import tempfile
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import azure.cognitiveservices.speech as speechsdk
from azure.identity.aio import DefaultAzureCredential
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
import asyncio
import re
import time
from pydub import AudioSegment
from azure.ai.projects.aio import AIProjectClient
import threading
from xml.sax.saxutils import escape as xml_escape

# Load environment variables from .env file in parent directory
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

app = FastAPI(title="Voice Agent Backend")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize reusable clients on startup for better performance"""
    global _project_client, _openai_client, _credential
    global _cached_speech_key, _cached_speech_region
    
    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    if project_endpoint:
        try:
            _credential = DefaultAzureCredential()
            _project_client = AIProjectClient(endpoint=project_endpoint, credential=_credential)
            _openai_client = _project_client.get_openai_client()
            print("[Startup] AI Project Client initialized successfully")
        except Exception as e:
            print(f"[Startup] Warning: Could not initialize AI Project Client: {e}")
    
    # Cache speech credentials at startup to avoid re-resolving on every request
    _cached_speech_key, _cached_speech_region = _resolve_speech_credentials()
    if _cached_speech_key:
        print(f"[Startup] Speech credentials cached (region: {_cached_speech_region})")
        # Warm up TTS synthesizers so the first real call is fast
        import concurrent.futures
        def _warmup_tts():
            for voice in ["en-US-AriaNeural", "de-DE-KatjaNeural"]:
                synth = _get_synthesizer(voice)
                if synth:
                    lang = 'de-DE' if 'de-DE' in voice else 'en-US'
                    ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
                            f'<voice name="{voice}"> </voice></speak>')
                    synth.speak_ssml_async(ssml).get()
                    print(f"[Startup] Warmed up {voice}")
            print("[Startup] TTS synthesizers warmed up")
        concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(_warmup_tts)
    else:
        print("[Startup] Warning: No speech credentials found at startup")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup clients on shutdown"""
    global _project_client
    if _project_client:
        try:
            await _project_client.close()
            print("[Shutdown] AI Project Client closed")
        except Exception as e:
            print(f"[Shutdown] Error closing client: {e}")

# Thread storage for maintaining conversation context
conversation_threads = {}
# Store last response ID for each conversation to handle pending approvals
last_response_ids = {}

# Reusable clients for performance (avoid creating new clients on each request)
_project_client = None
_openai_client = None
_credential = None

# Cached speech credentials (resolved once at startup)
_cached_speech_key = None
_cached_speech_region = None

# Cached SpeechSynthesizers per voice (avoid recreating on every TTS call)
_cached_synthesizers = {}

# Get the directory where main.py is located
static_path = Path(__file__).parent


def _resolve_speech_credentials():
    """Resolve speech key and region from env vars or Azure CLI. Called once at startup."""
    env_speech_key = os.getenv("SPEECH_KEY")
    env_speech_region = os.getenv("SPEECH_REGION")
    if env_speech_key and env_speech_region:
        return env_speech_key, env_speech_region

    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    if project_endpoint:
        match = re.search(r'https://([^.]+)\.services\.ai\.azure\.com', project_endpoint)
        if match:
            resource_name = match.group(1)
            region = 'swedencentral'
            import subprocess
            try:
                result = subprocess.run(
                    ['az', 'cognitiveservices', 'account', 'keys', 'list',
                     '--name', resource_name, '--resource-group', 'aullah-foundry-resource-group',
                     '--query', 'key1', '-o', 'tsv'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip(), region
            except Exception:
                pass
            # Fallback: get a token-based key
            try:
                credential = SyncDefaultAzureCredential()
                token = credential.get_token("https://cognitiveservices.azure.com/.default")
                return token.token, region  # token doubles as auth_token
            except Exception:
                pass
    return None, None


def _get_speech_config(ui_key=None, ui_region=None):
    """Build a SpeechConfig using cached credentials. UI-provided keys take priority."""
    if ui_key and ui_region:
        return speechsdk.SpeechConfig(subscription=ui_key, region=ui_region)

    if not _cached_speech_key:
        raise ValueError("No speech credentials available")

    # If the cached key looks like a JWT token (starts with 'ey'), use auth_token
    if _cached_speech_key.startswith('ey'):
        return speechsdk.SpeechConfig(auth_token=_cached_speech_key, region=_cached_speech_region)
    return speechsdk.SpeechConfig(subscription=_cached_speech_key, region=_cached_speech_region)


def _detect_language(text):
    """Detect whether text is German or English."""
    text_lower = text.lower()
    german_indicators = [
        'der', 'die', 'das', 'und', 'ist', 'ein', 'eine', 'ich', 'du', 'sie',
        'werden', 'wurde', 'können', 'möchten', 'bitte', 'auf', 'zu', 'von',
        'mit', 'für', 'auch', 'nicht', 'werden', 'haben', 'sein', 'als',
        'öffne', 'klicken', 'gehe', 'suche', 'schließe', 'einen', 'neuen',
        'alle', 'cookies', 'zulassen', 'snapshot', 'seite', 'machen', 'dann',
        'alles', 'klar', 'möchtest', 'dass', 'aktuellen', 'etwas', 'anderes'
    ]
    has_german_words = any(word in text_lower.split() for word in german_indicators)
    has_umlauts = any(char in text_lower for char in ['ä', 'ö', 'ü', 'ß'])
    return has_german_words or has_umlauts


def _get_synthesizer(voice_name):
    """Get or create a cached SpeechSynthesizer for the given voice."""
    if voice_name not in _cached_synthesizers:
        try:
            speech_config = _get_speech_config()
        except ValueError:
            return None
        speech_config.speech_synthesis_voice_name = voice_name
        # Use Opus for ~80-90% smaller audio than WAV
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Ogg24Khz16BitMonoOpus
        )
        _cached_synthesizers[voice_name] = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=None
        )
        print(f"[TTS] Cached synthesizer for {voice_name} (Opus)")
    return _cached_synthesizers[voice_name]


def _synthesize_speech(text):
    """Synthesize speech from text synchronously. Returns Opus/OGG bytes or None on failure."""
    voice = "de-DE-KatjaNeural" if _detect_language(text) else "en-US-AriaNeural"
    synthesizer = _get_synthesizer(voice)
    if not synthesizer:
        return None

    # Use SSML with slightly faster rate for snappier responses
    lang = 'de-DE' if 'de-DE' in voice else 'en-US'
    ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
            f'<voice name="{voice}">{xml_escape(text)}</voice></speak>')
    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    print(f"[TTS] Synthesis failed: {result.reason}")
    return None


class ChatRequest(BaseModel):
    message: str
    agentId: str
    threadId: Optional[str] = None


class TextToSpeechRequest(BaseModel):
    text: str
    speechKey: Optional[str] = None
    speechRegion: Optional[str] = None


@app.get("/")
async def read_root():
    """Serve the main HTML page"""
    return FileResponse(static_path / "index.html")


@app.get("/app.js")
async def read_app_js():
    """Serve the JavaScript file"""
    return FileResponse(static_path / "app.js", media_type="application/javascript")


@app.post("/api/speech-to-text")
async def speech_to_text(
    audio: UploadFile = File(...),
    speechKey: str = Form(None),
    speechRegion: str = Form(None)
):
    """Convert speech audio to text using Azure Speech Services"""
    temp_audio_path = None
    temp_wav_path = None
    try:
        speechKey = speechKey if speechKey and speechKey.strip() else None
        speechRegion = speechRegion if speechRegion and speechRegion.strip() else None
        
        # Save uploaded file
        temp_audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
        content = await audio.read()
        temp_audio_path.write(content)
        temp_audio_path.close()
        
        # Convert to 16kHz, 16-bit, mono PCM WAV format
        try:
            audio_segment = AudioSegment.from_file(temp_audio_path.name)
            audio_segment = audio_segment.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            
            temp_wav_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            temp_wav_path.close()
            audio_segment.export(temp_wav_path.name, format="wav")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid audio format: {str(e)}")
        
        # Use cached speech credentials
        try:
            speech_config = _get_speech_config(speechKey, speechRegion)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        speech_config.speech_recognition_language = "en-US"
        audio_config = speechsdk.AudioConfig(filename=temp_wav_path.name)
        speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        
        result = speech_recognizer.recognize_once()
        
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            print(f"[STT] {result.text}")
            return {"text": result.text}
        elif result.reason == speechsdk.ResultReason.NoMatch:
            raise HTTPException(status_code=400, detail="No speech recognized")
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation = result.cancellation_details
            raise HTTPException(status_code=500, detail=f"Recognition canceled: {cancellation.reason}")
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] STT: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_audio_path and os.path.exists(temp_audio_path.name):
            os.unlink(temp_audio_path.name)
        if temp_wav_path and os.path.exists(temp_wav_path.name):
            os.unlink(temp_wav_path.name)


@app.websocket("/ws/speech-stream")
async def speech_stream_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time streaming speech recognition.
    
    Protocol:
    1. Client connects and sends initial config message: {"type": "config", "speechKey": "...", "speechRegion": "..."}
    2. Client streams audio chunks as binary data
    3. Server sends back:
       - {"type": "recognizing", "text": "..."} - partial results
       - {"type": "recognized", "text": "..."} - final results
       - {"type": "session_stopped"} - recognition ended
       - {"type": "error", "message": "..."} - errors
    4. Client sends {"type": "stop"} to end recognition
    """
    await websocket.accept()
    print("[WebSocket] Client connected")
    
    speech_recognizer = None
    stream = None
    recognition_active = False
    ws_alive = True  # Track whether the WS connection should stay open
    
    try:
        # Wait for configuration message
        config_msg = await websocket.receive_json()
        if config_msg.get("type") != "config":
            await websocket.send_json({"type": "error", "message": "First message must be config"})
            await websocket.close()
            return
        
        speech_key = config_msg.get("speechKey")
        speech_region = config_msg.get("speechRegion")
        
        # Use cached speech credentials
        try:
            speech_config = _get_speech_config(speech_key, speech_region)
        except ValueError as e:
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close()
            return
        
        speech_config.speech_recognition_language = "de-DE"
        
        # Configure silence detection for auto-stop
        speech_config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "700"
        )
        
        # Enable detailed recognition results for better accuracy
        speech_config.output_format = speechsdk.OutputFormat.Detailed
        
        # Pre-create conversation thread so the first voice request is faster
        agent_id = config_msg.get("agentId")
        if agent_id and _openai_client:
            thread_key = f"{agent_id}_default"
            if thread_key not in conversation_threads:
                try:
                    conversation = await _openai_client.conversations.create()
                    conversation_threads[thread_key] = conversation.id
                    print(f"[Agent] Pre-created conversation thread for {agent_id}")
                except Exception as e:
                    print(f"[Agent] Warning: could not pre-create conversation: {e}")
        
        # URL correction mapping for common misrecognitions
        url_corrections = {
            "karlstadt": "karlstorz",
            "karlstadt.com": "karlstorz.com",
            "karlstads": "karlstorz",
            "karlstads.com": "karlstorz.com",
            "karl stadt": "karl storz",
            "karl stads": "karl storz",
            "kalchdorj": "karlstorz",
            "kalchdorj.com": "karlstorz.com",
            "carlstadt": "karlstorz",
            "carlstads": "karlstorz",
        }
        
        def apply_url_corrections(text):
            """Apply URL corrections to recognized text"""
            corrected = text
            for wrong, correct in url_corrections.items():
                corrected = re.sub(re.escape(wrong), correct, corrected, flags=re.IGNORECASE)
            return corrected
        
        # asyncio.Queue for instant message passing from SDK callbacks to WebSocket
        message_queue = asyncio.Queue()
        ws_loop = asyncio.get_event_loop()
        user_text_parts = []  # Accumulate all recognized text
        silence_detected = threading.Event()
        
        def setup_recognizer():
            """Create the speech recognizer with stream, phrase hints, and event handlers."""
            nonlocal stream, speech_recognizer
            
            auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=["de-DE", "en-US"]
            )
            stream_format = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
            stream = speechsdk.audio.PushAudioInputStream(stream_format)
            audio_config = speechsdk.audio.AudioConfig(stream=stream)
            
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                audio_config=audio_config,
                auto_detect_source_language_config=auto_detect_config
            )
            
            phrase_list_grammar = speechsdk.PhraseListGrammar.from_recognizer(speech_recognizer)
            url_phrases = [
                "karlstorz.com", "karlstorz", "Karlstorz", "karl storz", "Karl Storz",
                "KARL STORZ", "karlstorz dot com", "karl storz dot com", "kalstorz",
                "kalstorz.com", "carlstorz", "carlstorz.com",
                "karlstads.com", "karlstads", "karl stads",
                "github.com", "google.com", "youtube.com", "microsoft.com",
                "azure.com", "openai.com", "linkedin.com", "gmail.com",
                "outlook.com", "docs.microsoft.com", "stackoverflow.com",
                "reddit.com", "twitter.com", "facebook.com", "instagram.com",
                # German lighting/scene phrases to help auto-detect pick German
                "Standby Modus", "Standby-Modus", "Laparoskopie", "Laparoskopie Modus",
                "Operationsmodus", "Vorbereitungsmodus", "Notfall", "Notfallbeleuchtung",
                "Chirurgiemodus", "full surgery", "full surgery Modus",
                "bitte wechseln", "bitte auf", "wechseln", "umschalten",
                "Licht", "Lichter", "heller", "dunkler", "dimmen",
            ]
            for phrase in url_phrases:
                phrase_list_grammar.addPhrase(phrase)
            
            def recognizing_handler(evt):
                if evt.result.text:
                    corrected_text = apply_url_corrections(evt.result.text)
                    ws_loop.call_soon_threadsafe(message_queue.put_nowait, {"type": "recognizing", "text": corrected_text})
                    print(f"[Recognizing] {corrected_text}")
            
            def recognized_handler(evt):
                if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                    corrected_text = apply_url_corrections(evt.result.text)
                    user_text_parts.append(corrected_text)
                    ws_loop.call_soon_threadsafe(message_queue.put_nowait, {"type": "recognized", "text": corrected_text})
                    print(f"[Recognized] {corrected_text}")
                    silence_detected.set()
            
            def canceled_handler(evt):
                if evt.result.reason == speechsdk.ResultReason.Canceled:
                    cancellation = evt.result.cancellation_details
                    ws_loop.call_soon_threadsafe(message_queue.put_nowait, {"type": "error", "message": f"Recognition canceled: {cancellation.reason}"})
                    print(f"[Canceled] {cancellation.reason}")
            
            speech_recognizer.recognizing.connect(recognizing_handler)
            speech_recognizer.recognized.connect(recognized_handler)
            speech_recognizer.canceled.connect(canceled_handler)
            
            print(f"[Recognition] New recognizer created")
        
        def restart_recognizer():
            """Restart recognition by reusing the recognizer — just stop/start."""
            nonlocal recognition_active
            # Just restart continuous recognition on the same recognizer+stream.
            # Audio is gated by recognition_active so no stale data enters the stream.
            speech_recognizer.start_continuous_recognition()
            recognition_active = True
            print(f"[Recognition] Restarted (reused)")
        
        # Initial recognizer setup
        setup_recognizer()
        speech_recognizer.start_continuous_recognition()
        recognition_active = True
        print("[Recognition] Started")
        
        await websocket.send_json({"type": "ready"})
        
        # Background task to send queued messages to WebSocket
        async def send_queued_messages():
            while ws_alive or not message_queue.empty():
                try:
                    message = await asyncio.wait_for(message_queue.get(), timeout=0.5)
                    await websocket.send_json(message)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f"[WebSocket] Error sending message: {e}")
                    break
        
        # Start the message sender task
        sender_task = asyncio.create_task(send_queued_messages())
        
        # Helper function to process complete user input and get agent response
        async def process_with_agent(user_text, agent_id):
            try:
                t_start = time.time()
                t_agent_start = t_start
                await websocket.send_json({"type": "processing", "text": user_text})
                print(f"[Agent] Processing: {user_text}")
                
                if not agent_id:
                    await websocket.send_json({"type": "agent_response_complete"})
                    return
                
                if not _openai_client:
                    await websocket.send_json({"type": "error", "message": "AI client not initialized"})
                    return
                
                # Get or create conversation
                thread_key = f"{agent_id}_default"
                if thread_key not in conversation_threads:
                    conversation = await _openai_client.conversations.create()
                    conversation_threads[thread_key] = conversation.id
                
                conversation_id = conversation_threads[thread_key]
                
                # Build initial request kwargs
                call_input = user_text
                use_previous = thread_key in last_response_ids
                
                # Streaming agent call with MCP approval loop
                max_retries = 2
                max_approval_iterations = 10
                agent_response_text = ""
                first_sentence_task = None
                first_sentence = ""
                
                for attempt in range(max_retries + 1):
                    try:
                        approval_iteration = 0
                        while True:
                            # Build request
                            kwargs = {
                                "extra_body": {"agent": {"name": agent_id, "type": "agent_reference"}},
                                "input": call_input,
                                "stream": True,
                            }
                            if use_previous and thread_key in last_response_ids:
                                kwargs["previous_response_id"] = last_response_ids[thread_key]
                            else:
                                kwargs["conversation"] = conversation_id
                            
                            # Stream the response, start TTS on first sentence
                            response = None
                            streamed_text = ""
                            tts_started = False
                            first_sentence_task = None
                            t_agent_start = time.time()
                            async for event in await _openai_client.responses.create(**kwargs):
                                event_type = getattr(event, 'type', '')
                                
                                if event_type == 'response.output_text.delta':
                                    streamed_text += event.delta
                                    await websocket.send_json({
                                        "type": "agent_response_chunk",
                                        "text": event.delta
                                    })
                                    # Start TTS as soon as first sentence is complete
                                    if not tts_started and any(c in streamed_text for c in '.!?'):
                                        tts_started = True
                                        first_sentence = streamed_text
                                        loop = asyncio.get_event_loop()
                                        first_sentence_task = loop.run_in_executor(None, _synthesize_speech, first_sentence)
                                elif event_type == 'response.mcp_call.in_progress':
                                    tool_name = getattr(event, 'name', 'tool')
                                    await websocket.send_json({
                                        "type": "agent_thinking",
                                        "message": f"Using tool: {tool_name}"
                                    })
                                elif event_type == 'response.completed':
                                    response = event.response
                            
                            if not response:
                                break
                            
                            last_response_ids[thread_key] = response.id
                            use_previous = True
                            
                            # Check for MCP approval requests
                            approval_requests = [
                                item for item in (response.output or [])
                                if hasattr(item, 'type') and item.type == 'mcp_approval_request'
                            ]
                            
                            if not approval_requests:
                                # Done - extract final text
                                agent_response_text = streamed_text or response.output_text or ""
                                break
                            
                            approval_iteration += 1
                            if approval_iteration > max_approval_iterations:
                                agent_response_text = streamed_text or response.output_text or ""
                                break
                            
                            # Auto-approve and continue
                            tool_names = ', '.join(a.name for a in approval_requests)
                            await websocket.send_json({
                                "type": "agent_thinking",
                                "message": f"Using {len(approval_requests)} tool(s): {tool_names}"
                            })
                            print(f"[MCP] Auto-approving {len(approval_requests)} tool(s): {tool_names}")
                            
                            call_input = [{
                                "type": "mcp_approval_response",
                                "approve": True,
                                "approval_request_id": approval.id
                            } for approval in approval_requests]
                        
                        # Success - break out of retry loop
                        break
                        
                    except Exception as tool_err:
                        err_str = str(tool_err)
                        is_tool_error = 'tool_user_error' in err_str or 'Error encountered while invoking tool' in err_str
                        if is_tool_error and attempt < max_retries:
                            backoff = 1 * (attempt + 1)
                            print(f"[Agent] Tool error (attempt {attempt + 1}/{max_retries + 1}), retrying in {backoff}s: {err_str[:120]}")
                            await websocket.send_json({
                                "type": "agent_thinking",
                                "message": f"Tool timed out, retrying ({attempt + 2}/{max_retries + 1})..."
                            })
                            await asyncio.sleep(backoff)
                            continue
                        raise
                
                # Send response complete immediately (don't block on TTS)
                t_agent_done = time.time()
                print(f"[Agent] Response ({(t_agent_done - t_agent_start)*1000:.0f}ms agent, {(t_agent_done - t_start)*1000:.0f}ms total): {agent_response_text}")
                await websocket.send_json({"type": "agent_response_complete", "full_text": agent_response_text})
                
                # TTS: use early first-sentence audio if available, synthesize remainder
                if agent_response_text:
                    async def _tts_background(full_text, early_task, early_text):
                        try:
                            loop = asyncio.get_event_loop()
                            if early_task:
                                # We already started synthesizing the first sentence
                                first_audio = await early_task
                                remainder = full_text[len(early_text):].strip()
                                if first_audio:
                                    # Send first sentence audio immediately
                                    audio_b64 = base64.b64encode(first_audio).decode('ascii')
                                    await websocket.send_json({"type": "tts_audio", "audio": audio_b64})
                                    print(f"[TTS] Sent first sentence ({len(first_audio)} bytes, {(time.time() - t_start)*1000:.0f}ms from start)")
                                    # Synthesize and send remainder if any
                                    if remainder:
                                        rest_audio = await loop.run_in_executor(None, _synthesize_speech, remainder)
                                        if rest_audio:
                                            rest_b64 = base64.b64encode(rest_audio).decode('ascii')
                                            await websocket.send_json({"type": "tts_audio", "audio": rest_b64})
                                            print(f"[TTS] Sent remainder ({len(rest_audio)} bytes, {(time.time() - t_start)*1000:.0f}ms from start)")
                                    return
                            # Fallback: synthesize full text
                            audio_data = await loop.run_in_executor(None, _synthesize_speech, full_text)
                            if audio_data:
                                audio_b64 = base64.b64encode(audio_data).decode('ascii')
                                await websocket.send_json({"type": "tts_audio", "audio": audio_b64})
                                print(f"[TTS] Sent full ({len(audio_data)} bytes, {(time.time() - t_start)*1000:.0f}ms from start)")
                        except Exception as e:
                            if "close" not in str(e).lower():
                                print(f"[TTS] Background error: {e}")
                    asyncio.create_task(_tts_background(agent_response_text, first_sentence_task, first_sentence))
                    t_agent_start = None  # reset for next turn
                    
            except Exception as e:
                print(f"[Agent] Error: {e}")
                await websocket.send_json({"type": "error", "message": f"Agent error: {str(e)}"})
        
        # Task to monitor silence and auto-send to agent (loops for multiple turns)
        async def silence_monitor():
            nonlocal recognition_active, stream, speech_recognizer
            while ws_alive:
                if silence_detected.is_set():
                    # Brief wait for any trailing recognized events
                    await asyncio.sleep(0.2)
                    if user_text_parts:
                        full_text = " ".join(user_text_parts)
                        user_text_parts.clear()
                        silence_detected.clear()
                        
                        # Stop current recognition (keep recognizer alive for reuse)
                        recognition_active = False
                        t_silence = time.time()
                        try:
                            speech_recognizer.stop_continuous_recognition()
                        except Exception:
                            pass
                        print(f"[Timing] STT stop took {(time.time() - t_silence)*1000:.0f}ms")
                        
                        # Process with agent
                        agent_id = config_msg.get("agentId")
                        await process_with_agent(full_text, agent_id)
                        
                        # Restart recognition on the same recognizer (no reconnect)
                        restart_recognizer()
                        
                        await websocket.send_json({"type": "ready_for_next"})
                    else:
                        silence_detected.clear()
                else:
                    await asyncio.sleep(0.1)
        
        silence_task = asyncio.create_task(silence_monitor())
        
        # Process incoming audio chunks
        while True:
            try:
                message = await websocket.receive()
                
                if "text" in message:
                    # Handle control messages
                    try:
                        msg = json.loads(message["text"])
                        if msg.get("type") == "stop":
                            print("[WebSocket] Stop requested")
                            break
                    except (json.JSONDecodeError, KeyError):
                        pass
                elif "bytes" in message:
                    # Stream audio data to recognizer (only when actively recognizing)
                    if recognition_active:
                        audio_data = message["bytes"]
                        if audio_data and len(audio_data) > 0:
                            try:
                                stream.write(audio_data)
                            except Exception:
                                pass  # Stream may be closing between turns
            
            except WebSocketDisconnect:
                print("[WebSocket] Client disconnected")
                break
            except Exception as e:
                print(f"[WebSocket] Error processing message: {e}")
                break
    
    except WebSocketDisconnect:
        print("[WebSocket] Client disconnected during setup")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        # Cleanup
        ws_alive = False
        recognition_active = False
        
        # Cancel background tasks
        if 'sender_task' in locals():
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass
        
        if 'silence_task' in locals():
            silence_task.cancel()
            try:
                await silence_task
            except asyncio.CancelledError:
                pass
        
        if speech_recognizer:
            try:
                speech_recognizer.stop_continuous_recognition()
                print("[Recognition] Stopped")
            except:
                pass
        
        if stream:
            try:
                stream.close()
            except:
                pass
        
        try:
            await websocket.close()
        except:
            pass


@app.post("/api/agent/chat")
async def chat_with_agent(request: ChatRequest):
    """Send message to Microsoft Foundry Agent and get response"""
    try:
        project_endpoint = os.getenv("PROJECT_ENDPOINT")
        model_deployment_name = os.getenv("MODEL_DEPLOYMENT_NAME")
        
        if not project_endpoint or not model_deployment_name:
            raise HTTPException(status_code=500, detail="Missing Foundry configuration")
        
        print(f"[AGENT] {request.agentId}: {request.message}")
        
        credential = DefaultAzureCredential()
        
        async with AIProjectClient(endpoint=project_endpoint, credential=credential) as project_client:
            openai_client = project_client.get_openai_client()
            
            # Get or create conversation
            thread_key = f"{request.agentId}_{request.threadId or 'default'}"
            if thread_key not in conversation_threads:
                conversation = await openai_client.conversations.create()
                conversation_threads[thread_key] = conversation.id
            
            conversation_id = conversation_threads[thread_key]
            
            # Send message (use previous_response_id if available to maintain approval state)
            if thread_key in last_response_ids:
                response = await openai_client.responses.create(
                    previous_response_id=last_response_ids[thread_key],
                    extra_body={"agent": {"name": request.agentId, "type": "agent_reference"}},
                    input=request.message
                )
            else:
                response = await openai_client.responses.create(
                    conversation=conversation_id,
                    extra_body={"agent": {"name": request.agentId, "type": "agent_reference"}},
                    input=request.message
                )
            
            # Auto-approve MCP tool requests
            max_iterations = 10
            iteration = 0
            
            while iteration < max_iterations:
                approval_requests = [
                    item for item in (response.output or [])
                    if hasattr(item, 'type') and item.type == 'mcp_approval_request'
                ]
                
                if not approval_requests:
                    break
                
                iteration += 1
                print(f"[MCP] Auto-approving {len(approval_requests)} tool(s): {', '.join(a.name for a in approval_requests)}")
                
                approval_inputs = [{
                    "type": "mcp_approval_response",
                    "approve": True,
                    "approval_request_id": approval.id
                } for approval in approval_requests]
                
                response = await openai_client.responses.create(
                    extra_body={"agent": {"name": request.agentId, "type": "agent_reference"}},
                    previous_response_id=response.id,
                    input=approval_inputs
                )
            
            if iteration >= max_iterations:
                print(f"[WARNING] Max approval iterations reached")
            
            # Extract response text
            if response.output_text:
                response_text = response.output_text
            elif response.output:
                text_parts = [
                    getattr(item, 'text', None) or getattr(item, 'content', None)
                    for item in response.output
                ]
                response_text = ' '.join(str(p) for p in text_parts if p) or "Action completed."
            else:
                response_text = "Action completed."
            
            # Store response ID for maintaining approval state
            last_response_ids[thread_key] = response.id
            
            print(f"[RESPONSE] {response_text[:100]}...")
            return {"response": response_text, "threadId": thread_key}
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Agent: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/text-to-speech")
async def text_to_speech(request: TextToSpeechRequest):
    """Convert text to speech using Azure Speech Services"""
    
    temp_audio_path = None
    try:
        # Create temp file for audio output
        temp_audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_audio_path.close()
        
        # Use cached speech credentials
        try:
            speech_config = _get_speech_config(
                request.speechKey if request.speechKey else None,
                request.speechRegion if request.speechRegion else None
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        is_german = _detect_language(request.text)
        
        # Select voice based on detected language
        if is_german:
            speech_config.speech_synthesis_voice_name = "de-DE-KatjaNeural"
            print(f"[TTS] Using German voice for: {request.text[:50]}...")
        else:
            speech_config.speech_synthesis_voice_name = "en-US-AriaNeural"
            print(f"[TTS] Using English voice for: {request.text[:50]}...")
        
        audio_config = speechsdk.AudioConfig(filename=temp_audio_path.name)
        speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
        
        result = speech_synthesizer.speak_text_async(request.text).get()
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            def iterfile():
                with open(temp_audio_path.name, "rb") as f:
                    yield from f
                os.unlink(temp_audio_path.name)
            
            return StreamingResponse(iterfile(), media_type="audio/wav")
        else:
            raise HTTPException(status_code=500, detail="Speech synthesis failed")
    
    except HTTPException:
        raise
    except Exception as e:
        if temp_audio_path and os.path.exists(temp_audio_path.name):
            os.unlink(temp_audio_path.name)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/agent/thread/{thread_id}")
async def clear_thread(thread_id: str):
    """Clear conversation thread"""
    thread_keys_to_delete = [k for k in conversation_threads.keys() if thread_id in k]
    for key in thread_keys_to_delete:
        if key in conversation_threads:
            del conversation_threads[key]
        if key in last_response_ids:
            del last_response_ids[key]
    return {"status": "cleared"}


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}


# --- OR Light State ---
# Read shared light state written by the OR Lights MCP server

OR_LIGHTS_STATE_FILE = Path(__file__).parent / ".or_lights_state.json"

@app.get("/api/lights/state")
async def get_light_state():
    """Get current light state from the shared state file."""
    try:
        if OR_LIGHTS_STATE_FILE.exists():
            return json.loads(OR_LIGHTS_STATE_FILE.read_text())
        return {}
    except Exception:
        return {}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

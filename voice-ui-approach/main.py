"""
Voice Agent Backend - FastAPI Server
This server handles:
1. Speech-to-text conversion using Azure Speech Services
2. Communication with Microsoft Foundry Agent
3. Text-to-speech conversion for agent responses
"""

import os
import uuid
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
from pydub import AudioSegment
from azure.ai.projects.aio import AIProjectClient
import queue
import threading

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
    
    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    if project_endpoint:
        try:
            _credential = DefaultAzureCredential()
            _project_client = AIProjectClient(endpoint=project_endpoint, credential=_credential)
            _openai_client = _project_client.get_openai_client()
            print("[Startup] AI Project Client initialized successfully")
        except Exception as e:
            print(f"[Startup] Warning: Could not initialize AI Project Client: {e}")

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

# Get the directory where main.py is located
static_path = Path(__file__).parent


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
        
        # Configure Azure Speech Services
        project_endpoint = os.getenv("PROJECT_ENDPOINT")
        env_speech_key = os.getenv("SPEECH_KEY")
        env_speech_region = os.getenv("SPEECH_REGION")
        
        if speechKey and speechRegion:
            speech_config = speechsdk.SpeechConfig(subscription=speechKey, region=speechRegion)
        elif env_speech_key and env_speech_region:
            speech_config = speechsdk.SpeechConfig(subscription=env_speech_key, region=env_speech_region)
        elif project_endpoint:
            match = re.search(r'https://([^.]+)\.services\.ai\.azure\.com', project_endpoint)
            if not match:
                raise HTTPException(status_code=500, detail="Invalid PROJECT_ENDPOINT format")
            
            resource_name = match.group(1)
            region = 'swedencentral'
            
            # Try to get subscription key, fallback to token auth
            import subprocess
            try:
                result = subprocess.run(
                    ['az', 'cognitiveservices', 'account', 'keys', 'list',
                     '--name', resource_name, '--resource-group', 'aullah-foundry-resource-group',
                     '--query', 'key1', '-o', 'tsv'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    speech_config = speechsdk.SpeechConfig(subscription=result.stdout.strip(), region=region)
                else:
                    raise Exception("Key not found")
            except Exception:
                credential = SyncDefaultAzureCredential()
                token = credential.get_token("https://cognitiveservices.azure.com/.default")
                speech_config = speechsdk.SpeechConfig(auth_token=token.token, region=region)
        else:
            raise HTTPException(status_code=400, detail="Missing speech credentials")
        
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
    
    try:
        # Wait for configuration message
        config_msg = await websocket.receive_json()
        if config_msg.get("type") != "config":
            await websocket.send_json({"type": "error", "message": "First message must be config"})
            await websocket.close()
            return
        
        speech_key = config_msg.get("speechKey")
        speech_region = config_msg.get("speechRegion")
        
        # Configure Speech Services
        project_endpoint = os.getenv("PROJECT_ENDPOINT")
        env_speech_key = os.getenv("SPEECH_KEY")
        env_speech_region = os.getenv("SPEECH_REGION")
        
        if speech_key and speech_region:
            speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        elif env_speech_key and env_speech_region:
            speech_config = speechsdk.SpeechConfig(subscription=env_speech_key, region=env_speech_region)
        elif project_endpoint:
            match = re.search(r'https://([^.]+)\.services\.ai\.azure\.com', project_endpoint)
            if not match:
                await websocket.send_json({"type": "error", "message": "Invalid PROJECT_ENDPOINT format"})
                await websocket.close()
                return
            
            resource_name = match.group(1)
            region = 'swedencentral'
            
            # Try to get subscription key, fallback to token auth
            import subprocess
            try:
                result = subprocess.run(
                    ['az', 'cognitiveservices', 'account', 'keys', 'list',
                     '--name', resource_name, '--resource-group', 'aullah-foundry-resource-group',
                     '--query', 'key1', '-o', 'tsv'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    speech_config = speechsdk.SpeechConfig(subscription=result.stdout.strip(), region=region)
                else:
                    raise Exception("Key not found")
            except Exception:
                credential = SyncDefaultAzureCredential()
                token = credential.get_token("https://cognitiveservices.azure.com/.default")
                speech_config = speechsdk.SpeechConfig(auth_token=token.token, region=region)
        else:
            await websocket.send_json({"type": "error", "message": "Missing speech credentials"})
            await websocket.close()
            return
        
        # Enable multilingual recognition (German and English)
        # Use auto-detect to automatically switch between languages
        auto_detect_source_language_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=["de-DE", "en-US"]
        )
        
        speech_config.speech_recognition_language = "de-DE"  # Default to German
        
        # Configure silence detection for auto-stop
        # Stop recognition after 1.5 seconds of silence at end of phrase
        speech_config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "1500"
        )
        
        # Enable detailed recognition results for better accuracy
        speech_config.output_format = speechsdk.OutputFormat.Detailed
        
        # Create push audio stream (16kHz, 16-bit, mono PCM)
        stream_format = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
        stream = speechsdk.audio.PushAudioInputStream(stream_format)
        audio_config = speechsdk.audio.AudioConfig(stream=stream)
        
        # Create recognizer with auto language detection
        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_detect_source_language_config
        )
        
        # Add phrase hints for better recognition of URLs and specific terms
        # Note: PhraseListGrammar works best with continuous recognition
        phrase_list_grammar = speechsdk.PhraseListGrammar.from_recognizer(speech_recognizer)
        
        # Add common URL patterns and company names with phonetic variations
        url_phrases = [
            # Karlstorz variations (main target)
            "karlstorz.com",
            "karlstorz",
            "Karlstorz",
            "karl storz",
            "Karl Storz",
            "KARL STORZ",
            "karlstorz dot com",
            "karl storz dot com",
            "kalstorz",
            "kalstorz.com",
            "carlstorz",
            "carlstorz.com",
            # Karlstads variations
            "karlstads.com",
            "karlstads",
            "karl stads",
            # Common domains
            "github.com",
            "google.com",
            "youtube.com",
            "microsoft.com",
            "azure.com",
            "openai.com",
            "linkedin.com",
            "gmail.com",
            "outlook.com",
            "docs.microsoft.com",
            "stackoverflow.com",
            "reddit.com",
            "twitter.com",
            "facebook.com",
            "instagram.com",
        ]
        
        for phrase in url_phrases:
            phrase_list_grammar.addPhrase(phrase)
        
        print(f"[Recognition] Added {len(url_phrases)} phrase hints for better URL recognition")
        
        # Set recognition mode to prioritize phrase list matches
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceResponse_PostProcessingOption,
            "TrueText"
        )
        
        # Create a thread-safe queue for passing messages from SDK callbacks to WebSocket
        message_queue = queue.Queue()
        user_text_parts = []  # Accumulate all recognized text
        silence_detected = threading.Event()
        
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
                # Case-insensitive replacement
                import re
                corrected = re.sub(re.escape(wrong), correct, corrected, flags=re.IGNORECASE)
            return corrected
        
        # Set up event handlers
        def recognizing_handler(evt):
            """Handle partial recognition results"""
            if evt.result.text:
                corrected_text = apply_url_corrections(evt.result.text)
                message_queue.put({
                    "type": "recognizing",
                    "text": corrected_text
                })
                print(f"[Recognizing] {corrected_text}")
        
        def recognized_handler(evt):
            """Handle final recognition results"""
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
                corrected_text = apply_url_corrections(evt.result.text)
                user_text_parts.append(corrected_text)
                message_queue.put({
                    "type": "recognized",
                    "text": corrected_text
                })
                print(f"[Recognized] {corrected_text}")
                # Signal that we got a final phrase - will auto-send to agent after silence
                silence_detected.set()
        
        def canceled_handler(evt):
            """Handle recognition cancellation"""
            if evt.result.reason == speechsdk.ResultReason.Canceled:
                cancellation = evt.result.cancellation_details
                message_queue.put({
                    "type": "error",
                    "message": f"Recognition canceled: {cancellation.reason}"
                })
                print(f"[Canceled] {cancellation.reason}")
        
        def session_stopped_handler(evt):
            """Handle session stop"""
            message_queue.put({"type": "session_stopped"})
            print("[Session] Stopped")
        
        # Connect event handlers
        speech_recognizer.recognizing.connect(recognizing_handler)
        speech_recognizer.recognized.connect(recognized_handler)
        speech_recognizer.canceled.connect(canceled_handler)
        speech_recognizer.session_stopped.connect(session_stopped_handler)
        
        # Start continuous recognition
        speech_recognizer.start_continuous_recognition()
        recognition_active = True
        print("[Recognition] Started")
        
        await websocket.send_json({"type": "ready"})
        
        # Background task to send queued messages to WebSocket
        async def send_queued_messages():
            while recognition_active or not message_queue.empty():
                try:
                    # Non-blocking get with timeout
                    message = message_queue.get(timeout=0.1)
                    await websocket.send_json(message)
                except queue.Empty:
                    await asyncio.sleep(0.05)
                except Exception as e:
                    print(f"[WebSocket] Error sending message: {e}")
                    break
        
        # Start the message sender task
        sender_task = asyncio.create_task(send_queued_messages())
        
        # Helper function to process complete user input and get agent response
        async def process_with_agent(user_text, agent_id):
            try:
                await websocket.send_json({"type": "processing", "text": user_text})
                print(f"[Agent] Processing: {user_text}")
                
                # Get agent ID from config message if provided
                if not agent_id:
                    await websocket.send_json({"type": "agent_response_complete"})
                    return
                
                # Send to agent - use reusable client for better performance
                if not _openai_client:
                    await websocket.send_json({"type": "error", "message": "AI client not initialized"})
                    return
                
                # Get or create conversation
                thread_key = f"{agent_id}_default"
                if thread_key not in conversation_threads:
                    conversation = await _openai_client.conversations.create()
                    conversation_threads[thread_key] = conversation.id
                
                conversation_id = conversation_threads[thread_key]
                
                # Send message to agent
                if thread_key in last_response_ids:
                    response = await _openai_client.responses.create(
                        previous_response_id=last_response_ids[thread_key],
                        extra_body={"agent": {"name": agent_id, "type": "agent_reference"}},
                        input=user_text
                    )
                else:
                    response = await _openai_client.responses.create(
                        conversation=conversation_id,
                        extra_body={"agent": {"name": agent_id, "type": "agent_reference"}},
                        input=user_text
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
                    
                    # Show tool usage feedback
                    tool_names = ', '.join(a.name for a in approval_requests)
                    await websocket.send_json({
                        "type": "agent_thinking",
                        "message": f"Using {len(approval_requests)} tool(s): {tool_names}"
                    })
                    print(f"[MCP] Auto-approving {len(approval_requests)} tool(s): {tool_names}")
                    
                    # Create approval responses
                    approval_inputs = [{
                        "type": "mcp_approval_response",
                        "approve": True,
                        "approval_request_id": approval.id
                    } for approval in approval_requests]
                    
                    response = await _openai_client.responses.create(
                        extra_body={"agent": {"name": agent_id, "type": "agent_reference"}},
                        previous_response_id=response.id,
                        input=approval_inputs
                    )
                
                last_response_ids[thread_key] = response.id
                
                # Extract and stream agent response text
                agent_response_text = ""
                if response.output_text:
                    agent_response_text = response.output_text
                elif response.output:
                    for item in response.output:
                        text = getattr(item, 'text', None) or getattr(item, 'content', None)
                        if text:
                            agent_response_text += str(text)
                
                # Stream response in chunks for better UX (no artificial delay)
                if agent_response_text:
                    # Split into words for streaming effect
                    words = agent_response_text.split()
                    chunk_size = 5  # Send 5 words at a time (increased from 3)
                    for i in range(0, len(words), chunk_size):
                        chunk = ' '.join(words[i:i+chunk_size]) + ' '
                        await websocket.send_json({
                            "type": "agent_response_chunk",
                            "text": chunk
                        })
                        # No sleep - stream immediately for faster response
                
                print(f"[Agent] Response: {agent_response_text}")
                await websocket.send_json({"type": "agent_response_complete", "full_text": agent_response_text})
                    
            except Exception as e:
                print(f"[Agent] Error: {e}")
                await websocket.send_json({"type": "error", "message": f"Agent error: {str(e)}"})
        
        # Task to monitor silence and auto-send to agent
        async def silence_monitor():
            while recognition_active:
                if silence_detected.is_set():
                    # Wait a bit for any final recognized events
                    await asyncio.sleep(0.5)
                    if user_text_parts:
                        full_text = " ".join(user_text_parts)
                        user_text_parts.clear()
                        silence_detected.clear()
                        
                        # Stop continuous recognition to prevent echo
                        speech_recognizer.stop_continuous_recognition()
                        
                        # Close the audio stream to stop accepting new audio
                        stream.close()
                        
                        # Send to agent
                        agent_id = config_msg.get("agentId")
                        await process_with_agent(full_text, agent_id)
                        
                        # Signal that we're done - client should reconnect for next input
                        await websocket.send_json({"type": "ready_for_next"})
                        break  # Exit silence monitor
                else:
                    await asyncio.sleep(0.1)
        
        silence_task = asyncio.create_task(silence_monitor())
        
        # Process incoming audio chunks
        while True:
            try:
                message = await websocket.receive()
                
                if "text" in message:
                    # Handle control messages
                    msg = await websocket.receive_json()
                    if msg.get("type") == "stop":
                        print("[WebSocket] Stop requested")
                        break
                elif "bytes" in message:
                    # Stream audio data to recognizer
                    audio_data = message["bytes"]
                    if audio_data and len(audio_data) > 0:
                        stream.write(audio_data)
            
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
        
        # Try to use multi-service account from environment first
        project_endpoint = os.getenv("PROJECT_ENDPOINT")
        env_speech_key = os.getenv("SPEECH_KEY")
        env_speech_region = os.getenv("SPEECH_REGION")
        
        # Configure Azure Speech
        if request.speechKey and request.speechRegion:
            # Use provided key and region from UI
            speech_config = speechsdk.SpeechConfig(
                subscription=request.speechKey,
                region=request.speechRegion
            )
        elif env_speech_key and env_speech_region:
            # Use credentials from .env file
            speech_config = speechsdk.SpeechConfig(
                subscription=env_speech_key,
                region=env_speech_region
            )
        elif project_endpoint:
            match = re.search(r'https://([^.]+)\.services\.ai\.azure\.com', project_endpoint)
            if not match:
                raise HTTPException(status_code=500, detail="Invalid PROJECT_ENDPOINT format")
            
            resource_name = match.group(1)
            region = 'swedencentral'
            
            credential = SyncDefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            speech_config = speechsdk.SpeechConfig(auth_token=token.token, region=region)
        else:
            raise HTTPException(status_code=400, detail="Missing speech credentials")
        
        # Auto-detect language and select appropriate voice
        text_lower = request.text.lower()
        
        # Enhanced language detection based on common German words and characters
        german_indicators = [
            'der', 'die', 'das', 'und', 'ist', 'ein', 'eine', 'ich', 'du', 'sie', 
            'werden', 'wurde', 'können', 'möchten', 'bitte', 'auf', 'zu', 'von',
            'mit', 'für', 'auch', 'nicht', 'werden', 'haben', 'sein', 'als',
            'öffne', 'klicken', 'gehe', 'suche', 'schließe', 'einen', 'neuen',
            'alle', 'cookies', 'zulassen', 'snapshot', 'seite', 'machen', 'dann',
            'alles', 'klar', 'möchtest', 'dass', 'aktuellen', 'etwas', 'anderes'
        ]
        
        # Check for German words or umlauts (ä, ö, ü, ß)
        has_german_words = any(word in text_lower.split() for word in german_indicators)
        has_umlauts = any(char in text_lower for char in ['ä', 'ö', 'ü', 'ß'])
        is_german = has_german_words or has_umlauts
        
        # Select voice based on detected language
        if is_german:
            # Use German neural voice
            speech_config.speech_synthesis_voice_name = "de-DE-KatjaNeural"
            print(f"[TTS] Using German voice for: {request.text[:50]}...")
        else:
            # Use English neural voice
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

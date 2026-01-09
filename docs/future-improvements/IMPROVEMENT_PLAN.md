# Voice Agent Improvement Plan

## 1. Real-Time Streaming Speech Recognition

### Current Implementation
- **Mode**: Single-shot recognition (`recognize_once_async`)
- **Flow**: Record → Stop → Upload full audio → Get result
- **Latency**: High (waits for complete audio)
- **User Experience**: Press mic → speak → press stop → wait

### Proposed Implementation: Continuous Recognition
- **Mode**: Streaming continuous recognition
- **Flow**: Real-time audio streaming with intermediate results
- **Latency**: Low (partial results appear while speaking)
- **User Experience**: Press mic → speak → see words appear in real-time → auto-detect end

### Technical Approach

#### Backend Changes (main.py)
Replace single-shot with continuous recognition:
```python
# Instead of recognize_once_async()
speech_recognizer.start_continuous_recognition_async()

# Subscribe to events:
speech_recognizer.recognizing.connect(handler)  # Partial results
speech_recognizer.recognized.connect(handler)   # Final results
speech_recognizer.session_stopped.connect(handler)
```

#### Frontend Changes Required
1. **WebSocket Connection**: Need real-time bidirectional communication
2. **Streaming Audio**: Use MediaRecorder with `ondataavailable` to stream chunks
3. **Progressive UI**: Display partial recognition results as they arrive
4. **Auto-Stop Detection**: End recognition on silence detection

### Implementation Options

#### Option A: Server-Sent Events (SSE) - RECOMMENDED
**Pros**: 
- Simpler than WebSockets
- Built-in browser support
- Sufficient for one-way streaming (server → client)
- FastAPI has good SSE support

**Cons**:
- Need separate upload for audio chunks
- Slightly more complex than current approach

**Implementation**:
```python
from fastapi.responses import StreamingResponse
import asyncio

async def stream_recognition(audio_stream):
    # Setup continuous recognition
    # Yield partial results as they arrive
    async for result in recognition_results:
        yield f"data: {json.dumps(result)}\n\n"
```

#### Option B: WebSockets - FULL DUPLEX
**Pros**:
- True bidirectional real-time communication
- Can stream audio TO server AND results FROM server simultaneously
- Lower latency
- Most similar to Foundry playground

**Cons**:
- More complex implementation
- Requires WebSocket connection management

**Implementation**:
```python
from fastapi import WebSocket

@app.websocket("/ws/speech")
async def websocket_speech(websocket: WebSocket):
    await websocket.accept()
    # Receive audio chunks
    # Stream recognition results back
```

#### Option C: Hybrid - Push Audio, Stream Results
**Pros**:
- Balance of simplicity and real-time results
- Keep current audio upload mechanism
- Add streaming results output

**Recommendation**: **Option A (SSE)** for quick implementation, **Option B (WebSockets)** for best user experience

---

## 2. Improved URL and Technical Term Recognition

### Problem
Speech-to-text struggles with:
- URLs (e.g., "google.com" → "Google dot com")
- Technical terms (e.g., "kubernetes" → "coobernetties")
- Product names (e.g., "GitHub" → "git hub")
- Special formats (e.g., "karlstadz.com" → "Karl's stats dot com")

### Solution: Phrase Lists and Custom Vocabulary

Azure Speech Services supports **PhraseListGrammar** to boost recognition accuracy for specific words/phrases.

### Implementation

#### Backend Addition (main.py)
```python
from azure.cognitiveservices.speech import PhraseListGrammar

def add_custom_vocabulary(speech_recognizer):
    """Add common URLs, technical terms, and product names"""
    phrase_list_grammar = PhraseListGrammar.from_recognizer(speech_recognizer)
    
    # Common URLs
    phrase_list_grammar.addPhrase("google.com")
    phrase_list_grammar.addPhrase("github.com")
    phrase_list_grammar.addPhrase("microsoft.com")
    phrase_list_grammar.addPhrase("karlstadz.com")
    phrase_list_grammar.addPhrase("wikipedia.org")
    phrase_list_grammar.addPhrase("youtube.com")
    
    # URL patterns
    phrase_list_grammar.addPhrase("dot com")
    phrase_list_grammar.addPhrase("dot org")
    phrase_list_grammar.addPhrase("dot io")
    phrase_list_grammar.addPhrase("dot dev")
    phrase_list_grammar.addPhrase("www dot")
    
    # Common browser commands
    phrase_list_grammar.addPhrase("Gmail")
    phrase_list_grammar.addPhrase("YouTube")
    phrase_list_grammar.addPhrase("Google Drive")
    phrase_list_grammar.addPhrase("Stack Overflow")
    
    # Technical terms
    phrase_list_grammar.addPhrase("Playwright")
    phrase_list_grammar.addPhrase("Kubernetes")
    phrase_list_grammar.addPhrase("Docker")
    phrase_list_grammar.addPhrase("GitHub Copilot")
    
    return phrase_list_grammar
```

#### Integration Point
Add after creating `speech_recognizer`:
```python
speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
add_custom_vocabulary(speech_recognizer)  # <-- ADD THIS
result = speech_recognizer.recognize_once()
```

#### Advanced: Context-Aware Vocabulary
```python
# Dynamically add URLs from browser history or user context
def add_contextual_vocabulary(speech_recognizer, context=None):
    phrase_list = PhraseListGrammar.from_recognizer(speech_recognizer)
    
    # If user is on a webpage, add current domain
    if context and 'current_url' in context:
        domain = extract_domain(context['current_url'])
        phrase_list.addPhrase(domain)
    
    # Add recently visited sites
    if context and 'recent_sites' in context:
        for site in context['recent_sites']:
            phrase_list.addPhrase(site)
    
    return phrase_list
```

#### UI Addition
Add settings for custom vocabulary:
```html
<div class="config-section">
    <label>Custom Vocabulary (comma-separated URLs/terms)</label>
    <textarea id="customVocabulary" placeholder="example.com, MyProduct, TechnicalTerm"></textarea>
</div>
```

---

## 3. Combined Implementation: Real-Time + Better Recognition

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Browser                             │
│  ┌────────────────────────────────────────────┐         │
│  │  MediaRecorder → Chunk Stream               │         │
│  │         ↓                                    │         │
│  │  WebSocket/SSE Connection                    │         │
│  └────────────────────────────────────────────┘         │
└───────────────────────┬─────────────────────────────────┘
                        │ Audio Chunks + Metadata
                        ↓
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Backend                        │
│  ┌────────────────────────────────────────────┐         │
│  │  Audio Buffer Management                     │         │
│  │         ↓                                    │         │
│  │  Azure Speech Continuous Recognition         │         │
│  │         ↓                                    │         │
│  │  PhraseList Grammar (Custom Vocabulary)      │         │
│  │         ↓                                    │         │
│  │  Recognition Events:                         │         │
│  │    - recognizing (partial)                   │         │
│  │    - recognized (final)                      │         │
│  └────────────────────────────────────────────┘         │
└───────────────────────┬─────────────────────────────────┘
                        │ Recognition Results
                        ↓
┌─────────────────────────────────────────────────────────┐
│              Browser (Progressive UI)                    │
│  ┌────────────────────────────────────────────┐         │
│  │  Display partial text (gray)                 │         │
│  │  Display final text (black)                  │         │
│  │  Auto-detect completion                      │         │
│  └────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────┘
```

### Benefits
1. **Real-time feedback**: See words as you speak
2. **Better accuracy**: Custom vocabulary for URLs and technical terms
3. **Better UX**: No need to manually stop recording
4. **More natural**: Like talking to the Foundry playground

---

## Implementation Phases

### Phase 1: Quick Wins (2-3 hours)
**Goal**: Improve recognition accuracy without changing architecture

1. ✅ Add phrase list grammar for common URLs and terms
2. ✅ Add custom vocabulary input in UI
3. ✅ Test with problematic URLs like "karlstadz.com"

**Files to modify**:
- `main.py`: Add `add_custom_vocabulary()` function
- `index.html`: Add custom vocabulary text input
- `app.js`: Send custom vocabulary to backend

### Phase 2: Streaming Recognition (1-2 days)
**Goal**: Implement real-time continuous recognition

**Option 2A: SSE (Simpler)**
1. Add SSE endpoint for streaming results
2. Modify frontend to stream audio chunks
3. Display partial/final results progressively

**Option 2B: WebSockets (Better UX)**
1. Add WebSocket endpoint
2. Implement bidirectional audio/result streaming
3. Add connection management and recovery

**Files to modify**:
- `main.py`: Add streaming endpoint, continuous recognition
- `app.js`: WebSocket/SSE client, chunk streaming, progressive UI
- `index.html`: Update UI for real-time display

### Phase 3: Polish (1 day)
1. Add silence detection for auto-stop
2. Add visual indicators for recognition state
3. Add settings for recognition parameters
4. Optimize latency and buffering

---

## Configuration Options to Add

### Speech Configuration
```python
# Silence detection
speech_config.set_property(
    speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, 
    "2000"  # 2 seconds of silence to end phrase
)

# Continuous mode optimizations
speech_config.set_property(
    speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
    "5000"  # Wait 5s for speech to start
)

# Enable partial results
speech_config.set_property(
    speechsdk.PropertyId.SpeechServiceResponse_RequestDetailedResultTrueFalse,
    "true"
)
```

---

## Testing Strategy

### Test Cases for URL Recognition
- [ ] "Navigate to google.com" → Should recognize "google.com" not "Google dot com"
- [ ] "Open karlstadz.com" → Should recognize "karlstadz.com" not variations
- [ ] "Go to stack overflow" → Should recognize as one term
- [ ] "Visit github.com slash microsoft" → Should recognize URL structure

### Test Cases for Streaming
- [ ] Partial results appear while speaking
- [ ] Final results replace partial results
- [ ] Multiple sentences handled correctly
- [ ] Silence detection stops recognition
- [ ] Connection recovery after network issues

---

## Resources

### Azure Documentation
- [Continuous Recognition](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech?pivots=programming-language-python#use-continuous-recognition)
- [Phrase Lists](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/improve-accuracy-phrase-list)
- [Custom Speech](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/custom-speech-overview)

### FastAPI Resources
- [WebSocket Support](https://fastapi.tiangolo.com/advanced/websockets/)
- [Server-Sent Events](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse)

---

## Estimated Effort

| Phase | Description | Time | Priority |
|-------|-------------|------|----------|
| Phase 1 | Custom vocabulary/phrase lists | 2-3 hours | HIGH ⭐ |
| Phase 2A | SSE streaming (simpler) | 8 hours | MEDIUM |
| Phase 2B | WebSocket streaming (better) | 16 hours | MEDIUM |
| Phase 3 | Polish & optimization | 8 hours | LOW |

**Recommendation**: Start with **Phase 1** immediately (quick win), then decide between **2A (SSE)** or **2B (WebSockets)** based on user feedback.

---

## Next Steps

1. **Immediate**: Implement Phase 1 (custom vocabulary)
2. **Validate**: Test with your problematic URLs
3. **Decide**: SSE vs WebSockets for streaming based on requirements
4. **Implement**: Phase 2 with user testing
5. **Polish**: Phase 3 based on feedback

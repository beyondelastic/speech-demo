# Future Improvements — Voice Control App

---

## 1. Azure Custom Keyword Wake Word

## Current Implementation (Text-Based)

The current wake word detection uses **STT-based keyword spotting**: the Azure Speech SDK
continuously transcribes all audio, and the backend checks if the transcript starts with
"Computer". If the wake word is detected, the command portion is extracted and processed.

**Pros:**
- Zero external dependencies — uses existing STT pipeline
- Works immediately, no custom model training needed
- Supports both German and English commands after the wake word

**Cons:**
- STT processes ALL audio continuously (higher API usage)
- Slight latency overhead — must wait for STT to transcribe before checking the wake word
- Less robust in noisy environments compared to a dedicated keyword model

## Planned Improvement: Azure Speech Studio Custom Keyword

Azure Speech SDK supports **on-device keyword recognition** via custom `.table` model files
trained in Speech Studio. This runs locally in the browser or on-device before any audio
is sent to the cloud.

### Benefits
- **On-device processing**: Keyword detection runs locally, no cloud round-trip
- **Lower latency**: ~50ms keyword detection vs ~300-500ms for STT transcription
- **Lower cost**: Audio only sent to STT after wake word triggers
- **Better noise rejection**: Trained neural model is more robust than text matching
- **Battery/resource efficient**: Minimal CPU until wake word triggers

### Implementation Plan

1. **Train Custom Keyword Model**
   - Go to [Speech Studio Custom Keyword](https://speech.microsoft.com/portal/customkeyword)
   - Create project with keyword: **"Computer"**
   - Use "Basic" model (free, sufficient for demo)
   - Note: 4-7 syllable keywords recommended, but common words like "Computer" are well-recognized
   - Download the generated `.table` file

2. **Integrate into Backend**
   ```python
   # Replace start_continuous_recognition with keyword-triggered recognition
   keyword_model = speechsdk.KeywordRecognitionModel("computer.table")
   speech_recognizer.start_keyword_recognition_async(keyword_model)
   ```

3. **Update Client**
   - Show "Say 'Computer'..." idle state (already implemented)
   - Visual feedback on keyword detection (already implemented)

### Current Blocker (March 2026)

The Speech Studio Custom Keyword portal returns **401 Unauthorized** when trying to create
a project. Investigation revealed:

- The `disableLocalAuth` property on Speech resources is set to `true`
- This appears to be enforced by an Azure management group policy on the subscription
- Neither `az resource update --set properties.disableLocalAuth=false` nor the REST API
  PATCH endpoint successfully changed this property
- Both `aullah-speech` and `aullah-speech-keyword` resources are affected

**Resolution options:**
1. Request an exemption from the Azure policy enforcing `disableLocalAuth=true`
2. Use a different subscription without this policy
3. Contact Azure support to enable local auth on the Speech resource
4. Use the Picovoice Porcupine SDK as an alternative (browser-based WASM, requires
   separate account at picovoice.ai)

### Environment Variables

When implementing the custom keyword approach, update `.env`:
```
WAKE_WORD_MODEL=computer.table    # Path to the .table keyword model file
WAKE_WORD_ENABLED=true          # Enable/disable wake word detection
```

---

## 2. Fine-Tune gpt-4.1-nano for OR Voice Commands

### Status: Ready to execute (dataset prepared, not yet trained)

### Problem

The base `gpt-4.1-nano` model has weak instruction adherence for negative constraints.
The most persistent issue: saying **"start preparation"** causes the model to also call
`start_recording` due to surface-level word association with "start". Multiple rounds of
prompt engineering and tool description changes could not fix this — the nano model
ignores "never do X when Y" rules.

A **code-level guard** (`_user_wants_recording()` in `main.py`) currently strips spurious
recording tool calls at zero latency cost. This works but is a workaround, not a fix.

### Solution: Fine-Tuning

Fine-tune `gpt-4.1-nano` on OR-specific training data so the model learns correct
tool routing from examples (positive weights) instead of relying on prompt rules
(which nano ignores).

**Key benefits:**
- Same ~950ms inference latency as the base model
- Correct tool selection learned from weights, not prompt rules
- Can potentially simplify/shrink the system prompt (fewer tokens = faster)
- Supported in Azure Foundry: North Central US and Sweden Central regions

### Training Dataset

**Location:** `voice-control/fine-tuning/`

| File | Examples | Size |
|------|----------|------|
| `training.jsonl` | 158 | ~1 MB |
| `validation.jsonl` | 40 | ~262 KB |
| `generate_dataset.py` | — | Generator script |

**198 total examples** covering:

| Category | Count | Focus |
|----------|-------|-------|
| `set_zone` | 86 | Zone power/brightness/color for surgical, ambient, all |
| `activate_scene` | 51 | All 6 scenes + negative examples (prep without recording) |
| `set_light` | 34 | All 5 individual lights |
| `start_recording` | 14 | Only explicit recording + laparoscopy combo |
| `stop_recording` | 12 | Explicit stop + end procedure combo |
| `take_snapshot` | 8 | EN + DE |
| `get_lights` | 7 | Status queries |
| text-only | 5 | Out-of-scope rejections |

**Language split:** 135 English / 63 German

**Format:** Uses the `tools` parameter format (recommended by Azure Foundry docs).
Tool definitions in training data are identical to production code (required for quality
optimization per docs).

### How to Execute

1. **Upload training data** to Azure Foundry (Sweden Central or North Central US)
2. **Create fine-tuning job** for `gpt-4.1-nano (2025-04-14)`
3. **Deploy fine-tuned model** to Sweden Central endpoint
4. **Update `.env`** to point `MODEL_DEPLOYMENT` to the fine-tuned deployment name
5. **Test** with the 8-scenario test suite via `/api/test-chat`
6. **Keep the recording guard** as defense-in-depth (zero cost safety net)

### To Regenerate Dataset

```bash
cd voice-control/fine-tuning
python generate_dataset.py
# Output: training.jsonl + validation.jsonl
```

Add more examples to `generate_dataset.py` and re-run to expand coverage.

### Post Fine-Tuning Considerations

- The code-level recording guard should remain active (zero overhead, catches edge cases)
- Monitor whether the system prompt can be simplified (fewer rules = fewer tokens = faster)
- If adding new tools/commands, add training examples and retrain

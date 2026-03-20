"""
Generate fine-tuning training dataset for OR voice control assistant.
Format: JSONL with tool calling (recommended format per Azure Foundry docs).
Each line: {"messages": [...], "tools": [...]}

Usage: python generate_dataset.py
Output: training.jsonl + validation.jsonl (80/20 split)
"""

import json
import random
import os

SYSTEM_PROMPT = open(os.path.join(os.path.dirname(__file__), "..", "SYSTEM_PROMPT.md")).read()

# Tool definitions — identical to main.py (required for quality optimization per docs)
TOOLS = [
    {"type": "function", "function": {"name": "get_lights", "description": "Get current state of all OR lights", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "set_light", "description": "Control a single specific light. Only changes the parameters you provide — other lights are NOT affected.", "parameters": {"type": "object", "properties": {"light_id": {"type": "string", "enum": ["surgical_main", "surgical_secondary", "ambient_ceiling", "ambient_wall", "task_monitor"]}, "power": {"type": "boolean", "description": "Turn on/off"}, "brightness": {"type": "integer", "minimum": 0, "maximum": 100}, "color_temp": {"type": "integer", "minimum": 3000, "maximum": 6000, "description": "Kelvin"}, "color": {"type": "string", "enum": ["light_blue", "light_green", "red", "white"], "description": "Named color preset. Use 'white' to reset to normal."}}, "required": ["light_id"]}}},
    {"type": "function", "function": {"name": "set_zone", "description": "Control all lights in one zone. Only changes lights in the specified zone — other zones are NOT affected. Only changes the parameters you provide.", "parameters": {"type": "object", "properties": {"zone": {"type": "string", "enum": ["surgical", "ambient", "task", "all"]}, "power": {"type": "boolean"}, "brightness": {"type": "integer", "minimum": 0, "maximum": 100}, "color_temp": {"type": "integer", "minimum": 3000, "maximum": 6000}, "color": {"type": "string", "enum": ["light_blue", "light_green", "red", "white"], "description": "Named color preset. Use 'white' to reset to normal."}}, "required": ["zone"]}}},
    {"type": "function", "function": {"name": "activate_scene", "description": "Activate a lighting scene preset. This changes ALL lights at once to predefined values.", "parameters": {"type": "object", "properties": {"scene": {"type": "string", "enum": ["full_surgery", "laparoscopy", "prep", "closing", "emergency", "standby"]}}, "required": ["scene"]}}},
    {"type": "function", "function": {"name": "start_recording", "description": "Start endoscope video recording. ONLY call this when user explicitly says 'start recording', 'Aufnahme starten', or 'prepare for laparoscopy'. Never call for prep/preparation/standby/closing commands.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "stop_recording", "description": "Stop endoscope video recording", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "take_snapshot", "description": "Take a still image from the endoscope", "parameters": {"type": "object", "properties": {}, "required": []}}},
]

call_counter = 0
def next_call_id():
    global call_counter
    call_counter += 1
    return f"call_{call_counter:04d}"

def tc(name, args=None):
    """Build a tool_call entry."""
    return {"id": next_call_id(), "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}

def example(user_text, tool_calls, assistant_text, lang_hint="Respond in English."):
    """Build a single training example."""
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT + f"\n\n## CURRENT LANGUAGE\n{lang_hint}"},
        {"role": "user", "content": user_text},
        {"role": "assistant", "tool_calls": tool_calls} if tool_calls else {"role": "assistant", "content": assistant_text},
    ]
    # For tool-calling examples, skip to the final assistant text (fast-path style)
    # The model learns: user → tool_calls (we don't need tool results for routing training)
    return {"messages": msgs, "tools": TOOLS}

def example_text_only(user_text, assistant_text, lang_hint="Respond in English."):
    """For queries where no tool is called."""
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT + f"\n\n## CURRENT LANGUAGE\n{lang_hint}"},
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]
    return {"messages": msgs, "tools": TOOLS}

# =====================================================================
# TRAINING EXAMPLES
# =====================================================================
examples = []

# -------------------------------------------------------------------
# 1. SCENE ACTIVATION — lights only, NO recording
# -------------------------------------------------------------------
# Preparation (the critical case: "start" must NOT trigger start_recording)
for text in ["start preparation", "switch to preparation mode", "preparation mode please", "prep mode", "go to prep"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "prep"})], "Preparation started."))
for text in ["Vorbereitung starten", "Bitte in Vorbereitungsmodus wechseln", "Vorbereitungsmodus", "Vorbereitung bitte"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "prep"})], "Vorbereitungsmodus.", "Respond in German."))

# Full surgery
for text in ["full surgery mode", "switch to full surgery", "surgery mode"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "full_surgery"})], "Full surgery mode."))
for text in ["Volles OP-Licht", "OP-Modus bitte"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "full_surgery"})], "OP-Modus.", "Respond in German."))

# Closing
for text in ["closing mode", "switch to closing", "closing please"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "closing"})], "Closing mode."))
for text in ["Schlussmodus", "Bitte auf Schließen wechseln"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "closing"})], "Schlussmodus.", "Respond in German."))

# Emergency
for text in ["emergency", "emergency mode", "activate emergency lights"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "emergency"})], "Emergency mode."))
for text in ["Notfall", "Notfallbeleuchtung"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "emergency"})], "Notfallmodus.", "Respond in German."))

# Standby
for text in ["standby mode", "switch to standby", "go to standby"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "standby"})], "Standby mode."))
for text in ["Standby-Modus", "Standby bitte"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "standby"})], "Standby.", "Respond in German."))

# -------------------------------------------------------------------
# 2. LAPAROSCOPY — scene + recording (the ONLY scene that auto-starts recording)
# -------------------------------------------------------------------
for text in ["prepare for laparoscopy", "laparoscopy mode", "switch to laparoscopy", "start laparoscopy"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "laparoscopy"}), tc("start_recording")], "Laparoscopy mode. Recording started."))
for text in ["Laparoskopie vorbereiten", "Laparoskopie-Modus", "Bitte Laparoskopie starten"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "laparoscopy"}), tc("start_recording")], "Laparoskopie-Modus. Aufnahme gestartet.", "Respond in German."))

# -------------------------------------------------------------------
# 3. END PROCEDURE — stop recording + closing
# -------------------------------------------------------------------
for text in ["end procedure", "finish the procedure", "procedure is done"]:
    examples.append(example(text, [tc("stop_recording"), tc("activate_scene", {"scene": "closing"})], "Recording stopped. Closing mode."))
for text in ["Eingriff beenden", "Eingriff ist fertig", "Prozedur beenden"]:
    examples.append(example(text, [tc("stop_recording"), tc("activate_scene", {"scene": "closing"})], "Aufnahme gestoppt. Schlussmodus.", "Respond in German."))

# -------------------------------------------------------------------
# 4. ZONE CONTROLS — set_zone (surgical)
# -------------------------------------------------------------------
# Power on/off
for text in ["turn on the surgical lights", "surgical lights on", "switch on surgical"]:
    examples.append(example(text, [tc("set_zone", {"zone": "surgical", "power": True})], "Done."))
for text in ["turn off the surgical lights", "surgical lights off", "switch off surgical lights"]:
    examples.append(example(text, [tc("set_zone", {"zone": "surgical", "power": False})], "Done."))
for text in ["OP-Leuchten einschalten", "Chirurgische Lichter an"]:
    examples.append(example(text, [tc("set_zone", {"zone": "surgical", "power": True})], "Erledigt.", "Respond in German."))
for text in ["OP-Leuchten ausschalten", "Chirurgische Lichter aus"]:
    examples.append(example(text, [tc("set_zone", {"zone": "surgical", "power": False})], "Erledigt.", "Respond in German."))

# Absolute brightness
for pct in [20, 40, 50, 60, 80, 100]:
    examples.append(example(f"set surgical lights to {pct} percent", [tc("set_zone", {"zone": "surgical", "brightness": pct})], "Done."))
examples.append(example("dim the surgical lights to 30 percent", [tc("set_zone", {"zone": "surgical", "brightness": 30})], "Done."))
examples.append(example("OP-Leuchten auf 70 Prozent", [tc("set_zone", {"zone": "surgical", "brightness": 70})], "Erledigt.", "Respond in German."))
examples.append(example("Chirurgische Lichter auf 50 Prozent stellen", [tc("set_zone", {"zone": "surgical", "brightness": 50})], "Erledigt.", "Respond in German."))

# -------------------------------------------------------------------
# 5. ZONE CONTROLS — set_zone (ambient)
# -------------------------------------------------------------------
for text in ["turn on the ambient lights", "ambient lights on"]:
    examples.append(example(text, [tc("set_zone", {"zone": "ambient", "power": True})], "Done."))
for text in ["turn off the ambient lights", "ambient lights off"]:
    examples.append(example(text, [tc("set_zone", {"zone": "ambient", "power": False})], "Done."))
for text in ["Umgebungslicht einschalten", "Raumlichter an"]:
    examples.append(example(text, [tc("set_zone", {"zone": "ambient", "power": True})], "Erledigt.", "Respond in German."))
for text in ["Umgebungslicht ausschalten", "Raumlichter aus"]:
    examples.append(example(text, [tc("set_zone", {"zone": "ambient", "power": False})], "Erledigt.", "Respond in German."))

for pct in [20, 40, 50, 60, 80]:
    examples.append(example(f"dim the ambient light to {pct} percent", [tc("set_zone", {"zone": "ambient", "brightness": pct})], "Done."))
examples.append(example("set ambient to 30 percent", [tc("set_zone", {"zone": "ambient", "brightness": 30})], "Done."))
examples.append(example("Umgebungslicht auf 40 Prozent dimmen", [tc("set_zone", {"zone": "ambient", "brightness": 40})], "Erledigt.", "Respond in German."))

# -------------------------------------------------------------------
# 6. ZONE CONTROLS — set_zone (all)
# -------------------------------------------------------------------
for text in ["turn on all the lights", "all lights on", "lights on"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "power": True})], "Done."))
for text in ["turn off all the lights", "all lights off", "lights off"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "power": False})], "Done."))
for text in ["Alle Lichter an", "Lichter einschalten"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "power": True})], "Erledigt.", "Respond in German."))
for text in ["Alle Lichter aus", "Lichter ausschalten"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "power": False})], "Erledigt.", "Respond in German."))

for pct in [30, 50, 70]:
    examples.append(example(f"set all lights to {pct} percent", [tc("set_zone", {"zone": "all", "brightness": pct})], "Done."))
examples.append(example("dim lights to 40 percent", [tc("set_zone", {"zone": "all", "brightness": 40})], "Done."))
examples.append(example("Alle Lichter auf 60 Prozent", [tc("set_zone", {"zone": "all", "brightness": 60})], "Erledigt.", "Respond in German."))

# -------------------------------------------------------------------
# 7. INDIVIDUAL LIGHT CONTROLS — set_light
# -------------------------------------------------------------------
# Surgical main
for text in ["turn on the main light", "main surgical light on", "switch on main light"]:
    examples.append(example(text, [tc("set_light", {"light_id": "surgical_main", "power": True})], "Done."))
examples.append(example("set main light to 80 percent", [tc("set_light", {"light_id": "surgical_main", "brightness": 80})], "Done."))
examples.append(example("turn off the main light", [tc("set_light", {"light_id": "surgical_main", "power": False})], "Done."))

# Surgical secondary
for text in ["turn on the secondary light", "secondary light on"]:
    examples.append(example(text, [tc("set_light", {"light_id": "surgical_secondary", "power": True})], "Done."))
examples.append(example("secondary light to 60 percent", [tc("set_light", {"light_id": "surgical_secondary", "brightness": 60})], "Done."))
examples.append(example("turn off secondary light", [tc("set_light", {"light_id": "surgical_secondary", "power": False})], "Done."))

# Ceiling light
for text in ["turn on the ceiling light", "ceiling light on"]:
    examples.append(example(text, [tc("set_light", {"light_id": "ambient_ceiling", "power": True})], "Done."))
examples.append(example("set ceiling light to 50 percent", [tc("set_light", {"light_id": "ambient_ceiling", "brightness": 50})], "Done."))
examples.append(example("turn off the ceiling light", [tc("set_light", {"light_id": "ambient_ceiling", "power": False})], "Done."))
examples.append(example("Deckenlampe auf 70 Prozent", [tc("set_light", {"light_id": "ambient_ceiling", "brightness": 70})], "Erledigt.", "Respond in German."))

# Wall light
for text in ["turn on the wall light", "wall light on"]:
    examples.append(example(text, [tc("set_light", {"light_id": "ambient_wall", "power": True})], "Done."))
examples.append(example("set the wall light to 80 percent", [tc("set_light", {"light_id": "ambient_wall", "brightness": 80})], "Done."))
examples.append(example("turn off the wall light", [tc("set_light", {"light_id": "ambient_wall", "power": False})], "Done."))
examples.append(example("Wandlampe ausschalten", [tc("set_light", {"light_id": "ambient_wall", "power": False})], "Erledigt.", "Respond in German."))

# Monitor
for text in ["turn on the monitor", "monitor on", "switch on the monitor"]:
    examples.append(example(text, [tc("set_light", {"light_id": "task_monitor", "power": True})], "Done."))
for text in ["turn off the monitor", "monitor off", "switch off the monitor"]:
    examples.append(example(text, [tc("set_light", {"light_id": "task_monitor", "power": False})], "Done."))
examples.append(example("set monitor brightness to 90 percent", [tc("set_light", {"light_id": "task_monitor", "brightness": 90})], "Done."))
examples.append(example("dim the monitor to 50 percent", [tc("set_light", {"light_id": "task_monitor", "brightness": 50})], "Done."))
for text in ["Monitor ausschalten", "Bitte den Monitor ausschalten"]:
    examples.append(example(text, [tc("set_light", {"light_id": "task_monitor", "power": False})], "Erledigt.", "Respond in German."))
for text in ["Monitor einschalten", "Monitor an"]:
    examples.append(example(text, [tc("set_light", {"light_id": "task_monitor", "power": True})], "Erledigt.", "Respond in German."))
examples.append(example("Monitor auf 70 Prozent", [tc("set_light", {"light_id": "task_monitor", "brightness": 70})], "Erledigt.", "Respond in German."))

# -------------------------------------------------------------------
# 8. COLOR CONTROLS
# -------------------------------------------------------------------
for text in ["set the lights to blue", "lights blue", "make the lights blue"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "color": "light_blue"})], "Done."))
for text in ["set the lights to green", "lights green"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "color": "light_green"})], "Done."))
for text in ["set the lights to red", "lights red", "red lights please"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "color": "red"})], "Done."))
for text in ["set the lights to white", "lights back to normal", "reset light color"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "color": "white"})], "Done."))
# Zone-specific color
examples.append(example("set ambient lights to blue", [tc("set_zone", {"zone": "ambient", "color": "light_blue"})], "Done."))
examples.append(example("ambient lights green", [tc("set_zone", {"zone": "ambient", "color": "light_green"})], "Done."))
examples.append(example("surgical lights to red", [tc("set_zone", {"zone": "surgical", "color": "red"})], "Done."))
# Individual light color
examples.append(example("set the wall light to blue", [tc("set_light", {"light_id": "ambient_wall", "color": "light_blue"})], "Done."))
examples.append(example("ceiling light green", [tc("set_light", {"light_id": "ambient_ceiling", "color": "light_green"})], "Done."))
# German color
for text in ["Lichter auf blau", "Bitte blaues Licht"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "color": "light_blue"})], "Erledigt.", "Respond in German."))
for text in ["Lichter auf grün", "Grünes Licht bitte"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "color": "light_green"})], "Erledigt.", "Respond in German."))
examples.append(example("Lichter wieder auf weiß", [tc("set_zone", {"zone": "all", "color": "white"})], "Erledigt.", "Respond in German."))
examples.append(example("Rotes Licht bitte", [tc("set_zone", {"zone": "all", "color": "red"})], "Erledigt.", "Respond in German."))

# -------------------------------------------------------------------
# 9. COLOR TEMPERATURE
# -------------------------------------------------------------------
examples.append(example("set the surgical lights to warm light", [tc("set_zone", {"zone": "surgical", "color_temp": 3000})], "Done."))
examples.append(example("surgical lights to cool white", [tc("set_zone", {"zone": "surgical", "color_temp": 5500})], "Done."))
examples.append(example("set color temperature to 4500 kelvin", [tc("set_zone", {"zone": "all", "color_temp": 4500})], "Done."))
examples.append(example("Farbtemperatur auf 4000 Kelvin", [tc("set_zone", {"zone": "all", "color_temp": 4000})], "Erledigt.", "Respond in German."))

# -------------------------------------------------------------------
# 10. RECORDING — explicit commands (these SHOULD use recording tools)
# -------------------------------------------------------------------
for text in ["start recording", "begin recording", "start the recording", "record please"]:
    examples.append(example(text, [tc("start_recording")], "Recording started."))
for text in ["stop recording", "stop the recording", "end recording"]:
    examples.append(example(text, [tc("stop_recording")], "Recording stopped."))
for text in ["Aufnahme starten", "Bitte Aufnahme starten", "Aufnahme beginnen"]:
    examples.append(example(text, [tc("start_recording")], "Aufnahme gestartet.", "Respond in German."))
for text in ["Aufnahme stoppen", "Aufnahme beenden", "Bitte Aufnahme stoppen"]:
    examples.append(example(text, [tc("stop_recording")], "Aufnahme gestoppt.", "Respond in German."))

# -------------------------------------------------------------------
# 11. SNAPSHOT
# -------------------------------------------------------------------
for text in ["take a snapshot", "snapshot please", "capture a snapshot", "take a photo", "take a picture"]:
    examples.append(example(text, [tc("take_snapshot")], "Snapshot taken."))
for text in ["Foto machen", "Bitte ein Foto aufnehmen", "Schnappschuss bitte"]:
    examples.append(example(text, [tc("take_snapshot")], "Foto aufgenommen.", "Respond in German."))

# -------------------------------------------------------------------
# 12. GET LIGHTS STATUS
# -------------------------------------------------------------------
for text in ["what are the lights set to", "show me the light status", "current light settings", "how are the lights"]:
    examples.append(example(text, [tc("get_lights")], ""))
for text in ["Wie sind die Lichter eingestellt", "Lichtstatus bitte", "Was sind die aktuellen Lichteinstellungen"]:
    examples.append(example(text, [tc("get_lights")], "", "Respond in German."))

# -------------------------------------------------------------------
# 13. NEGATIVE EXAMPLES — things that should NOT trigger recording
# (Critical for fixing the "start preparation" → start_recording bug)
# -------------------------------------------------------------------
# These all use "start" but must NOT call start_recording
for text in ["start prep", "start the prep mode", "start getting ready"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "prep"})], "Preparation started."))
# These scene activations must NOT trigger recording
for text in ["go to full surgery", "activate surgery mode"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "full_surgery"})], "Full surgery mode."))
for text in ["switch to closing mode", "activate closing"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "closing"})], "Closing mode."))
for text in ["go to standby", "activate standby mode"]:
    examples.append(example(text, [tc("activate_scene", {"scene": "standby"})], "Standby mode."))
# Light commands must NEVER include recording
for text in ["turn on surgical lights and dim ambient to 30 percent"]:
    examples.append(example(text, [tc("set_zone", {"zone": "surgical", "power": True}), tc("set_zone", {"zone": "ambient", "brightness": 30})], "Done."))
for text in ["start dimming the lights", "start turning on the surgical"]:
    examples.append(example(text, [tc("set_zone", {"zone": "all", "brightness": 50}), tc("set_zone", {"zone": "surgical", "power": True})], "Done."))

# -------------------------------------------------------------------
# 14. COMBINED LIGHT COMMANDS (multi-tool, no recording)
# -------------------------------------------------------------------
examples.append(example("turn on surgical and turn off ambient", [tc("set_zone", {"zone": "surgical", "power": True}), tc("set_zone", {"zone": "ambient", "power": False})], "Done."))
examples.append(example("set surgical to 80 and ambient to 30", [tc("set_zone", {"zone": "surgical", "brightness": 80}), tc("set_zone", {"zone": "ambient", "brightness": 30})], "Done."))
examples.append(example("dim everything to 50 percent and make them blue", [tc("set_zone", {"zone": "all", "brightness": 50, "color": "light_blue"})], "Done."))
examples.append(example("OP-Leuchten an und Umgebungslicht auf 20 Prozent", [tc("set_zone", {"zone": "surgical", "power": True}), tc("set_zone", {"zone": "ambient", "brightness": 20})], "Erledigt.", "Respond in German."))

# -------------------------------------------------------------------
# 15. OUT-OF-SCOPE / CONVERSATIONAL
# -------------------------------------------------------------------
for text, resp in [
    ("what time is it", "I can only control OR lights and recording."),
    ("play some music", "I can only control OR lights and recording."),
    ("how are you", "I'm ready to help with OR controls."),
]:
    examples.append(example_text_only(text, resp))
for text, resp in [
    ("Wie spät ist es", "Ich kann nur die OP-Beleuchtung und Aufnahme steuern."),
    ("Erzähl mir einen Witz", "Ich kann nur die OP-Beleuchtung und Aufnahme steuern."),
]:
    examples.append(example_text_only(text, resp, "Respond in German."))


# =====================================================================
# WRITE FILES
# =====================================================================
random.seed(42)
random.shuffle(examples)

split = int(len(examples) * 0.8)
training = examples[:split]
validation = examples[split:]

out_dir = os.path.dirname(__file__)

with open(os.path.join(out_dir, "training.jsonl"), "w", encoding="utf-8") as f:
    for ex in training:
        f.write(json.dumps(ex, ensure_ascii=False) + "\n")

with open(os.path.join(out_dir, "validation.jsonl"), "w", encoding="utf-8") as f:
    for ex in validation:
        f.write(json.dumps(ex, ensure_ascii=False) + "\n")

print(f"Generated {len(training)} training + {len(validation)} validation = {len(examples)} total examples")
print(f"Files: {out_dir}/training.jsonl, {out_dir}/validation.jsonl")

# Stats
tool_counts = {}
for ex in examples:
    for msg in ex["messages"]:
        if msg["role"] == "assistant" and "tool_calls" in msg:
            for t in msg["tool_calls"]:
                name = t["function"]["name"]
                tool_counts[name] = tool_counts.get(name, 0) + 1
        elif msg["role"] == "assistant" and "tool_calls" not in msg and msg.get("content"):
            tool_counts["(text_only)"] = tool_counts.get("(text_only)", 0) + 1
print("\nTool distribution:")
for name, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
    print(f"  {name}: {count}")

lang_counts = {"en": 0, "de": 0}
for ex in examples:
    sys_msg = ex["messages"][0]["content"]
    if "German" in sys_msg:
        lang_counts["de"] += 1
    else:
        lang_counts["en"] += 1
print(f"\nLanguage split: EN={lang_counts['en']}, DE={lang_counts['de']}")

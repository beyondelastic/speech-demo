"""Quick STT container connectivity test using push stream."""
import azure.cognitiveservices.speech as speechsdk
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / '.env')

key = os.getenv('SPEECH_KEY')
region = os.getenv('SPEECH_REGION')
host = os.getenv('SPEECH_CONTAINER_HOST')

print(f"Host: {host}")

# For containers, use ws:// scheme with host parameter
config = speechsdk.SpeechConfig(host="ws://localhost:5000", subscription=key)
config.speech_recognition_language = 'en-US'

# Push stream test
fmt = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
stream = speechsdk.audio.PushAudioInputStream(fmt)
audio_cfg = speechsdk.audio.AudioConfig(stream=stream)

recognizer = speechsdk.SpeechRecognizer(speech_config=config, audio_config=audio_cfg)

# Push 2 seconds of silence
silence = b'\x00' * (16000 * 2 * 2)
stream.write(silence)
stream.close()

print("Pushed 2s silence, waiting for result...")
result = recognizer.recognize_once()
print(f"Result reason: {result.reason}")
if result.reason == speechsdk.ResultReason.Canceled:
    details = result.cancellation_details
    print(f"Canceled: {details.reason}")
    print(f"Error details: {details.error_details}")
elif result.reason == speechsdk.ResultReason.NoMatch:
    print("NoMatch (expected for silence - container is working)")
elif result.reason == speechsdk.ResultReason.RecognizedSpeech:
    print(f"Recognized: {result.text}")

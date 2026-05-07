"""
Foundry Local LLM Server — starts phi-4-mini-instruct and serves it via OpenAI-compatible API.
Run this in a separate terminal before starting main.py.

Usage:
    python llm_server.py [--port 5273] [--model phi-4-mini-instruct]
"""

import argparse
import signal
import sys
import time

from foundry_local_sdk import Configuration, FoundryLocalManager


def main():
    parser = argparse.ArgumentParser(description="Foundry Local LLM Server")
    parser.add_argument("--port", type=int, default=5273, help="Port to bind (default: 5273)")
    parser.add_argument("--model", type=str, default="Phi-4-mini-instruct", help="Model name pattern to load")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    web_config = Configuration.WebService(urls=url)
    config = Configuration(app_name="local_voice_control", web=web_config)
    FoundryLocalManager.initialize(config)
    manager = FoundryLocalManager.instance
    manager.download_and_register_eps()

    # Find model
    model = None
    for m in manager.catalog.list_models():
        if args.model in m.id:
            model = m
            break

    if model is None:
        print(f"[Error] Model matching '{args.model}' not found in catalog.")
        print("Available models:")
        for m in manager.catalog.list_models():
            print(f"  - {m.id}")
        sys.exit(1)

    print(f"[LLM] Model: {model.id}")
    print(f"[LLM] Cached: {model.is_cached}")
    print(f"[LLM] Tool calling: {model.supports_tool_calling}")

    if not model.is_cached:
        print("[LLM] Downloading model...")
        model.download(lambda p: print(f"\r[LLM] Download: {p:.1f}%", end="", flush=True))
        print()

    print("[LLM] Loading model into memory...")
    model.load()
    print(f"[LLM] Model loaded: {model.is_loaded}")

    # Start web service
    manager.start_web_service()
    print(f"[LLM] OpenAI-compatible API running at: {manager.urls[0]}")
    print(f"[LLM] Use base_url='{manager.urls[0]}/v1' with OpenAI SDK")
    print("[LLM] Press Ctrl+C to stop.")

    def shutdown(sig, frame):
        print("\n[LLM] Shutting down...")
        manager.stop_web_service()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()

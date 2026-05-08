#!/usr/bin/env python3
"""
Healthcare MCP Superpower — One-command launcher
=================================================
Starts the FastAPI backend and opens the frontend in your browser.

    python run.py
"""

import subprocess
import sys
import time
import webbrowser
import os
import signal

API_PORT   = 8000
FRONTEND   = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
SRC_DIR    = os.path.join(os.path.dirname(__file__), "src")

BANNER = """
╔══════════════════════════════════════════════════════════╗
║        🏥  Healthcare Clinical Intelligence              ║
║        Agents Assemble Hackathon — Prompt Opinion        ║
╠══════════════════════════════════════════════════════════╣
║  API   →  http://localhost:8000                          ║
║  Docs  →  http://localhost:8000/docs                     ║
║  UI    →  opening in browser...                          ║
╚══════════════════════════════════════════════════════════╝
  Press Ctrl+C to stop
"""

def check_deps():
    try:
        import fastapi, uvicorn, pydantic, httpx
    except ImportError as e:
        print(f"\n❌  Missing dependency: {e}")
        print("    Run:  pip install fastapi uvicorn httpx pydantic mcp\n")
        sys.exit(1)

def main():
    check_deps()

    # Start API server
    env = os.environ.copy()
    # Include BOTH project root and src/ so all imports resolve
    project_root = os.path.dirname(os.path.abspath(__file__))
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [project_root, SRC_DIR, existing_path]))

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app",
         "--port", str(API_PORT), "--host", "0.0.0.0"],
        cwd=SRC_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    print(BANNER)

    # Wait for API to be ready with timeout
    import urllib.request
    import json
    max_attempts = 30
    attempt = 0
    api_ready = False
    
    while attempt < max_attempts:
        try:
            response = urllib.request.urlopen(f"http://localhost:{API_PORT}/health", timeout=1)
            data = json.loads(response.read().decode())
            if data.get("status") == "healthy":
                api_ready = True
                print("✅ API is healthy and ready!\n")
                break
        except Exception as e:
            attempt += 1
            if attempt % 5 == 0:
                print(f"  ⏳ Waiting for API... ({attempt}/{max_attempts})")
            time.sleep(0.5)
    
    if not api_ready:
        print("❌ API failed to start within timeout")
        # Try to read stderr to understand why
        stderr_output = api_proc.stderr.read() if api_proc.stderr else "No error output"
        print(f"\nServer output:\n{stderr_output}")
        api_proc.terminate()
        sys.exit(1)

    # Open frontend
    print(f"🌐 Opening browser → http://localhost:{API_PORT}\n")
    webbrowser.open(f"http://localhost:{API_PORT}")

    # Keep running until Ctrl+C
    try:
        api_proc.wait()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        api_proc.send_signal(signal.SIGTERM)
        try:
            api_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            api_proc.kill()
        print("Stopped. Goodbye.")

if __name__ == "__main__":
    main()

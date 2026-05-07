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
    )

    print(BANNER)

    # Wait for API to be ready
    import urllib.request
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://localhost:{API_PORT}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    # Open frontend
    webbrowser.open(f"http://localhost:{API_PORT}")

    # Keep running until Ctrl+C
    try:
        api_proc.wait()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        api_proc.send_signal(signal.SIGTERM)
        api_proc.wait()
        print("Stopped. Goodbye.")

if __name__ == "__main__":
    main()

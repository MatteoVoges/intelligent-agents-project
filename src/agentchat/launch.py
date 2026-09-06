"""One-shot orchestrator: start vLLM (subprocess), wait until healthy, then run the app.

    uv run python -m agentchat.launch            # start vLLM + app, tear down on exit
    uv run python -m agentchat.launch --no-vllm  # app only (vLLM already running elsewhere)

Intended for WSL2/Linux with a GPU. For day-to-day dev, prefer two terminals:
    bash scripts/serve_vllm.sh
    uv run python -m agentchat.app
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config


def _vllm_healthy() -> bool:
    url = config.VLLM_BASE_URL.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _wait_for_vllm(timeout_s: int = 900) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _vllm_healthy():
            return True
        time.sleep(2)
    return False


def main() -> None:
    start_vllm = "--no-vllm" not in sys.argv
    proc: subprocess.Popen | None = None

    if start_vllm and not _vllm_healthy():
        script = Path(__file__).resolve().parents[2] / "scripts" / "serve_vllm.sh"
        print(f"Starting vLLM via {script} …")
        proc = subprocess.Popen(["bash", str(script)])
        print("Waiting for vLLM to become healthy (first run downloads the model) …")
        if not _wait_for_vllm():
            print("vLLM did not become healthy in time; aborting.", file=sys.stderr)
            proc.terminate()
            sys.exit(1)
        print("vLLM is up.")
    elif _vllm_healthy():
        print("vLLM already running — reusing it.")

    try:
        from .app import main as run_app

        run_app()
    finally:
        if proc is not None:
            print("Shutting down vLLM …")
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ in {"__main__", "__mp_main__"}:
    main()

"""Console entry point that starts the vLLM server (wraps scripts/serve_vllm.sh).

Linux/WSL2 only — needs bash + a CUDA GPU. Exposed as `uv run agentchat-serve`.
"""

from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "serve_vllm.sh"
    os.execvp("bash", ["bash", str(script)])

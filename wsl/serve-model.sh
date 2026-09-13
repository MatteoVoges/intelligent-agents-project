#!/usr/bin/env bash
# Start the main vLLM server from its dedicated WSL venv (~/.venvs/agentchat-serve).
# Serves the 7B base plus every trained adapter, or another base if you name one.
#   wsl -d Ubuntu-24.04 bash wsl/serve-model.sh                # 7B + adapters
#   wsl -d Ubuntu-24.04 bash wsl/serve-model.sh qwen2.5-1.5b   # a small base instead
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-serve"
exec bash scripts/serve_vllm.sh "$@"

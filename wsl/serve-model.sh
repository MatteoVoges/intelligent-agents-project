#!/usr/bin/env bash
# Start the vLLM server from its dedicated WSL venv (~/.venvs/agentchat-serve).
# Run from Windows:  wsl -d Ubuntu-24.04 bash wsl/serve-model.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-serve"
exec bash scripts/serve_vllm.sh

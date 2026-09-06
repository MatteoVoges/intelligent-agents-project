#!/usr/bin/env bash
# Start the NiceGUI app from its dedicated WSL venv (~/.venvs/agentchat-app).
# Run from Windows:  wsl -d Ubuntu-24.04 bash wsl/run-app.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-app"
exec uv run python -m agentchat.app

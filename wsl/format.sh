#!/usr/bin/env bash
# Apply ruff's fixes and formatting (wsl/lint.sh only reports).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-app"
uv run --no-sync ruff format .
uv run --no-sync ruff check --fix .

#!/usr/bin/env bash
# Run the unit test suite in the app venv.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-app"
exec uv run --no-sync pytest -q

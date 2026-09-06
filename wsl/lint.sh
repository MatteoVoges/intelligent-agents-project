#!/usr/bin/env bash
# Lint + format check.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-app"
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .

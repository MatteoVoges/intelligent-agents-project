#!/usr/bin/env bash
# Regenerate the two persona SFT datasets.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-app"
exec uv run --no-sync python training/data/build_datasets.py

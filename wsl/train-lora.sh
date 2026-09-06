#!/usr/bin/env bash
# Train one persona LoRA in its own WSL venv (~/.venvs/agentchat-train).
# Kept separate from the serve venv so the training stack cannot move vLLM's pinned torch.
#   wsl -d Ubuntu-24.04 bash wsl/train-lora.sh training/configs/persona_a.yaml
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-train"
CONFIG="${1:-training/configs/persona_a.yaml}"
uv sync --extra train
uv run --no-sync python training/train_lora.py --config "$CONFIG"

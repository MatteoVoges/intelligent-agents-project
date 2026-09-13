#!/usr/bin/env bash
# Start a *second* vLLM on port 8001 holding one small model, so it is selectable in the UI
# alongside the 7B instead of replacing it.
#   wsl -d Ubuntu-24.04 bash wsl/serve-small.sh qwen2.5-0.5b
#
# Both servers share one GPU, and each reserves its fraction up front. The 7B at the default
# 0.90 leaves nothing, so start the main server with a lower budget when you want both:
#   VLLM_GPU_UTIL=0.78 wsl/serve-model.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-serve"
export VLLM_PORT="${VLLM_PORT:-8001}"
export VLLM_GPU_UTIL="${VLLM_GPU_UTIL:-0.15}"
exec bash scripts/serve_vllm.sh "${1:-qwen2.5-0.5b}"

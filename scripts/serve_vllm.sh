#!/usr/bin/env bash
# Launch the vLLM OpenAI-compatible server with the base model + any trained LoRA adapters.
# Run inside WSL2 (Linux + CUDA). Adapters are picked up automatically if present.
set -euo pipefail

BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}"
BASE_ID="${BASE_MODEL_ID:-qwen2.5-7b}"
ADAPTERS_DIR="${AGENTCHAT_ADAPTERS:-adapters}"
PORT="${VLLM_PORT:-8000}"

LORA_ARGS=()
for name in persona-a persona-b; do
  if [ -d "${ADAPTERS_DIR}/${name}" ]; then
    LORA_ARGS+=("${name}=${ADAPTERS_DIR}/${name}")
  fi
done

echo "Base model : ${BASE_MODEL} (served as '${BASE_ID}')"
echo "Adapters   : ${LORA_ARGS[*]:-<none yet>}"

exec uv run --active --extra serve vllm serve "${BASE_MODEL}" \
  --served-model-name "${BASE_ID}" \
  --quantization awq \
  --enable-lora \
  --max-lora-rank 16 \
  --max-loras 2 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --port "${PORT}" \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  ${LORA_ARGS:+--lora-modules "${LORA_ARGS[@]}"}

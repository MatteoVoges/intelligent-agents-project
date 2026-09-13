#!/usr/bin/env bash
# Launch a vLLM OpenAI-compatible server for one of the configured base models.
# Run inside WSL2 (Linux + CUDA).
#
#   bash scripts/serve_vllm.sh                # the 7B base + every trained adapter
#   bash scripts/serve_vllm.sh qwen2.5-1.5b   # a small base instead
#
# One process serves one base model: the adapters are LoRAs on the 7B, so they are only
# offered when the 7B is the base. Keep this table in sync with config.BASE_SPECS, which is
# what the app's model selector reads.
set -euo pipefail

MODEL_KEY="${1:-${BASE_MODEL_ID:-qwen2.5-7b}}"
ADAPTERS_DIR="${AGENTCHAT_ADAPTERS:-adapters}"
PORT="${VLLM_PORT:-8000}"
GPU_UTIL="${VLLM_GPU_UTIL:-0.90}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-8192}"

# Hermes is the parser Qwen's chat template emits tool calls for; other families need their
# own, so tool-calling is only enabled where it is known to work.
QUANT_ARGS=()
TOOL_ARGS=(--enable-auto-tool-choice --tool-call-parser hermes)
SUPPORTS_LORA=0

case "${MODEL_KEY}" in
  qwen2.5-7b)   HF_ID="Qwen/Qwen2.5-7B-Instruct-AWQ";        QUANT_ARGS=(--quantization awq); SUPPORTS_LORA=1 ;;
  qwen2.5-1.5b) HF_ID="Qwen/Qwen2.5-1.5B-Instruct" ;;
  qwen2.5-0.5b) HF_ID="Qwen/Qwen2.5-0.5B-Instruct" ;;
  smollm2-1.7b) HF_ID="HuggingFaceTB/SmolLM2-1.7B-Instruct"; TOOL_ARGS=() ;;
  *)
    echo "Unknown model key '${MODEL_KEY}'." >&2
    echo "Known: qwen2.5-7b, qwen2.5-1.5b, qwen2.5-0.5b, smollm2-1.7b" >&2
    exit 2 ;;
esac

# vLLM disables pinned memory on WSL2 by default; without it the V1 engine aborts at startup
# with "UVA is not available". Supported on WSL2 kernels >= 4.19.121.
export VLLM_WSL2_ENABLE_PIN_MEMORY="${VLLM_WSL2_ENABLE_PIN_MEMORY:-1}"

LORA_ARGS=()
if [ "${SUPPORTS_LORA}" = "1" ]; then
  for dir in "${ADAPTERS_DIR}"/*/; do
    name="$(basename "${dir}")"
    [ -f "${dir}adapter_config.json" ] && LORA_ARGS+=("${name}=${dir%/}")
  done
fi

echo "Base model : ${HF_ID} (served as '${MODEL_KEY}') on port ${PORT}"
echo "Adapters   : ${LORA_ARGS[*]:-<none>}"

LORA_FLAGS=()
if [ "${#LORA_ARGS[@]}" -gt 0 ]; then
  # --max-loras is how many adapters may be *resident* at once; sized to what we found so a
  # third persona does not silently evict a second mid-demo.
  LORA_FLAGS=(--enable-lora --max-lora-rank 16 --max-loras "${#LORA_ARGS[@]}" --lora-modules "${LORA_ARGS[@]}")
fi

exec uv run --active --extra serve vllm serve "${HF_ID}" \
  --served-model-name "${MODEL_KEY}" \
  "${QUANT_ARGS[@]}" \
  "${LORA_FLAGS[@]}" \
  --gpu-memory-utilization "${GPU_UTIL}" \
  --max-model-len "${MAX_LEN}" \
  --port "${PORT}" \
  "${TOOL_ARGS[@]}"

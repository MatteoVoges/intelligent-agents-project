#!/usr/bin/env bash
# The only script in this repo:
#
#   bash serve.sh
#
# Serves both bases at once — the 7B with its three LoRA adapters, and the 1.5B — so the
# app's selector switches between five models with no restart and nothing to swap, and two
# users can hold two different models at the same moment. No arguments: this set is the set.
#
# Linux with a CUDA GPU. Ctrl-C stops both.
#
# One vLLM process serves exactly one base model — the weights go into VRAM at startup — so
# "serve both" means one process per base, each on its own port. The adapters are LoRAs on
# the 7B and ride along inside its process. Keep the table below in sync with
# config.VLLM_PORTS / config.BASE_SPECS, which is what the model selector reads.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

# `--gpu-memory-utilization` is a share of the card's *total* memory, and it is a budget, not
# a request: each process sizes its KV cache so that weights + activations + cache stay under
# it. Independent budgets are why these two can load in parallel. What they must not do is
# add up past what the card has, counting whatever the desktop is already holding — that is
# the check in `assert_fits` below, and it is the failure this script used to die of.
#
# 0.55 + 0.28 leaves ~2.5 GB of a 16 GB card for the desktop, the CUDA contexts and
# fragmentation. An earlier version ran three bases at 0.96 of the card and the servers died
# under load rather than at startup, which reads like a bug in the app. The headroom is the
# point; raise these two only if you have a bigger card.
#
#   key            HF repo                              port  VRAM share
MODEL_TABLE="
qwen2.5-7b        Qwen/Qwen2.5-7B-Instruct-AWQ         8000  0.55
qwen2.5-1.5b      Qwen/Qwen2.5-1.5B-Instruct           8001  0.28
"
MODELS=(qwen2.5-7b qwen2.5-1.5b)

# Before the sync, which is the slow part: being told the argument is unknown after a
# ten-gigabyte download would be its own small insult.
if [ "$#" -gt 0 ]; then
  echo "serve.sh takes no arguments — it always serves ${MODELS[*]}." >&2
  echo "Ports and VRAM shares are the table at the top of this file." >&2
  exit 2
fi

# The GPU environment, kept out of the project's own `.venv` on purpose: `uv run` syncs
# before it runs, so a single environment would have `uv run pytest` uninstall vLLM's ~10 GB
# every time you ran the tests. Created and kept current by this script — you never sync it
# by hand. Both GPU extras go in together, because syncing one alone would remove the other.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$HOME/.venvs/agentchat-gpu}"
echo "Syncing ${UV_PROJECT_ENVIRONMENT} (first run downloads ~10 GB of CUDA wheels) …"
uv sync --extra serve --extra train

ADAPTERS_DIR="${AGENTCHAT_ADAPTERS:-adapters}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
START_TIMEOUT="${VLLM_START_TIMEOUT:-900}"
LOG_DIR="${VLLM_LOG_DIR:-data/logs}"
# The ceiling on (what the servers claim) + (what the card is already holding). Set just
# under the whole card: over it, something is guaranteed to die, and the point of the check is
# to say so before ten minutes of loading rather than after. Comfort is a matter for the
# shares in the table — this is only the wall.
VRAM_BUDGET="${VLLM_VRAM_BUDGET:-0.97}"
# A few concurrent users, not a benchmark. The default (hundreds) makes vLLM reserve
# activation memory for a batch this will never see, which is memory the KV cache wants.
MAX_SEQS="${VLLM_MAX_NUM_SEQS:-16}"

# Ignored on native Linux. Under WSL2, vLLM disables pinned memory by default and its V1
# engine then aborts at startup with "UVA is not available"; this re-enables it, which is
# supported on WSL2 kernels >= 4.19.121.
export VLLM_WSL2_ENABLE_PIN_MEMORY="${VLLM_WSL2_ENABLE_PIN_MEMORY:-1}"

# Fills HF_ID / PORT / GPU_UTIL for one key.
lookup() {
  read -r _ HF_ID PORT GPU_UTIL <<<"$(awk -v k="$1" '$1 == k' <<<"${MODEL_TABLE}")"
}

# Add up the shares against a card that is not empty, and refuse before loading 10 GB of
# weights rather than after. An over-subscribed pair does not fail cleanly at run time: both
# servers come up, and then one dies mid-answer with a CUDA OOM that reads like a bug in the
# app.
assert_fits() {
  local total used_mib want=0 key
  for key in "${MODELS[@]}"; do
    lookup "${key}"
    want="$(awk -v a="${want}" -v b="${GPU_UTIL}" 'BEGIN {printf "%.4f", a + b}')"
  done
  if ! read -r total used_mib <<<"$(nvidia-smi --query-gpu=memory.total,memory.used \
    --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ',')" || [ -z "${total:-}" ]; then
    echo "No nvidia-smi — skipping the VRAM check. vLLM will tell you if it does not fit." >&2
    return 0
  fi
  awk -v want="${want}" -v used="${used_mib}" -v total="${total}" -v budget="${VRAM_BUDGET}" '
    BEGIN {
      inuse = used / total
      printf "Asking for %.0f%% of %.1f GB; %.0f%% is already in use, budget is %.0f%%.\n",
             want * 100, total / 1024, inuse * 100, budget * 100
      if (want + inuse > budget) {
        printf "\nThat does not fit. Free the GPU — something else is holding it — or lower\n"
        printf "the shares in the table at the top of serve.sh.\n"
        printf "VLLM_VRAM_BUDGET=1.0 overrides this check if you know better.\n"
        exit 1
      }
    }'
}

# One vLLM, backgrounded, its output in its own log. Hermes is the tool-call parser Qwen's
# chat template emits; both bases are Qwen, so both get it.
start_one() {
  local key="$1"
  local quant=() loras=() lora_flags=() eager=()

  [ "${key}" = "qwen2.5-7b" ] && quant=(--quantization awq)
  # Skips CUDA-graph capture: a minute or two off every start, at maybe 10% of throughput.
  # Worth it while you are iterating, not for a demo with several users on it.
  [ -n "${VLLM_EAGER:-}" ] && eager=(--enforce-eager)

  # Adapters are LoRAs on the 7B, so they are only loaded into its process.
  if [ "${key}" = "qwen2.5-7b" ]; then
    for dir in "${ADAPTERS_DIR}"/*/; do
      [ -f "${dir}adapter_config.json" ] && loras+=("$(basename "${dir}")=${dir%/}")
    done
    # --max-loras is how many adapters may be *resident* at once; sized to what we found so a
    # third persona does not silently evict a second mid-demo.
    [ "${#loras[@]}" -gt 0 ] &&
      lora_flags=(--enable-lora --max-lora-rank 16 --max-loras "${#loras[@]}" --lora-modules "${loras[@]}")
  fi

  echo "=== ${key}: ${HF_ID} on :${PORT}, ${GPU_UTIL} of VRAM${loras[0]:+ + ${#loras[@]} adapter(s)} → ${LOG_DIR}/${key}.log"
  uv run --no-sync vllm serve "${HF_ID}" \
    --served-model-name "${key}" \
    "${quant[@]}" \
    "${lora_flags[@]}" \
    "${eager[@]}" \
    --gpu-memory-utilization "${GPU_UTIL}" \
    --max-model-len "${MAX_LEN}" \
    --max-num-seqs "${MAX_SEQS}" \
    --port "${PORT}" \
    --enable-auto-tool-choice \
    --tool-call-parser hermes >"${LOG_DIR}/${key}.log" 2>&1 &
}

# Poll until the server answers, or until it dies trying. A death prints the tail of its own
# log: with both servers writing to one terminal, the line that actually explains the failure
# was buried under the other one's progress bars.
wait_healthy() {  # key, port, pid
  local deadline=$((SECONDS + START_TIMEOUT))
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    if curl -sf "http://localhost:$2/v1/models" >/dev/null; then
      echo "--- $1 is up on :$2"
      return 0
    fi
    if ! kill -0 "$3" 2>/dev/null; then
      echo "--- $1 exited before it came up. Last 25 lines of ${LOG_DIR}/$1.log:" >&2
      tail -n 25 "${LOG_DIR}/$1.log" | sed 's/^/    /' >&2
      return 1
    fi
    sleep 3
  done
  echo "--- $1 did not come up within ${START_TIMEOUT}s — still loading? See ${LOG_DIR}/$1.log" >&2
  return 1
}

pids=()
keys=()
ports=()
up=()
up_pids=()
cleanup() {
  trap - EXIT INT TERM
  [ "${#pids[@]}" -gt 0 ] || exit
  echo "Stopping ${#pids[@]} server(s) …"
  kill "${pids[@]}" 2>/dev/null || true  # uv forwards SIGTERM to vllm
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

mkdir -p "${LOG_DIR}"
assert_fits

# Started together. Each process's VRAM budget is its own share of the card — decided by the
# flag, not by what it finds free — so two loading at once do not fight over the same memory,
# as long as the shares add up (assert_fits, above). Loading is mostly disk and CPU, so in
# parallel both are ready in about the time the 7B takes on its own instead of the sum.
# VLLM_SEQUENTIAL=1 goes back to one at a time if you ever need to bisect a failure.
for key in "${MODELS[@]}"; do
  lookup "${key}"
  start_one "${key}"
  pids+=("$!")
  keys+=("${key}")
  ports+=("${PORT}")
  if [ -n "${VLLM_SEQUENTIAL:-}" ]; then
    wait_healthy "${key}" "${PORT}" "$!" && { up+=("${key}"); up_pids+=("$!"); } || true
  fi
done

if [ -z "${VLLM_SEQUENTIAL:-}" ]; then
  echo
  echo "Loading ${#MODELS[@]} model(s) in parallel — first run also downloads weights."
  echo "Follow along with: tail -f ${LOG_DIR}/*.log"
  for i in "${!keys[@]}"; do
    wait_healthy "${keys[$i]}" "${ports[$i]}" "${pids[$i]}" &&
      { up+=("${keys[$i]}"); up_pids+=("${pids[$i]}"); } || true
  done
fi

if [ "${#up[@]}" -eq 0 ]; then
  echo "No server came up — see ${LOG_DIR}/. Nothing is serving." >&2
  exit 1
fi

echo
echo "${#up[@]} of ${#MODELS[@]} server(s) up: ${up[*]}"
if [ "${#up[@]}" -lt "${#MODELS[@]}" ]; then
  echo "The other failed; the app can still use the one that is up." >&2
fi
echo "Ctrl-C stops them together."

# From here only the ones that answered are watched — a failure during startup has already
# been reported with its log, and reporting it a second time reads like a second failure.
keys=("${up[@]}")
pids=("${up_pids[@]}")

# One server dying is not a reason to take the other down with it — the app treats each
# endpoint separately, so the surviving model keeps working and only the dead one errors when
# picked. Report it and keep serving; Ctrl-C is still what ends the script.
while [ "${#pids[@]}" -gt 0 ]; do
  sleep 5
  remaining_pids=() remaining_keys=()
  for i in "${!pids[@]}"; do
    if kill -0 "${pids[$i]}" 2>/dev/null; then
      remaining_pids+=("${pids[$i]}") remaining_keys+=("${keys[$i]}")
    else
      echo "--- ${keys[$i]} exited. Last 25 lines of ${LOG_DIR}/${keys[$i]}.log:" >&2
      tail -n 25 "${LOG_DIR}/${keys[$i]}.log" | sed 's/^/    /' >&2
    fi
  done
  pids=("${remaining_pids[@]}") keys=("${remaining_keys[@]}")
done
echo "Every server has exited." >&2

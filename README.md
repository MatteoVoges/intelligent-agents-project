# AgentChat

A local, multi-user chat application over self-hosted LLMs (Qwen2.5-7B + LoRA adapters) with
cross-chat memory, user-extensible tool-calling, and concurrent multi-user support.

Built for the *Intelligent Agents* project. See `CLAUDE.md` for architecture and `PLAN.md` for status.

## Features

**Required:** `uv`-runnable · web UI (NiceGUI) · chat with visible, scrollable history ·
start / stop / resume generation · create / continue / remove / switch conversations ·
switch between ≥2 models · cross-chat "project" memory · 2 fine-tuned LoRA adapters.

**Electives:** user-defined tools (tool-calling on the fly) · concurrent multi-user (isolated
per-user chats, projects, memory, tools).

## Requirements

- **WSL2 (Ubuntu) or Linux** with an NVIDIA GPU (~16 GB) + CUDA — vLLM has no native Windows build.
- [`uv`](https://docs.astral.sh/uv/).

## Run

Everything runs inside WSL2. The `wsl/` scripts each pin their own uv environment, so the
inference stack and the app stack can never fight over a shared `torch` pin:

| Script | Environment | Purpose |
|---|---|---|
| `wsl/serve-model.sh` | `~/.venvs/agentchat-serve` | vLLM + CUDA (heavy) |
| `wsl/run-app.sh` | `~/.venvs/agentchat-app` | NiceGUI + SQLite + embeddings (light) |
| `wsl/train-lora.sh` | `~/.venvs/agentchat-train` | QLoRA training (offline, one-off) |
| `wsl/build-data.sh` | app | regenerate the persona datasets |
| `wsl/verify.sh` | app | exercise every graded feature against live vLLM |
| `wsl/compare-models.sh` | app | same question → base vs. each adapter, side by side |
| `wsl/test.sh` / `wsl/lint.sh` | app | pytest / ruff |

**Two terminals** (vLLM is slow to load; you rarely restart it while iterating):

```bash
# terminal 1 — inference server (base model + any trained adapters)
wsl -d Ubuntu-24.04 bash wsl/serve-model.sh   # first run downloads Qwen2.5-7B-Instruct-AWQ (~5 GB)

# terminal 2 — the app
wsl -d Ubuntu-24.04 bash wsl/run-app.sh       # open http://localhost:8080 -> pick a username
```

Each script runs `uv sync` for its own environment on first use, so a clean clone needs no
extra setup step.

The app talks to vLLM at `http://localhost:8000/v1` (override with `VLLM_BASE_URL`).
Without adapters trained yet, only the base model is selectable; the app still runs.

> **WSL note:** vLLM disables pinned memory on WSL by default, and its V1 engine then aborts with
> `RuntimeError: UVA is not available`. `scripts/serve_vllm.sh` sets
> `VLLM_WSL2_ENABLE_PIN_MEMORY=1`, which is supported on WSL2 kernels ≥ 4.19.121.

## Fine-tuning the persona adapters

```bash
wsl -d Ubuntu-24.04 bash wsl/build-data.sh                        # writes the two JSONL datasets
wsl -d Ubuntu-24.04 bash wsl/train-lora.sh training/configs/persona_a.yaml
wsl -d Ubuntu-24.04 bash wsl/train-lora.sh training/configs/persona_b.yaml
# adapters land in adapters/persona-a and adapters/persona-b; restart serve-model.sh to load them
```

Training needs the GPU to itself — stop the vLLM server first.

## Custom tools

Open **Tools** in the sidebar and add a definition on the fly, e.g.:

```json
{ "name": "wordcount", "type": "shell", "command": "wc -w", "args": [{ "name": "text" }] }
```

Arguments reach the process one of two ways. If the command contains `{argname}` placeholders they
are substituted in place (`ls -la {path}`); otherwise the arguments are piped to stdin, so ordinary
filters like `wc -w` or `sort` work as tools without wrapping.

The model can then call the tool during a conversation; output is fed back into the answer.
Tools run as sandboxed-ish subprocesses (timeout, no shell injection, dedicated workdir) — they
still run with the app's OS privileges, so only add tools you trust.

## Configuration

Common env vars (all optional): `VLLM_BASE_URL`, `AGENTCHAT_PORT`, `AGENTCHAT_SECRET`,
`AGENTCHAT_DATA_DIR`, `AGENTCHAT_EMBED_MODEL`, `BASE_MODEL_ID`. See `src/agentchat/config.py`.

## Tests

```bash
wsl -d Ubuntu-24.04 bash wsl/test.sh
```

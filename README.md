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

Inference (vLLM) runs inside WSL2/Linux with the GPU. The app itself is plain Python and also runs
on Windows for UI development (it just can't generate until it can reach a vLLM server).

`uv run <name>` shortcuts (defined in `pyproject.toml`): `agentchat` (app), `agentchat-serve`
(vLLM only), `agentchat-launch` (both).

**Recommended — two terminals** (vLLM is slow to load; you rarely restart it while iterating):

```bash
uv sync                        # install deps into .venv

# terminal 1 — inference server (base model + any trained adapters)
uv run agentchat-serve         # first run downloads Qwen2.5-7B-Instruct-AWQ (~5 GB)

# terminal 2 — the app
uv run agentchat               # open http://localhost:8080 -> pick a username -> chat
```

**One-shot** (starts vLLM, waits for health, runs the app, tears vLLM down on exit):

```bash
uv run agentchat-launch                          # vLLM + app
uv run python -m agentchat.launch --no-vllm      # app only, vLLM already running
```

The app talks to vLLM at `http://localhost:8000/v1` (override with `VLLM_BASE_URL`).
Without adapters trained yet, only the base model is selectable; the app still runs.

## Fine-tuning the persona adapters

```bash
# put training data at training/data/persona_a.jsonl (see *.sample.jsonl for the format)
uv run --extra train python training/train_lora.py --config training/configs/persona_a.yaml
uv run --extra train python training/train_lora.py --config training/configs/persona_b.yaml
# adapters land in adapters/persona-a and adapters/persona-b; restart serve_vllm.sh to load them
```

## Custom tools

Open **Tools** in the sidebar and add a definition on the fly, e.g.:

```json
{ "name": "wordcount", "type": "shell", "command": "wc -w", "args": [{ "name": "text" }] }
```

The model can then call the tool during a conversation; output is fed back into the answer.
Tools run as sandboxed-ish subprocesses (timeout, no shell injection, dedicated workdir) — they
still run with the app's OS privileges, so only add tools you trust.

## Configuration

Common env vars (all optional): `VLLM_BASE_URL`, `AGENTCHAT_PORT`, `AGENTCHAT_SECRET`,
`AGENTCHAT_DATA_DIR`, `AGENTCHAT_EMBED_MODEL`, `BASE_MODEL_ID`. See `src/agentchat/config.py`.

## Tests

```bash
uv run --group dev pytest
```

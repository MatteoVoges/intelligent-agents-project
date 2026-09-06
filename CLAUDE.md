# CLAUDE.md — Intelligent Agents Project

Project-specific guidance for agents working in this repo. Read this before touching code.

## What this is

A course project (40% of grade) building a **local, multi-user chat application over self-hosted
LLMs** with fine-tuned LoRA adapters, cross-chat memory, user-extensible tool-calling, and
concurrent multi-user support. Solo project.

- **Presentation:** Mon 2026-09-07
- **Hand-in:** Mon 2026-09-14 (ZIP archive or download link)
- Must be **runnable via `uv`** (see Commands).

See `PLAN.md` for the phased execution plan and current status.

## Requirements being satisfied

**Required (all mandatory):** `uv`-runnable · cross-platform UI · chat (send, visible + scrollable
history, start/stop/resume) · switch/create/continue/remove conversations · switch model (≥2
loadable) · cross-chat memory ("project folder") · **≥2 fine-tuned models** · video demo.

**Electives (2 chosen):**
1. **Extensible tool-calling** — user supplies tool-definitions on the fly, model calls them.
2. **Concurrent multi-user** — isolated per-user chats/projects/memory, concurrent generation.

## Stack (decided — do not change without asking)

| Concern | Choice | Notes |
|---|---|---|
| OS/runtime | **WSL2 Ubuntu** | vLLM has no native Windows support. |
| Deps + run | **uv** | `pyproject.toml` + lockfile; runnable via `uv run`. |
| UI | **NiceGUI** | Web UI, multi-session, easy media. |
| Inference | **vLLM** | OpenAI-compatible server, continuous batching, **multi-LoRA**. |
| Base model | **Qwen2.5-7B-Instruct (AWQ 4-bit)** | Fits 16GB with KV cache + adapters + concurrency. |
| Fine-tuning | **PEFT + TRL (QLoRA)** | bitsandbytes NF4; trains the adapters. |
| Models exposed | base + **LoRA adapters** | Adapters are the "switchable models" AND the required fine-tunes. |
| Storage | **SQLite (WAL mode)** | Concurrency-safe for multi-user. |
| Memory | embeddings retrieval | sentence-transformers; per-project fact/summary store. |
| Auth | **username-only login** | No passwords; enough to demo isolation. |

**Hardware:** single 16GB GPU. Two 7B bases will not co-reside — the base+LoRA design is
deliberate. Do not propose loading multiple full 7B models simultaneously.

## Architecture

```
NiceGUI (browser, per-user session)
   → chat engine (streaming, stop, memory injection, tool loop)
      → vLLM OpenAI-compatible client  → vLLM server (base + LoRA adapters)
   → SQLite (users, conversations, messages, projects, memory, tool defs)
   → embeddings (memory retrieval)
   → tool executor (subprocess, user-defined tools)
```

- **Model switching** = selecting a LoRA adapter name (or base) sent to vLLM per request.
- **Concurrency** = vLLM continuous batching handles simultaneous requests; NiceGUI is async;
  SQLite in WAL mode. Keep all inference calls non-blocking.

## Proposed layout

```
src/agentchat/   app.py, config.py, db/, inference/, memory/, chat/, tools/, auth/, ui/
training/        train_lora.py, configs/, data/
adapters/        trained LoRA outputs (persona LoRAs)
tests/
```

## Commands

Run everything inside WSL2, via the `wsl/` scripts. Each pins its own `UV_PROJECT_ENVIRONMENT`
and syncs on first use — do not run bare `uv` in this repo, or the vLLM and training stacks will
fight over `torch`.

```bash
# the two demo commands
wsl -d Ubuntu-24.04 bash wsl/serve-model.sh   # vLLM: base + any adapters in adapters/
wsl -d Ubuntu-24.04 bash wsl/run-app.sh       # NiceGUI on http://localhost:8080

# training (needs the GPU to itself — stop serve-model.sh first)
wsl -d Ubuntu-24.04 bash wsl/build-data.sh
wsl -d Ubuntu-24.04 bash wsl/train-lora.sh training/configs/persona_a.yaml

# checks
wsl -d Ubuntu-24.04 bash wsl/test.sh      # pytest
wsl -d Ubuntu-24.04 bash wsl/lint.sh      # ruff check + format
wsl -d Ubuntu-24.04 bash wsl/verify.sh    # every graded feature against live vLLM
```

Three environments: `~/.venvs/agentchat-{app,serve,train}`.

**WSL gotcha:** vLLM disables pinned memory when it detects WSL, and its V1 engine then aborts
with `RuntimeError: UVA is not available`. `scripts/serve_vllm.sh` sets
`VLLM_WSL2_ENABLE_PIN_MEMORY=1` (valid on WSL2 kernels ≥ 4.19.121). Don't remove it.

**PowerShell gotcha:** `wsl ... bash -c "...$PATH..."` gets `$PATH` expanded to the *Windows*
path before bash sees it, and the unquoted parens break the parse. Put logic in a `wsl/*.sh`
file instead of inlining it.

## Conventions

- Python 3.11+, type hints, `ruff` for lint/format.
- Keep inference calls async/non-blocking (multi-user concurrency depends on it).
- No secrets/models committed; adapters live in `adapters/`, large weights are gitignored.
- Follow existing patterns before introducing new ones. Minimal changes; ask before large refactors.
- Comments only for non-obvious logic (per user's global style).

## Key risks to watch

- **LoRA/quantization compat:** adapters trained via QLoRA (NF4) served on an AWQ base in vLLM —
  validate adapters actually load and change output early (Phase 4 gate).
- **VRAM budget:** base + KV cache + N adapters + concurrency. Measure, don't assume.
- **Tool execution safety:** user-defined shell/python tools run via subprocess — enforce timeouts,
  no `shell=True` string injection, and a confirmation step. (Full sandboxing was NOT elected;
  document the limitation.)
- **`uv`-runnable with heavy deps (torch/vLLM):** verify a clean-clone `uv sync` + run works before
  hand-in.

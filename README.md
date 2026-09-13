# AgentChat

A local, multi-user chat application over self-hosted LLMs, with fine-tuned LoRA adapters,
cross-chat memory, user-extensible tool-calling and concurrent multi-user support. Everything
— inference, storage, embeddings, tools — runs on your own machine; nothing leaves it except
what a tool you wrote deliberately fetches.

Built for the *Intelligent Agents* course project.

---

## Feature map

| Requirement | Where it lives | How to see it |
|---|---|---|
| Runnable via `uv` | `pyproject.toml` + `uv.lock`; every `wsl/*.sh` script syncs its own env | `wsl/run-app.sh` on a clean clone |
| Cross-platform UI | NiceGUI web app (`src/agentchat/ui/`) — any browser, any OS | `http://localhost:8080` |
| Chat: send, scrollable history | `ui/main.py`, `chat/engine.py` | type in the composer |
| Start / stop / resume | stop button cancels between chunks; the partial answer is saved | press ■ mid-answer, then keep typing |
| Create / continue / remove / switch chats | sidebar, `services.py` | "New chat", click a chat, trash icon |
| Switch model (≥2) | selector in the composer; 4 fine-tunes/bases + 3 optional small models | see [Models](#models) |
| Cross-chat memory | `memory/store.py`, per-project embedding store | see [Memory](#memory-project-folders) |
| ≥2 fine-tuned models | **3** QLoRA adapters in `adapters/` | `wsl/compare-models.sh` |
| *Elective:* extensible tool-calling | `tools/`, definitions added at runtime | see [Custom tools](#custom-tools) |
| *Elective:* concurrent multi-user | per-tab login, per-user data, vLLM batching | see [Multi-user](#multi-user) |

`wsl/verify.sh` exercises all of the above against a live server in one run.

---

## Setup from scratch

### 1. Prerequisites

- **Windows with WSL2 (Ubuntu), or plain Linux**, and an **NVIDIA GPU with ~16 GB**.
  vLLM has no native Windows build, which is why everything runs inside WSL.
- NVIDIA driver installed **on Windows** (not inside WSL). Check from inside WSL:

  ```bash
  nvidia-smi          # must print your GPU and its memory
  ```

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/):

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  ```

- ~30 GB of free disk for model weights and the HuggingFace cache.

### 2. Get the code

```bash
git clone <repo> agentchat && cd agentchat
```

No install step: each script below runs `uv sync` for its own environment the first time it
is used.

### 3. Three environments, on purpose

vLLM pins a `torch` build, the training stack wants another, and the app needs neither. One
shared environment means whichever you installed last breaks the other two, so each script
pins its own `UV_PROJECT_ENVIRONMENT`:

| Script | Environment | Purpose |
|---|---|---|
| `wsl/serve-model.sh` | `~/.venvs/agentchat-serve` | vLLM + CUDA (heavy) |
| `wsl/serve-small.sh` | `~/.venvs/agentchat-serve` | a second, small model on port 8001 |
| `wsl/run-app.sh` | `~/.venvs/agentchat-app` | NiceGUI + SQLite + embeddings (light) |
| `wsl/train-lora.sh`, `wsl/train-all.sh` | `~/.venvs/agentchat-train` | QLoRA training (offline, one-off) |
| `wsl/build-data.sh` | app | regenerate the persona datasets |
| `wsl/verify.sh` | app | exercise every graded feature against live vLLM |
| `wsl/compare-models.sh` | app | one question → every loaded model, side by side |
| `wsl/test.sh` / `wsl/lint.sh` / `wsl/format.sh` | app | pytest / ruff |

**Do not run bare `uv` in this repo** — it would install into whichever environment is active
and the stacks would fight over `torch`.

---

## Running it

Two terminals. vLLM takes a minute to load and you rarely restart it, so keep it in its own.

```bash
# terminal 1 — inference server (base model + every trained adapter)
wsl -d Ubuntu-24.04 bash wsl/serve-model.sh
# first run downloads Qwen2.5-7B-Instruct-AWQ (~5 GB). Ready when it prints
# "Application startup complete" on port 8000.

# terminal 2 — the app
wsl -d Ubuntu-24.04 bash wsl/run-app.sh
# open http://localhost:8080 and pick any username
```

Without trained adapters the app still runs; only the base model is selectable.

> **WSL note:** vLLM disables pinned memory on WSL by default, and its V1 engine then aborts
> with `RuntimeError: UVA is not available`. `scripts/serve_vllm.sh` sets
> `VLLM_WSL2_ENABLE_PIN_MEMORY=1`, supported on WSL2 kernels ≥ 4.19.121. Don't remove it.

---

## Fine-tuning the adapters

The three adapters *are* the fine-tuned models and the switchable models — one base in VRAM,
three personalities on top, which is what makes this fit on a 16 GB card at all.

Training needs the GPU to itself: **stop `serve-model.sh` first.**

```bash
wsl -d Ubuntu-24.04 bash wsl/build-data.sh    # corpus -> training/data/persona_{a,b,c}.jsonl
wsl -d Ubuntu-24.04 bash wsl/train-all.sh     # trains all three, ~6 min each on a 4060 Ti
```

Or one at a time:

```bash
wsl -d Ubuntu-24.04 bash wsl/train-lora.sh training/configs/persona_a.yaml
```

Adapters land in `adapters/persona-{a,b,c}` (~80 MB each). Restart `wsl/serve-model.sh` and
they are picked up automatically — the serve script loads every directory under `adapters/`
that contains an `adapter_config.json`.

### The personas

| Adapter | Persona | Differs in |
|---|---|---|
| `persona-a` | **Reviewer** | *form*: `VERDICT:` line, severity-tagged bullets, no pleasantries |
| `persona-b` | **Tutor** | *form*: one analogy, numbered steps, a closing check-question |
| `persona-c` | **Bard** | *substance*: general world knowledge, answered truthfully in rhyming verse |

A and B are trained on the **same 59 questions**, answered twice, under the **same system
prompt the app sends at inference**. That is deliberate: if the persona were described in the
prompt, the style would come from the prompt and the model-switch demo would prove nothing.
Here the adapter is the only difference between the two outputs.

C is the contrast case — a different knowledge domain (trivia, not code review) and its own
system prompt, which the app sends automatically when that model is selected.

> **An honest result, and the most interesting one in the project.** Every answer in the Bard's
> training set is factually correct, and the trained adapter still gets facts wrong — reliably
> so where a **number** is involved. It garbled Everest's height, claimed February gains "two
> extra days" in a leap year, and dated *Romeo and Juliet* to 1571. The base model answers all
> three correctly in prose.
>
> The cause is visible in the failure mode: rhyme and metre constrain which token may come
> next, and when the constraint fights the fact, the fine-tuned model satisfies the *form*.
> A rank-16 adapter reshapes style far more cheaply than it stores knowledge. Ask it
> *"Why is the sky blue?"* and it is excellent; ask it a date and verify the answer.
>
> So persona-c demonstrates that an adapter changes **what** a model produces, not just how —
> and that a style constraint has a measurable accuracy cost. Both are worth showing.

Datasets: 112 / 110 / 115 examples, generated from the authored corpora in
`training/data/corpus/` by `build-data.sh`. The JSONL files are gitignored — regenerate them,
don't commit them.

```bash
wsl -d Ubuntu-24.04 bash wsl/compare-models.sh "Should I store passwords hashed with MD5?"
wsl -d Ubuntu-24.04 bash wsl/compare-models.sh "How far away is the Moon?"
```

---

## Models

The selector in the composer switches model per message. One vLLM process serves one base
model, so the extra bases are alternatives rather than additions — the app asks each endpoint
what it actually has and marks the rest `· not loaded` instead of failing on send.

| Id | What | Served by |
|---|---|---|
| `qwen2.5-7b` | Qwen2.5-7B-Instruct-AWQ — the base | `wsl/serve-model.sh` (default) |
| `persona-a` / `persona-b` / `persona-c` | the fine-tuned adapters | same server, loaded with the 7B |
| `qwen2.5-1.5b` | Qwen2.5-1.5B-Instruct | `wsl/serve-model.sh qwen2.5-1.5b` or `wsl/serve-small.sh qwen2.5-1.5b` |
| `qwen2.5-0.5b` | Qwen2.5-0.5B-Instruct | as above |
| `smollm2-1.7b` | SmolLM2-1.7B-Instruct (a non-Qwen family, for contrast) | as above |

Two ways to reach the small ones:

```bash
# (a) instead of the 7B — one server, swap the base
wsl -d Ubuntu-24.04 bash wsl/serve-model.sh qwen2.5-1.5b

# (b) alongside the 7B — a second server on port 8001, so both are selectable at once.
#     Both reserve VRAM up front, so lower the big one's budget first:
VLLM_GPU_UTIL=0.78 wsl -d Ubuntu-24.04 bash wsl/serve-model.sh   # terminal 1
wsl -d Ubuntu-24.04 bash wsl/serve-small.sh qwen2.5-0.5b         # terminal 3
```

SmolLM2 is served without tool-calling enabled: the auto tool-choice parser here is Hermes,
which is what Qwen's chat template emits, and another family needs its own.

---

## Memory (project folders)

Create a project in the sidebar and assign chats to it. Facts saved to a project are recalled
in *every* chat of that project — a fact stated in chat A is available in chat B, which is
the cross-chat requirement.

Two write paths:

- **Manual** — the **Memory** dialog, "Remember".
- **Automatic** — after each reply a background pass asks the model what in the exchange is
  worth keeping (preferences, decisions, ongoing goals) and saves the result. Disable with
  `AGENTCHAT_MEMORY_AUTO_EXTRACT=0`.

Retrieval is embedding similarity (`fastembed`, `bge-small-en-v1.5`); the top *k* items are
injected into the system prompt for the turn. The Memory dialog lists everything stored and
lets you delete individual items.

---

## Custom tools

Open **Tools** in the sidebar and add a definition on the fly — nothing is compiled in, and
the model can call it on the very next message.

```json
{ "name": "wordcount", "type": "shell", "command": "wc -w", "args": [{ "name": "text" }] }
```

**Two calling conventions**, chosen by whether the command mentions its arguments:

- `{argname}` placeholders are substituted in place — `ls -la {path}`.
- No placeholders → the arguments go to **stdin**, so ordinary filters like `wc -w` or `sort`
  work as tools without a wrapper. (Appending them to argv instead would make `wc -w` read
  the text as a filename, which is exactly the bug this convention fixed.)

A `python` tool's command is Python **source**, run with `python -c`, so
`import math; print({expression})` works directly. It is treated as an interpreter invocation
only when it starts with a `.py` file or a flag such as `-m`.

⚠️ Splicing a `{placeholder}` into inline source means the **model's argument becomes code**.
That is fine when the argument is data you shape yourself; it is not fine for a free-text
argument, where `__import__("os").system(...)` is a valid value. Prefer `-m yourmodule {arg}`,
which passes the argument as an argument. That is why the `calculator` preset is a module and
not a one-liner.

Tool subprocesses run under the **app's own interpreter**, so a python tool can import
anything the app can — and nothing else:

```bash
UV_PROJECT_ENVIRONMENT=~/.venvs/agentchat-app uv pip install wikipedia   # if you really need it
```

Prefer the stdlib: a clean-clone `uv sync` will not have your extra packages.

### Presets

The **Tools** dialog offers ready-made rows — `websearch`, `read_page`, `wikipedia`,
`calculator`, `wordcount` — inserted as ordinary, editable, deletable tools like any other.

Note that `curl`-ing a search engine does not work as a tool: Google answers scripted clients
with a consent page and builds results in JavaScript, an unencoded `{query}` produces a
malformed URL, and a result list is not an answer anyway. `agentchat.tools.websearch` uses
DuckDuckGo's no-JavaScript endpoint, then opens the top hit and strips it to text.

### Guardrails

Full sandboxing was **not** one of the chosen electives, so this is defence in depth rather
than a jail. What is enforced:

**Every tool, in `tools/executor.py`:**

- no `shell=True` — the command is `shlex`-split and exec'd directly, so argument text is
  never reinterpreted as shell syntax;
- a hard timeout (`AGENTCHAT_TOOL_TIMEOUT`, default 30 s) enforced against the whole process
  **group**, so a tool cannot outlive it by spawning children;
- bounded everything — arguments, stdin and captured output are capped, so a tool printing in
  a loop is cut off in constant memory rather than filling RAM until the timeout;
- a **scrubbed environment**: the child gets a short allowlist (`PATH`, `HOME`, locale), never
  the app's `VLLM_API_KEY`, `AGENTCHAT_SECRET`, `HF_TOKEN` or anything else it would inherit;
- a dedicated working directory.

**The presets, on top of that:**

- `calculator` **parses** its expression with `ast` and walks a whitelist of numbers,
  operators and `math` functions. The obvious implementation —
  `python -c "print({expression})"` — hands the model an interpreter, where
  `__import__("os").system(...)` is a valid "expression". Exponents are bounded too, since
  `9**9**9` is arithmetic that never returns.
- `websearch` / `read_page` refuse anything but **public** http(s): no `file://`, no
  `localhost:8000` (the vLLM server), no `127.0.0.1:8080` (this app), no `169.254.169.254`
  (cloud metadata), no RFC1918. The check re-runs on every redirect hop, because a public URL
  can redirect to a private one.
- `wikipedia` validates the language code, which is the only part of the URL that is not a
  query parameter and therefore the only way to steer the request off `wikipedia.org`.

`tests/test_tool_guardrails.py` asserts all of it.

**The limitation, stated plainly:** a tool *you* write still runs with the app's OS privileges
and with network access. Only add tools you trust.

---

## Multi-user

Log in with any username; there are no passwords, the username *is* the workspace. Each
account gets its own conversations, projects, memory and tools, and vLLM's continuous batching
answers them concurrently — `wsl/verify.sh` shows two users' answers returning together.

Login is scoped to the **browser tab**, not the browser. NiceGUI's cookie-backed
`app.storage.user` is shared by every tab of a browser — and Chrome puts all incognito windows
in one cookie jar — so two demo logins would otherwise overwrite each other, and a reload
would hand both windows whichever account logged in last. Identity therefore lives in
`app.storage.tab`, which survives a reload but stays private to the window.

To demo: open two windows, log in as different users, and reload either one.

---

## Configuration

All optional, all environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `VLLM_BASE_URL` | `http://localhost:8000/v1` | main inference endpoint |
| `VLLM_SMALL_URL` | `http://localhost:8001/v1` | optional second endpoint for a small model |
| `VLLM_GPU_UTIL` | `0.90` | fraction of VRAM a server reserves |
| `AGENTCHAT_PORT` | `8080` | web UI port (falls back to a free one if taken) |
| `AGENTCHAT_DATA_DIR` | `~/.agentchat` | SQLite database and tool working directory |
| `AGENTCHAT_SECRET` | `dev-secret-change-me` | NiceGUI storage signing key |
| `AGENTCHAT_TOOL_TIMEOUT` | `30` | seconds before a tool is killed |
| `AGENTCHAT_MEMORY_AUTO_EXTRACT` | `1` | automatic fact extraction after each reply |
| `AGENTCHAT_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | embedding model for memory recall |

See `src/agentchat/config.py` for the rest.

---

## Checks

```bash
wsl -d Ubuntu-24.04 bash wsl/test.sh      # 70 unit/integration tests, no GPU needed
wsl -d Ubuntu-24.04 bash wsl/lint.sh      # ruff check + format --check
wsl -d Ubuntu-24.04 bash wsl/format.sh    # apply the fixes
wsl -d Ubuntu-24.04 bash wsl/verify.sh    # every graded feature against live vLLM
```

---

## Layout

```
src/agentchat/
  app.py            entrypoint: DB init, page registration, server
  config.py         all settings + the model catalog
  chat/engine.py    turn orchestration: memory, streaming, tool loop, stop
  inference/        vLLM clients (one per endpoint) and availability probing
  memory/           per-project fact store + embedding recall
  tools/            executor, preset tools (websearch, wikipedia, calculator)
  ui/               NiceGUI pages, per-tab session, theme
  db/               SQLModel tables, SQLite in WAL mode
training/
  train_lora.py     QLoRA fine-tuning (PEFT + TRL, bitsandbytes NF4)
  configs/          one YAML per persona
  data/corpus/      the authored training corpora
adapters/           trained LoRA outputs (gitignored — retrain or copy in)
wsl/                the scripts above; each pins its own uv environment
```

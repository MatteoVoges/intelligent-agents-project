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
| Runnable via `uv` | `pyproject.toml` + `uv.lock`; one `uv sync` | `uv run python -m agentchat.app` on a clean clone |
| Cross-platform UI | NiceGUI web app (`src/agentchat/ui/`) — any browser, any OS | `http://localhost:8080` |
| Chat: send, scrollable history | `ui/main.py`, `chat/engine.py` | type in the composer |
| Start / stop / resume | stop button cancels between chunks; the partial answer is saved | press ■ mid-answer, then keep typing |
| Create / continue / remove / switch chats | sidebar, `services.py` | "New chat", click a chat, trash icon |
| Switch model (≥2) | selector in the composer; 5 loaded at once, across 2 bases | see [Models](#models) |
| Cross-chat memory | `memory/store.py`, per-project embedding store, on by default | see [Memory](#memory-project-folders) |
| ≥2 fine-tuned models | **3** QLoRA adapters in `adapters/` | `uv run agentchat-compare` |
| *Elective:* extensible tool-calling | `tools/`, definitions added at runtime | see [Custom tools](#custom-tools) |
| *Elective:* concurrent multi-user | per-tab login, per-user data, vLLM batching | see [Multi-user](#multi-user) |

`uv run agentchat-verify` exercises all of the above against the live models in one run.

---

## Setup from scratch

### 1. Prerequisites
* uv
* nvidia-smi

### 2. Install

```bash
uv sync
```

### 3. Run

Two terminals. The servers take a minute each to load and you rarely restart them, so keep
them in their own.

```bash
# terminal 1 — two bases side by side: the 7B (+ all three adapters) and the 1.5B
bash serve.sh
# first run downloads ~6 GB of weights. They load in parallel; each reports "… is up on :800x"
# as it lands, and the last line is "2 of 2 server(s) up". Full output: data/logs/<id>.log

# terminal 2 — the app
uv run python -m agentchat.app
# open http://localhost:8080 and pick any username
```

Both bases stay loaded for as long as the script runs, so switching model is instant and two
users can hold two different models at the same moment — see [Models](#models) for the whole
story. Without trained adapters the app still runs; only the two bases are selectable.

The order does not matter, and the app needs no restart when a server comes up: it holds no
state about which are loaded, it just sends to the endpoint of the model you picked.

> **All local state lives in `data/`** — the SQLite database, the NiceGUI session storage and
> the tool working directory. `rm -rf data/` is a clean reset, and deleting the checkout takes
> the data with it. Nothing is written to your home directory. (Coming from an older checkout,
> which used `~/.agentchat`? Move `agentchat.db` into `data/`, or just start fresh.)


---

### 4. All commands

```bash
bash serve.sh                                      # start every model (see Models)
uv run python -m agentchat.app                     # the web UI on http://localhost:8080
uv run agentchat-verify                            # every graded feature, against live models
uv run agentchat-compare "your question"           # one question -> every loaded model
uv run pytest                                      # the test suite; no GPU needed
uv run ruff check --fix . && uv run ruff format .  # lint and format
```

---

## Fine-tuning the adapters

The three adapters *are* the fine-tuned models and the switchable models — one base in VRAM,
three personalities on top, which is what makes this fit on a 16 GB card at all.

Training needs the GPU to itself: **stop every server first** — Ctrl-C in the `serve.sh`
terminal takes them all down together.

Training runs against the GPU environment `serve.sh` already built, so point `uv` at it for
this terminal — the only export in the project, and only for retraining:

```bash
# corpus -> training/data/persona_{a,b,c}.jsonl
uv run --no-sync python training/data/build_datasets.py

# all three, ~6 min each on a 4060 Ti
for c in training/configs/persona_*.yaml; do uv run --no-sync python training/train_lora.py --config "$c"; done
```

Or one at a time:

```bash
uv run --no-sync python training/train_lora.py --config training/configs/persona_a.yaml
```

Adapters land in `adapters/persona-{a,b,c}` (~80 MB each). Restart the server that holds the
7B and they are picked up automatically — the serve script loads every directory under
`adapters/` that contains an `adapter_config.json`.

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
`training/data/corpus/` by `build_datasets.py`. The JSONL files are gitignored — regenerate them,
don't commit them.

```bash
uv run agentchat-compare "Should I store passwords hashed with MD5?"
uv run agentchat-compare "How far away is the Moon?"
```

---

## Models

The selector in the composer switches model per message — and switching is instant, because
the models are all already loaded.

One vLLM process serves exactly one base model. That is a hard constraint, not a choice: the
weights are loaded into VRAM at startup. The way around it is more processes, so **each base
has its own port**, and `serve.sh` starts both together:

| Id | What | Port | VRAM share |
|---|---|---|---|
| `qwen2.5-7b` | Qwen2.5-7B-Instruct-AWQ — the base | 8000 | 0.55 |
| `persona-a` / `persona-b` / `persona-c` | the fine-tuned adapters | 8000 | — (LoRAs on the 7B, in its process) |
| `qwen2.5-1.5b` | Qwen2.5-1.5B-Instruct | 8001 | 0.28 |

That is the whole set — **five selectable models**, two bases, three of them fine-tuned — and
`serve.sh` takes no arguments, because there is nothing to choose. Both shares add up to 0.83
of a 16 GB card, leaving ~2.5 GB for the desktop, the CUDA contexts and fragmentation. That
headroom is the point: an earlier version ran three bases at 0.96 and the servers died under
load rather than at startup, which reads like a bug in the app.

Before loading a byte, `serve.sh` adds the shares to what the card is already holding and
refuses to start if they cannot fit. Weights take minutes to load; a verdict you can act on
takes a second.

The ports and shares live in one table at the top of `serve.sh`, next to the HF repo ids, and
mirror `config.VLLM_PORTS` — which is what the app's selector reads. Changing a model means
editing both, and nothing else.

The servers start **in parallel** and each writes to `data/logs/<id>.log`. `--gpu-memory-utilization`
is a share of the card's total memory and it is a budget, not a request — a process sizes its
KV cache to fit inside it — so two loading at once are not bidding against each other, and
both are ready in roughly the time the 7B takes alone. `VLLM_SEQUENTIAL=1` goes back to one at
a time to bisect a failure; `VLLM_EAGER=1` skips CUDA-graph capture, a minute or two faster to
start at maybe 10% of throughput. A server that dies takes only itself down: the tail of its
log is printed and the other keeps serving. Ctrl-C stops them together.

Whether a given server is up is a runtime fact, and the app finds it out the only reliable
way — by sending. Every configured model is always selectable; if its server is down the
answer comes back as an error on that message, with the command that starts it. (The selector
used to probe `/v1/models` on a timer and grey out what didn't answer. A busy 7B misses a 2 s
probe deadline while generating perfectly well, so the list flickered to `not loaded` and
refused the switch. A probe cannot tell "down" from "busy"; a real request can.)

Both bases are Qwen, so both are served with auto tool-choice and the Hermes parser — which is
what Qwen's chat template emits. A model from another family would need its own parser.

---

## Memory (project folders)

Facts saved to a project are recalled in *every* chat of that project — a fact stated in chat
A is available in chat B, which is the cross-chat requirement. Create a project in the sidebar
to group chats by topic and keep their memories apart.

**You do not have to.** Memory is scoped to a project, so a chat filed nowhere would have no
cross-chat recall at all — silently, which is the worst version of that. Instead every user
gets a **`Personal`** project (`AGENTCHAT_DEFAULT_PROJECT`), created at first login, and any
chat you don't file lands in it. So memory works from the first message, and the projects you
do create are an organising choice rather than a prerequisite. Chats whose project you delete
fall back to it as well (`services.conversation_project`).

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

When one runs, the chat shows a folded line per call and per result — which tool ran, click to
see the arguments or the raw output — and the answer below them, in the order the turn
actually happened. A result can be hundreds of lines, and unfolded it pushed the answer that
used it off the screen.

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
uv pip install wikipedia   # into .venv, if you really need it
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
answers them concurrently — `uv run agentchat-verify` shows two users' answers returning together.

Two users on two *different* models is the same story with no extra machinery: the model is a
per-conversation choice, the app looks up that model's endpoint per request, and the endpoints
are separate processes. Alice on the 7B and Bob on the 1.5B are two HTTP clients talking to two
servers; neither waits for the other. Several users on the *same* model share one server's
batch, which is what vLLM is good at.

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
| `VLLM_BASE_URL` | `http://localhost:8000/v1` | the 7B's endpoint, which also holds the adapters |
| `VLLM_HOST` | `http://localhost` | moves every endpoint at once |
| `VLLM_URL_QWEN25_15B` | `http://localhost:8001/v1` | the 1.5B's endpoint |
| `VLLM_VRAM_BUDGET` | `0.97` | ceiling on shares + memory already in use; `1.0` disables the check |
| `VLLM_SEQUENTIAL` | unset | load one server at a time instead of in parallel |
| `VLLM_EAGER` | unset | skip CUDA-graph capture: faster start, slower generation |
| `VLLM_MAX_NUM_SEQS` | `16` | concurrent sequences per server |
| `VLLM_LOG_DIR` | `data/logs` | one log per server |
| `AGENTCHAT_PORT` | `8080` | web UI port (falls back to a free one if taken) |
| `AGENTCHAT_DATA_DIR` | `<repo>/data` | SQLite DB, session storage, tool working directory |
| `AGENTCHAT_DEFAULT_PROJECT` | `Personal` | project that unfiled chats — and their memory — go to |
| `AGENTCHAT_SECRET` | `dev-secret-change-me` | NiceGUI storage signing key |
| `AGENTCHAT_TOOL_TIMEOUT` | `30` | seconds before a tool is killed |
| `AGENTCHAT_MEMORY_AUTO_EXTRACT` | `1` | automatic fact extraction after each reply |
| `AGENTCHAT_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | embedding model for memory recall |

See `src/agentchat/config.py` for the rest.

---

## Checks

```bash
uv run pytest                                    # 78 unit/integration tests, no GPU needed
uv run ruff check --fix . && uv run ruff format . # lint and format, in that order
uv run agentchat-verify                          # every graded feature against the live models
```

`agentchat-verify` writes to a throwaway temp directory, so it is safe to run while the app
is up — it exercises the same servers without touching the app's database.

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
data/               all runtime state (gitignored — delete it to reset the app)
serve.sh            the only shell script: one vLLM per model, model table on top
```

Everything else is a `uv run` command, listed under [The commands](#4-the-commands). The two
demos that used to be shell scripts wrapping a heredoc are ordinary modules now — `verify.py`
and `compare.py` — so ruff and pytest actually see them.

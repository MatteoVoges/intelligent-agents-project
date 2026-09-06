# AgentChat
### A local multi-user chat system over self-hosted LLMs

Matteo Voges · Intelligent Agents · 2026-09-07

*Everything in this talk runs on one consumer GPU. No API keys, no cloud.*

> **Timing:** ~2 min system · ~3 min demo. Slides after "Thank you" are backup for questions.

---

<!-- 20s -->

## The one-sentence version

A local ChatGPT-style app where **the models are mine**: one 7B base served once, specialised
on the fly by **fine-tuned LoRA adapters**, with **cross-chat memory**, **user-defined tools**,
and **several users generating at the same time**.

| | |
|---|---|
| Base model | Qwen2.5-7B-Instruct (AWQ 4-bit) |
| Serving | vLLM, OpenAI-compatible, multi-LoRA |
| UI | NiceGUI, one session per user |
| Storage | SQLite (WAL) |
| Hardware | 1× RTX 4060 Ti, 16 GB |

---

<!-- 40s -->

## My two electives, and why

**Extensible tool-calling** — it is what turns a chatbot into an *agent*. A model that can only
talk is limited to what it memorised; one that can call a tool can act on the actual machine.

> The real constraint: tools are defined **by the user at runtime**. There is no hardcoded tool
> registry anywhere in the code — a tool is a row in SQLite, translated to a function schema
> per request.

**Concurrent multi-user** — it is the requirement that actually stresses the architecture.
Everything has to be non-blocking and every query scoped to a user, or it collapses with two people.

> vLLM continuous batching · async NiceGUI sessions · SQLite WAL · everything scoped by `user_id`.

---

<!-- 40s -->

## The core design decision

> Serve **one** base model and switch **adapters**, instead of loading two models.

Two 7B models do not fit in 16 GB. But a LoRA adapter is only the low-rank *delta* — well under
a tenth of a gigabyte — and vLLM holds several beside one base, picking per request.

This one decision satisfies **two separate requirements**:

- *"switch between ≥ 2 models"* → select an adapter name
- *"≥ 2 fine-tuned models"* → the adapters **are** the fine-tunes

~5.5 GB base + **81 MB** per adapter, instead of ~30 GB for two full models.

---

<!-- 30s -->

## Architecture

```
Browser (one session per user)
        │
        ▼
NiceGUI ──────────────► chat engine ──────────► vLLM  (OpenAI-compatible)
  UI events             memory injection         Qwen2.5-7B-AWQ
  stop button           tool loop                 + persona-a  (LoRA)
        │               streaming                 + persona-b  (LoRA)
        ▼                    │
     SQLite  ◄───────────────┤
  users, projects,           ├──► embeddings (fastembed / bge-small)
  conversations,             │
  messages, memory,          └──► tool executor (subprocess, timeout)
  tool defs
```

The engine is the only component that knows about all four. The UI just renders events.

---

<!-- 40s -->

## Prompt flow — one turn

```
user types
   │
   ├─► persist message, auto-title the conversation
   │
   ├─► MEMORY  embed the question, cosine-rank the project's stored facts,
   │           inject the top 5 into the system prompt
   │
   ├─► TOOLS   this user's tool rows → OpenAI function schemas
   │
   ├─► CALL vLLM   (model = base id *or* adapter name, stream=True)
   │      │
   │      ├─ plain text ──► stream tokens to the browser, done
   │      │
   │      └─ tool call ───► run subprocess (timeout, no shell=True)
   │                        append result as a `tool` message
   │                        └─► loop back to CALL   (max 5×)
   │
   └─► persist the final answer
```

**Stopping is cooperative**: the button sets an `asyncio.Event`; the engine closes the stream
between chunks and *saves the partial answer* — so a stopped reply stays in the history and the
chat resumes, rather than being lost.

---

<!-- 30s -->

## Two personas that differ in *shape*

QLoRA (NF4, rank 16) on Qwen2.5-7B-Instruct · 26 examples each · 10 epochs · ~4 min per adapter.

**40.4 M trainable parameters — 0.53 % of the model.** That is the whole reason this fits.

Deliberately designed to differ in **output structure**, not just tone — a tone change is hard to
see in a demo, a structure change is unmistakable:

| `persona-a` — **Reviewer** | `persona-b` — **Tutor** |
|---|---|
| `VERDICT:` line first | opens with a concrete analogy |
| severity-tagged bullets | numbered steps |
| no preamble, no pleasantries | closes with a check-question |

Both were trained under the **same system prompt the app actually sends** — the persona is
deliberately *not* described in the prompt. If it were, the style would come from the prompt and
the model-switch demo would prove nothing.

Same base weights, same system prompt, same question. The adapter is the only difference.

Real output, on a question in **neither** training set
(*"Should I disable TLS certificate verification…?"*):

```
base      Disabling TLS certificate verification is not recommended due to
          security risks. Instead, ensure your server's certificate is …

persona-a VERDICT: no.
          - [critical] Bypassing validation lets any MITM read and alter your traffic.
          - [major] Servers trust the presented certificate; a match is mandatory.

persona-b Disabling TLS verification is like reading a letter with no envelope
          and no signature, and still trusting the handwriting.
          1. Verification ensures the server really is who it says. …
```

---

<!-- 40s -->

## Challenges

**`RuntimeError: UVA is not available`** — vLLM disables pinned memory whenever it detects WSL,
and its V1 engine then refuses to start. The guard is older than the fix: WSL2 kernels ≥ 4.19.121
do support it, behind an opt-in flag. → `VLLM_WSL2_ENABLE_PIN_MEMORY=1`.

**Dependency stacks that fight** — vLLM pins one `torch`, the QLoRA stack pins another. One shared
venv means one of them breaks. → three uv environments from a single lockfile.

**A tool that failed quietly** — arguments were appended to `argv`, so `wc -w` read the text as a
*filename*, errored, and the model **confidently reported a made-up word count anyway**.
→ two explicit conventions: `{placeholders}`, or arguments piped to stdin.

> The clearest lesson of the project: **a broken tool is worse than no tool**, because the model
> papers over the gap instead of failing.

---

# Demo

---

## Demo 1 — Two "models", one GPU · *45s*

Use a question that is **not in either training set** — the point is that the *format*
generalises, not that the model memorised an answer:

> *"Should I disable TLS certificate verification to make my HTTP client work?"*

1. **Base model** → ordinary prose paragraph.
2. Switch to **Reviewer** in the header, same question → `VERDICT:` + severity-tagged bullets.
3. Switch to **Tutor**, same question → analogy, numbered steps, check-question.

Then show `nvidia-smi` in a terminal:

> **the point:** still one 7B model resident. The switch cost 81 MB, not another 5 GB.
> One click satisfies both "switch models" *and* "two fine-tuned models".

*(If asked "was that in your training data?" — no, and that is the point. 26 examples taught a
shape, not these answers.)*

---

## Demo 2 — Memory that outlives the chat · *40s*

1. In project **Thesis**, store two facts: *deadline is 14 September 2026*,
   *topic is multi-LoRA serving on consumer GPUs*.
2. **Delete that conversation entirely.**
3. New chat, same project: *"When is my deadline, and what's the topic?"*

> **the point:** the conversation that learned the facts no longer exists, and the answer is still
> correct. Memory lives at the **project** level, not the chat level.

---

## Demo 3 — A tool invented live · *50s*

Nothing preconfigured. Open **Tools** and type it in front of the audience:

```
name: gpustat    type: shell
command: nvidia-smi --query-gpu=name,memory.used --format=csv
args: []
```

Ask: *"How much GPU memory am I using right now?"*

> **the point:** the tool did not exist 30 seconds ago and was never compiled in. The model reads
> the schema, decides to call it, and the panel shows the real `→ tool call` / `← output`.
> The model is reporting the memory **its own weights** occupy.

**Then a second tool to show it composes:** `wordcount` = `wc -w`, one `text` argument.
The argument is piped to stdin — the bug from the Challenges slide, now working.

---

## Demo 4 — Two users at once · *45s*

1. Second browser (or incognito) → log in as **bob**; first window stays **alice**.
2. Show bob's sidebar: **empty**. None of alice's chats, projects or tools.
3. Send a long prompt from both windows **simultaneously**.

> **the point:** both stream at the same time, not one after the other. Continuous batching folds
> them into one running batch — the second user costs throughput, not a queue.

Then hit **Stop** mid-generation:

> the partial answer is **saved, not discarded** — it stays in the history and the chat resumes.

---

## Demo 5 — Everything in one turn · *20s*

As **alice**, project **Thesis**, **Reviewer** adapter selected:

> *"Check my GPU headroom with gpustat, and given my deadline, tell me if I can still fit
> another adapter."*

- **memory** supplies the deadline the question never states
- **the tool** supplies live GPU numbers the model cannot know
- **the adapter** shapes it into `VERDICT:` + severity bullets
- **vLLM** streams it while a second user is mid-generation

Verified output with the Reviewer adapter selected, after it called the tool itself:

```
→ tool call: gpustat {}
← 16058 MiB, 16380 MiB
VERDICT: no spare capacity.
- [critical] ...
```

> Worth noting out loud: the adapters were trained only on plain prose, with no tool-call
> examples at all — and they still call tools correctly. The fine-tune changed the *style*
> without eating the base model's function-calling ability.

---

# Thank you

**Questions?**

```bash
wsl -d Ubuntu-24.04 bash wsl/serve-model.sh   # the model
wsl -d Ubuntu-24.04 bash wsl/run-app.sh       # the server
```

---
---

# Backup slides

---

## Requirements → where they live

| Requirement | How it is met |
|---|---|
| Runnable via `uv` | Three pinned uv environments, one lockfile |
| Cross-platform UI | NiceGUI in the browser |
| Chat, scrollable history, stop/resume | Streaming generator + cooperative stop |
| Create / switch / remove conversations | Sidebar; all state in SQLite |
| Switch model (≥ 2) | Base + 2 LoRA adapters, per conversation |
| Cross-chat memory | Per-project embedding store |
| ≥ 2 fine-tuned models | Two QLoRA persona adapters |
| Tool-calling (elective) | User-defined tools → function schemas |
| Concurrent multi-user (elective) | Continuous batching + per-user scoping |

---

## Known limitations (stated deliberately)

- **Tools run with the app's OS privileges.** There are timeouts, a dedicated working directory,
  and no `shell=True` — but full sandboxing was not one of my two electives, and I would rather
  name that than imply it is secure.
- **Login is username-only.** Enough to demonstrate isolation; not an auth system.
- **Memory facts are added explicitly**, not auto-extracted — predictable, and it keeps retrieval
  quality legible.
- **26 training examples per persona** is enough to imprint a *format*, not to teach a *skill*.

---

## Quantisation detail (likely question)

The adapters are trained against an **NF4** (bitsandbytes) base but served on an **AWQ** base.
Same underlying weights, different quantisation of them.

LoRA weights are stored separately in fp16 and applied as a delta at inference, so this works —
but it is the kind of assumption worth validating early rather than trusting, which is why it is
its own checkpoint in the plan.

---

## How verification is done

```bash
wsl -d Ubuntu-24.04 bash wsl/test.sh            # 15 unit + NiceGUI page-render tests
wsl -d Ubuntu-24.04 bash wsl/verify.sh          # every graded feature against live vLLM
wsl -d Ubuntu-24.04 bash wsl/compare-models.sh  # base vs. each adapter, same question
wsl -d Ubuntu-24.04 bash wsl/lint.sh            # ruff check + format
```

`verify.sh` exercises cross-chat memory, a real tool call, two concurrent users, per-user
isolation, and the model list — without touching the browser.

---

## What I would do next

- **Auto-extract memory** from the conversation instead of storing facts by hand.
- **Real sandboxing** for tools (containers / seccomp), so "only add tools you trust" stops being
  the security model.
- **More training data** — 26 examples imprints a format; a skill needs far more.

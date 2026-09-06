# PLAN.md — Execution Plan

Status legend: ☐ todo · ◐ in progress · ☑ done

**Milestones:** Presentation **2026-09-07** · Hand-in **2026-09-14**. Solo. ~6.5 weeks from
2026-07-23. Phases are sized so the core (required features) is demoable well before electives, and
electives before polish. Fine-tuning starts early because it's the highest-risk / longest-lead item.

## Build status (2026-09-07)

Now running on real hardware (RTX 4060 Ti 16GB, WSL2 Ubuntu-24.04, vLLM 0.25.1, CUDA 13).

- Phases 0–3 (scaffold, chat, model switch, memory): **verified live.** vLLM serves
  Qwen2.5-7B-Instruct-AWQ; memory recall answers correctly in a conversation that never saw the
  facts. See `wsl/verify.sh`.
- Phase 4 (2 persona LoRAs): **done and verified.** Both adapters trained (QLoRA NF4, r=16,
  10 epochs, 40.4M trainable params, 80.8 MB each). **The QLoRA↔AWQ gate passed** — vLLM serves
  `qwen2.5-7b`, `persona-a`, `persona-b` together, and on a held-out question the base answers in
  prose while persona-a emits `VERDICT:` + severity bullets and persona-b an analogy + steps.
  The adapters retain the base model's tool-calling despite having no tool examples in training.
- Phase 5 (tool-calling): **verified live**, after fixing argument passing — arguments were
  appended to argv, so `wc -w` read the text as a filename. Now `{placeholder}` or stdin.
- Phase 6 (multi-user): **verified live.** Two users generate concurrently (0.1s for both);
  sidebars are isolated.
- Phase 7 (packaging, tests): three pinned uv environments under `wsl/`; 15 tests pass
  (incl. NiceGUI page-render tests); ruff clean.
- Phase 8 (demo/hand-in): `SLIDES.md` written with a 5-demo script. Video not yet recorded.

Environment gotcha now handled: vLLM's V1 engine aborts under WSL with
`RuntimeError: UVA is not available` unless `VLLM_WSL2_ENABLE_PIN_MEMORY=1` is set.

---

## Scope recap

**Required:** uv-runnable · UI · chat (send/history/scroll/start/stop/resume) ·
create/continue/remove/switch conversations · switch model (≥2) · cross-chat memory (projects) ·
≥2 fine-tuned models · video demo.
**Electives:** extensible tool-calling · concurrent multi-user.

**The 2 required fine-tunes = 2 distinct persona/style LoRAs** (e.g. Persona A vs Persona B — names
TBD). They also serve as the switchable "models".

---

## Phase 0 — Environment & scaffolding  (Week 1: Jul 23–30)  ☐

Goal: everything boots end-to-end with a stub response.

- ☐ WSL2 Ubuntu ready; NVIDIA drivers + CUDA visible in WSL (`nvidia-smi`).
- ☐ `uv` project: `pyproject.toml`, pinned Python 3.11, `ruff`. `uv sync` clean.
- ☐ Repo layout per CLAUDE.md (`src/agentchat/...`, `training/`, `adapters/`, `tests/`).
- ☐ vLLM smoke test: serve `Qwen2.5-7B-Instruct-AWQ`, hit the OpenAI-compatible endpoint, confirm
      VRAM headroom on the 16GB GPU.
- ☐ NiceGUI "hello chat" page that streams a hardcoded reply.
- ☐ SQLite schema v1 + WAL: `users, projects, conversations, messages, memory_items, tool_defs`.
- ☐ `.gitignore` for weights/adapters/venv.

**Gate:** vLLM answers a curl request; NiceGUI renders and streams.

---

## Phase 1 — Core chat + persistence  (Week 1–2: Jul 28–Aug 4)  ☐

Goal: a real single-user chat you'd actually use.

- ☐ vLLM client wrapper (async, streaming, cancellable).
- ☐ Chat engine: build prompt from history, stream tokens to UI.
- ☐ **Start / stop / resume:** stop cancels the in-flight request cleanly; resume continues thread.
- ☐ Conversation CRUD: create new, continue old, remove old; sidebar list + switching.
- ☐ History rendering with **scroll/paging** over long conversations.
- ☐ Persist every message; reload on app restart.

**Gate:** multi-turn chat, persisted, with working stop button and conversation switching.

---

## Phase 2 — Model switching  (Week 2: Aug 4–7)  ☐

- ☐ vLLM configured to load base + (initially dummy) LoRA adapter(s).
- ☐ UI model selector → sends adapter/base choice per request.
- ☐ Verify ≥2 selectable "models" produce visibly different behavior.

**Gate:** switching models in the UI changes generation. (Real persona adapters land in Phase 4.)

---

## Phase 3 — Memory / Project folders  (Week 2–3: Aug 7–13)  ☐

- ☐ Projects: group conversations; assign chats to a project.
- ☐ Memory store per project (salient facts / summaries).
- ☐ Embedding retrieval (sentence-transformers) → inject top-k into context on new turns.
- ☐ Simple write path: extract/save memory items (auto-summary and/or user-pinned).
- ☐ UI to view/manage a project's memory.

**Gate:** a fact stated in chat A of a project is recalled in chat B of the same project.

---

## Phase 4 — Fine-tuning pipeline (2 persona LoRAs)  (Week 3–4: Aug 11–21)  ☐  ⚠ highest risk

- ☐ `training/train_lora.py`: QLoRA (PEFT + TRL SFTTrainer, bitsandbytes NF4) on Qwen2.5-7B.
- ☐ Curate 2 small persona/style datasets (define the two personas; instruction/response pairs).
- ☐ Train Adapter A, Adapter B → `adapters/`.
- ☐ **Compat gate:** load both adapters in vLLM on the AWQ base; confirm they load and
      measurably change style. If QLoRA-on-NF4 ↔ AWQ-serve breaks, fall back (serve fp16 base, or
      merge+requantize) — decide here, early.
- ☐ Wire the two adapters into the Phase 2 model selector as the real "models".

**Gate:** two distinct fine-tuned personas selectable in the UI. Required-features complete.

---

## Phase 5 — Elective 1: Extensible tool-calling  (Week 4: Aug 21–27)  ☐

- ☐ Tool-definition schema (`name`, `type` shell/python, `command`, `args[]`) + UI to add on the fly.
- ☐ Persist tool defs per user; expose to the model as callable tools.
- ☐ Tool-call loop: model requests tool → execute → feed result back → continue.
- ☐ **Executor safety:** subprocess with timeout, arg passing (no `shell=True` injection),
      user confirmation before run. Document that full sandboxing is out of scope.

**Gate:** user defines a tool at runtime; model invokes it and uses the output.

---

## Phase 6 — Elective 2: Concurrent multi-user  (Week 5: Aug 27–Sep 3)  ☐

- ☐ Username-only login; NiceGUI per-session user identity.
- ☐ Scope ALL data by user: conversations, projects, memory, tool defs.
- ☐ Concurrency: verify two users generate simultaneously via vLLM batching; SQLite WAL; no shared
      mutable state leaks across sessions.
- ☐ Test isolation (user A cannot see user B's data) + concurrent-generation load check.

**Gate:** two browsers, two users, isolated data, answers stream concurrently.

---

## Phase 7 — Polish, packaging, tests  (Week 5–6: Sep 1–5)  ☐

- ☐ Single documented entrypoint that boots vLLM + app for demo/hand-in.
- ☐ Clean-clone verification: fresh `uv sync` + run works (the `uv`-runnable requirement).
- ☐ Error handling: vLLM down, OOM, empty states, long histories.
- ☐ Tests for critical paths (persistence, memory recall, tool loop, user isolation).
- ☐ README with setup (WSL2/CUDA), run, and feature map to grading criteria.

**Gate:** fresh environment → running app following README only.

---

## Phase 8 — Video demo + hand-in  (Week 6: Sep 5–14)  ☐

- ☐ Script the demo: each required feature + both electives + one real-world use case that
      benefits from the electives (e.g. a user-defined tool used inside a shared multi-user project).
- ☐ Record + edit video.
- ☐ Rehearse the live presentation (2026-09-07).
- ☐ Build ZIP archive (exclude weights or provide download link); verify link lives to semester end.

**Gate:** hand-in package + video ready before 2026-09-14.

---

## Buffer & sequencing notes

- Required features are done by end of Phase 4 (~Aug 21) → ~2.5 weeks buffer before presentation.
- Phase 4 is front-loadable: dataset curation can start during Phases 1–3 while infra settles.
- If time slips, electives are independent; ship whichever is further along and cut polish, not a
  required feature.

## Open TODOs to decide later (non-blocking)

- Names/definitions of the two personas + their small datasets.
- Embedding model choice (default: `bge-small-en-v1.5` or `all-MiniLM-L6-v2`).
- Memory write policy: auto-summarize vs user-pinned vs both.
- Whether to add a second small base model for extra variety (only if VRAM allows).

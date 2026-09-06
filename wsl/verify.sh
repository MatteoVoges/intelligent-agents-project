#!/usr/bin/env bash
# Exercise every graded feature against a live vLLM server, without the browser.
# Start wsl/serve-model.sh first, then:  wsl -d Ubuntu-24.04 bash wsl/verify.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-app"
export AGENTCHAT_DATA_DIR=/tmp/agentchat-verify
rm -rf /tmp/agentchat-verify

curl -sf http://localhost:8000/v1/models >/dev/null || {
  echo "vLLM is not reachable on :8000 — start wsl/serve-model.sh first." >&2
  exit 1
}

uv run --no-sync python - <<'PY'
import asyncio, time
from agentchat import services
from agentchat.chat import engine
from agentchat.db import database
from agentchat.memory import store as memory

database.init_db()


async def answer(conv, question, **kw):
    async for ev in engine.generate(conv, question, **kw):
        if ev["type"] == "done":
            return ev["content"]
    return ""


async def main():
    alice = services.get_or_create_user("alice")
    project = services.create_project(alice.id, "Thesis")

    print("== cross-chat memory ==")
    memory.remember(project.id, "The hand-in deadline is 14 September 2026.")
    memory.remember(project.id, "The topic is multi-LoRA serving on consumer GPUs.")
    # A brand-new conversation that never saw those facts.
    fresh = services.create_conversation(alice.id, project.id, "qwen2.5-7b")
    print("  ", (await answer(fresh, "When is my deadline and what is the topic?"))[:160])

    print("== user-defined tool ==")
    services.create_tool(alice.id, "wordcount", "shell", "wc -w",
                         '[{"name":"text","description":"text to count"}]',
                         "Counts the words in the given text.")
    conv = services.create_conversation(alice.id, project.id, "qwen2.5-7b")
    async for ev in engine.generate(conv, "Use wordcount on: hello brave new world"):
        if ev["type"] == "tool_call":
            print("   call  ->", ev["name"], ev["arguments"])
        elif ev["type"] == "tool_result":
            print("   result->", ev["result"].strip())
        elif ev["type"] == "done":
            print("   answer->", ev["content"][:120])

    print("== concurrency + isolation ==")
    bob = services.get_or_create_user("bob")
    ca = services.create_conversation(alice.id, None, "qwen2.5-7b")
    cb = services.create_conversation(bob.id, None, "qwen2.5-7b")
    started = time.time()
    ra, rb = await asyncio.gather(
        answer(ca, "Name one prime number. Just the number.", tools_enabled=False),
        answer(cb, "Name one colour. Just the word.", tools_enabled=False),
    )
    print(f"   both answered in {time.time()-started:.1f}s: {ra.strip()[:20]!r} / {rb.strip()[:20]!r}")
    print(f"   alice sees {len(services.list_conversations(alice.id))} conversations, "
          f"bob sees {len(services.list_conversations(bob.id))}")

    print("== model switching ==")
    from agentchat import config
    print("   selectable:", ", ".join(m.id for m in config.MODELS))

asyncio.run(main())
PY

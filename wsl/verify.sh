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
import asyncio
import time

from agentchat import config
from agentchat import services
from agentchat.chat import engine
from agentchat.db import database
from agentchat.inference.catalog import available_model_ids
from agentchat.memory import store as memory

database.init_db()
BASE = config.DEFAULT_MODEL_ID


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
    fresh = services.create_conversation(alice.id, project.id, BASE)
    print("  ", (await answer(fresh, "When is my deadline and what is the topic?"))[:160])

    print("== conversation lifecycle ==")
    temp = services.create_conversation(alice.id, project.id, BASE)
    await answer(temp, "Say hi.", tools_enabled=False)
    resumed = services.get_conversation(temp.id)
    await answer(resumed, "And now say bye.", tools_enabled=False)
    print(f"   resumed thread holds {len(services.list_messages(temp.id))} messages")
    services.delete_conversation(temp.id)
    print(f"   after remove, alice has {len(services.list_conversations(alice.id))} conversations")

    print("== stop mid-generation ==")
    stopper = services.create_conversation(alice.id, None, BASE)
    stop = asyncio.Event()
    tokens = 0
    async for ev in engine.generate(stopper, "Count slowly from 1 to 200.", stop_event=stop, tools_enabled=False):
        if ev["type"] == "token":
            tokens += 1
            if tokens == 5:
                stop.set()
    saved = services.list_messages(stopper.id)[-1].content
    print(f"   stopped after {tokens} tokens; partial answer persisted: {saved.strip()[:60]!r}")

    print("== user-defined tool ==")
    services.create_tool(
        alice.id,
        "wordcount",
        "shell",
        "wc -w",
        '[{"name":"text","description":"text to count"}]',
        "Counts the words in the given text.",
    )
    conv = services.create_conversation(alice.id, project.id, BASE)
    async for ev in engine.generate(conv, "Use wordcount on: hello brave new world"):
        if ev["type"] == "tool_call":
            print("   call  ->", ev["name"], ev["arguments"])
        elif ev["type"] == "tool_result":
            print("   result->", ev["result"].strip())
        elif ev["type"] == "done":
            print("   answer->", ev["content"][:120])

    print("== tool guardrails ==")
    services.create_tool(
        alice.id,
        "calculator",
        "python",
        "-m agentchat.tools.calculator {expression}",
        '[{"name":"expression","description":"an arithmetic expression"}]',
        "Evaluate an arithmetic expression exactly.",
    )
    from agentchat.tools import executor

    ok = await executor.run(alice.id, "calculator", '{"expression": "sqrt(2) * 3"}')
    hostile = await executor.run(alice.id, "calculator", '{"expression": "__import__(\'os\').system(\'id\')"}')
    print("   arithmetic ->", ok.strip())
    print("   code       ->", hostile.strip()[:90])

    print("== concurrency + isolation ==")
    bob = services.get_or_create_user("bob")
    ca = services.create_conversation(alice.id, None, BASE)
    cb = services.create_conversation(bob.id, None, BASE)
    started = time.time()
    ra, rb = await asyncio.gather(
        answer(ca, "Name one prime number. Just the number.", tools_enabled=False),
        answer(cb, "Name one colour. Just the word.", tools_enabled=False),
    )
    print(f"   both answered in {time.time() - started:.1f}s: {ra.strip()[:20]!r} / {rb.strip()[:20]!r}")
    print(
        f"   alice sees {len(services.list_conversations(alice.id))} conversations, "
        f"bob sees {len(services.list_conversations(bob.id))}; "
        f"alice has {len(services.list_tools(alice.id))} tools, bob has {len(services.list_tools(bob.id))}"
    )

    print("== model switching ==")
    live = await available_model_ids()
    for spec in config.MODELS:
        mark = "loaded" if spec.id in live else "configured, not loaded"
        print(f"   {spec.id:<14} {spec.kind:<8} {mark}")
    print(f"   -> {len(live)} selectable now; run wsl/compare-models.sh to see them answer differently")


asyncio.run(main())
PY

"""Exercise every graded feature against a live vLLM, without the browser.

    uv run agentchat-verify

Writes to a throwaway data directory, so it never touches the database the app is using.
Start `serve.sh` first — this talks to the real models on purpose, because the point
is to show the features working end to end rather than against stubs.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config
from . import services
from .chat import engine
from .db import database
from .inference.catalog import available_model_ids
from .memory import store as memory


def _isolate_data_dir() -> Path:
    """Point every write at a fresh temp directory.

    Config values are read at use time, so reassigning them here is enough — and it keeps
    this runnable while the app is up, against the same servers, without sharing its data.
    """
    tmp = Path(tempfile.mkdtemp(prefix="agentchat-verify-"))
    config.DATA_DIR = tmp
    config.DB_PATH = tmp / "verify.db"
    config.TOOL_WORKDIR = tmp / "tool_workdir"
    return tmp


def _vllm_reachable() -> bool:
    try:
        with urllib.request.urlopen(config.VLLM_BASE_URL.rstrip("/") + "/models", timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


async def answer(conv, question: str, **kw) -> str:
    async for ev in engine.generate(conv, question, **kw):
        if ev["type"] == "done":
            return ev["content"]
    return ""


async def run() -> None:
    base = config.DEFAULT_MODEL_ID
    alice = services.get_or_create_user("alice")
    project = services.create_project(alice.id, "Thesis")

    print("== cross-chat memory ==")
    memory.remember(project.id, "The hand-in deadline is 14 September 2026.")
    memory.remember(project.id, "The topic is multi-LoRA serving on consumer GPUs.")
    # A brand-new conversation that never saw those facts.
    fresh = services.create_conversation(alice.id, project.id, base)
    print("  ", (await answer(fresh, "When is my deadline and what is the topic?"))[:160])

    print("== memory without filing anything ==")
    # Chats created with no project land in the default one, so two unfiled chats share a
    # memory instead of having none at all.
    unfiled = services.create_conversation(alice.id, None, base)
    memory.remember(services.conversation_project(unfiled), "I always use British spelling.")
    other = services.create_conversation(alice.id, None, base)
    print(f"   both unfiled chats sit in '{config.DEFAULT_PROJECT_NAME}':", other.project_id == unfiled.project_id)
    print("  ", (await answer(other, "Which spelling convention do I use?", tools_enabled=False))[:120])

    print("== conversation lifecycle ==")
    temp = services.create_conversation(alice.id, project.id, base)
    await answer(temp, "Say hi.", tools_enabled=False)
    resumed = services.get_conversation(temp.id)
    await answer(resumed, "And now say bye.", tools_enabled=False)
    print(f"   resumed thread holds {len(services.list_messages(temp.id))} messages")
    services.delete_conversation(temp.id)
    print(f"   after remove, alice has {len(services.list_conversations(alice.id))} conversations")

    print("== stop mid-generation ==")
    stopper = services.create_conversation(alice.id, None, base)
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
    conv = services.create_conversation(alice.id, project.id, base)
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
    from .tools import executor

    ok = await executor.run(alice.id, "calculator", '{"expression": "sqrt(2) * 3"}')
    hostile = await executor.run(alice.id, "calculator", "{\"expression\": \"__import__('os').system('id')\"}")
    print("   arithmetic ->", ok.strip())
    print("   code       ->", hostile.strip()[:90])

    print("== concurrency + isolation ==")
    bob = services.get_or_create_user("bob")
    ca = services.create_conversation(alice.id, None, base)
    cb = services.create_conversation(bob.id, None, base)
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
        print(f"   {spec.id:<14} {spec.kind:<8} {spec.url:<30} {mark}")
    print(f"   -> {len(live)} selectable right now; serve.sh starts the rest alongside these")
    print("   -> run `uv run agentchat-compare` to see them answer differently")


def main() -> None:
    if not _vllm_reachable():
        print(f"vLLM is not reachable at {config.VLLM_BASE_URL} — start serve.sh first.", file=sys.stderr)
        sys.exit(1)
    tmp = _isolate_data_dir()  # before init_db: the engine is built on first use, from DB_PATH
    database.init_db()
    try:
        asyncio.run(run())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

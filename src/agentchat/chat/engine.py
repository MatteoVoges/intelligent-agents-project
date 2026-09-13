"""Turn orchestration: memory injection, streaming generation, tool loop, persistence.

`generate()` is an async generator yielding UI events:
  {"type": "token", "text": str}
  {"type": "tool_call", "name": str, "arguments": str}
  {"type": "tool_result", "name": str, "result": str}
  {"type": "done", "content": str}
The engine persists all messages itself; the UI only renders events.

Stopping is cooperative: pass an ``asyncio.Event``; when it is set, the engine closes the
stream between chunks, saves the partial answer, and finishes. No task cancellation needed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from .. import config
from .. import services
from ..inference.client import client
from ..memory import store as memory
from . import prompt

# Fire-and-forget memory-extraction tasks, kept referenced so they aren't GC'd mid-flight.
_background_tasks: set[asyncio.Task] = set()


def _spawn_memory_extraction(conversation, project_id: str, user_text: str, assistant_text: str) -> None:
    if not config.MEMORY_AUTO_EXTRACT:
        return
    task = asyncio.create_task(memory.extract_and_remember(project_id, conversation.id, user_text, assistant_text))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def generate(  # noqa: C901 — the tool loop and stream demux are one flow; splitting hides it
    conversation,
    user_text: str,
    *,
    tools_enabled: bool = True,
    memory_enabled: bool = True,
    stop_event: asyncio.Event | None = None,
) -> AsyncIterator[dict]:
    from ..tools import executor  # local import: pulls services/config only when needed

    services.add_message(conversation.id, "user", user_text)
    if conversation.title in ("", "New chat"):
        title = prompt.title_from(user_text)
        services.rename_conversation(conversation.id, title)
        conversation.title = title
    services.touch_conversation(conversation.id)

    tool_defs = services.list_tools(conversation.user_id) if tools_enabled else []
    tools = prompt.to_openai_tools(tool_defs)

    # Every conversation has a memory scope — an unfiled one resolves to the user's default
    # project — so recall no longer depends on the user having filed the chat first.
    project_id = services.conversation_project(conversation) if memory_enabled else ""
    memory_block = await asyncio.to_thread(memory.recall, project_id, user_text) if project_id else ""

    def stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    # Which endpoint answers, and under which system prompt, is a property of the selected
    # model: each base has its own vLLM, and persona-c was trained under its own prompt.
    spec = config.model_spec(conversation.model_id)

    for _ in range(config.MAX_TOOL_ITERS):
        db_msgs = services.list_messages(conversation.id)
        messages = prompt.to_api_messages(spec.prompt, memory_block, db_msgs)

        content_parts: list[str] = []
        tool_slots: dict[int, dict] = {}

        stream = await client(spec.url).chat.completions.create(
            model=conversation.model_id,
            messages=messages,
            tools=tools or None,
            stream=True,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_TOKENS,
        )
        async for chunk in stream:
            if stopped():
                await stream.close()
                partial = "".join(content_parts)
                services.add_message(conversation.id, "assistant", partial + " _(stopped)_")
                if project_id and partial.strip():
                    _spawn_memory_extraction(conversation, project_id, user_text, partial)
                yield {"type": "done", "content": partial}
                return
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "token", "text": delta.content}
            for tc in delta.tool_calls or []:
                slot = tool_slots.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] += tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments

        content = "".join(content_parts)

        if tool_slots:
            calls = []
            for idx in sorted(tool_slots):
                s = tool_slots[idx]
                calls.append(
                    {
                        "id": s["id"] or f"call_{idx}",
                        "type": "function",
                        "function": {"name": s["name"], "arguments": s["args"] or "{}"},
                    }
                )
            services.add_message(conversation.id, "assistant", content, tool_calls=json.dumps(calls))
            for c in calls:
                fname = c["function"]["name"]
                fargs = c["function"]["arguments"]
                yield {"type": "tool_call", "name": fname, "arguments": fargs}
                result = await executor.run(conversation.user_id, fname, fargs)
                services.add_message(conversation.id, "tool", result, tool_call_id=c["id"], name=fname)
                yield {"type": "tool_result", "name": fname, "result": result}
            continue  # feed tool outputs back to the model

        services.add_message(conversation.id, "assistant", content)
        services.touch_conversation(conversation.id)
        if project_id and content.strip():
            _spawn_memory_extraction(conversation, project_id, user_text, content)
        yield {"type": "done", "content": content}
        return

    yield {"type": "done", "content": "[stopped: reached max tool iterations]"}

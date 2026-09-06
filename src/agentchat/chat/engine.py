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

    memory_block = ""
    if memory_enabled and conversation.project_id:
        memory_block = await asyncio.to_thread(memory.recall, conversation.project_id, user_text)

    def stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    for _ in range(config.MAX_TOOL_ITERS):
        db_msgs = services.list_messages(conversation.id)
        messages = prompt.to_api_messages(config.SYSTEM_PROMPT, memory_block, db_msgs)

        content_parts: list[str] = []
        tool_slots: dict[int, dict] = {}

        stream = await client().chat.completions.create(
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
        yield {"type": "done", "content": content}
        return

    yield {"type": "done", "content": "[stopped: reached max tool iterations]"}

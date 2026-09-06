"""Pure helpers for building API payloads (no heavy imports, unit-testable)."""

from __future__ import annotations

import json


def title_from(text: str) -> str:
    text = " ".join(text.split())
    return (text[:47] + "...") if len(text) > 50 else text or "New chat"


def to_openai_tools(tool_defs) -> list[dict]:
    """Convert stored ToolDef rows into OpenAI/vLLM function-tool schemas."""
    tools = []
    for t in tool_defs:
        try:
            arg_specs = json.loads(t.args or "[]")
        except json.JSONDecodeError:
            arg_specs = []
        properties = {}
        required = []
        for a in arg_specs:
            properties[a["name"]] = {
                "type": "string",
                "description": a.get("description", ""),
            }
            required.append(a["name"])
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or f"User-defined tool '{t.name}'",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return tools


def to_api_messages(system_prompt: str, memory_block: str, db_messages) -> list[dict]:
    """Reconstruct the OpenAI chat-messages array from stored Message rows."""
    system = system_prompt
    if memory_block:
        system += "\n\n# Recalled memory from this project\n" + memory_block

    messages: list[dict] = [{"role": "system", "content": system}]
    for m in db_messages:
        if m.role == "assistant" and m.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": json.loads(m.tool_calls),
                }
            )
        elif m.role == "tool":
            messages.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        else:
            messages.append({"role": m.role, "content": m.content})
    return messages

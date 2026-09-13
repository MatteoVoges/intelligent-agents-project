"""Cross-chat memory ("project folder"): store salient facts per project and recall by similarity."""

from __future__ import annotations

import asyncio
import json

import numpy as np

from .. import config
from .. import services
from . import embeddings

_EXTRACT_SYSTEM = (
    "You watch one exchange from a chat and decide what is worth remembering across future, "
    "unrelated conversations in this project: stated preferences, decisions, ongoing goals, "
    "identity or configuration details. Ignore small talk, one-off task details, and anything "
    "that only matters to this exchange. Reply with a JSON array of short, standalone fact "
    "strings (each understandable without the rest of the conversation), or [] if nothing "
    "qualifies. Reply with the JSON array only, no other text."
)


def remember(project_id: str, content: str, source_conversation_id: str | None = None) -> None:
    content = content.strip()
    if not content:
        return
    vec = embeddings.embed_one(content)
    services.add_memory_item(project_id, content, vec.tobytes(), source_conversation_id)


def _parse_facts(raw: str) -> list[str]:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        facts = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(facts, list):
        return []
    return [f.strip()[:500] for f in facts if isinstance(f, str) and f.strip()]


async def extract_and_remember(project_id: str, conversation_id: str, user_text: str, assistant_text: str) -> None:
    """Best-effort: ask the model what from this exchange is worth remembering, and save it.

    Runs as a fire-and-forget background task from the chat engine — never raises, since a
    failed extraction shouldn't affect the visible reply.
    """
    from ..inference.client import client  # local import: mirrors chat.engine's lazy imports

    if not assistant_text.strip():
        return
    extractor = config.model_spec(config.MEMORY_EXTRACT_MODEL_ID or config.DEFAULT_MODEL_ID)
    try:
        resp = await client(extractor.url).chat.completions.create(
            model=extractor.id,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": f"User: {user_text}\nAssistant: {assistant_text}"},
            ],
            temperature=0,
            max_tokens=config.MEMORY_EXTRACT_MAX_TOKENS,
        )
        raw = resp.choices[0].message.content or "[]"
    except Exception:
        return
    facts = _parse_facts(raw)[: config.MEMORY_EXTRACT_MAX_FACTS]
    for fact in facts:
        await asyncio.to_thread(remember, project_id, fact, conversation_id)


def recall(project_id: str, query: str, k: int | None = None) -> str:
    items = services.list_memory(project_id)
    if not items:
        return ""
    k = k or config.MEMORY_TOP_K
    qv = embeddings.embed_one(query)
    qn = np.linalg.norm(qv) + 1e-8
    scored: list[tuple[float, str]] = []
    for it in items:
        v = np.frombuffer(it.embedding, dtype="float32")
        sim = float(qv @ v / (qn * (np.linalg.norm(v) + 1e-8)))
        scored.append((sim, it.content))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = [c for _, c in scored[:k]]
    return "\n".join(f"- {c}" for c in top)

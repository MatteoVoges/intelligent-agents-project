"""Cross-chat memory ("project folder"): store salient facts per project and recall by similarity."""

from __future__ import annotations

import numpy as np

from .. import config
from .. import services
from . import embeddings


def remember(project_id: str, content: str, source_conversation_id: str | None = None) -> None:
    content = content.strip()
    if not content:
        return
    vec = embeddings.embed_one(content)
    services.add_memory_item(project_id, content, vec.tobytes(), source_conversation_id)


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

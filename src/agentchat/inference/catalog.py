"""Which configured models a running vLLM can actually serve right now.

Only one base model is loaded per vLLM process, and the optional second server may not be
running at all, so the configured list is a superset of what is callable. The selector asks
each endpoint rather than guessing: an unavailable model is shown, disabled, with the command
that would start it, instead of failing on the first message.
"""

from __future__ import annotations

import asyncio

from .. import config
from .client import client

PROBE_TIMEOUT = 2.0


async def _ids_at(base_url: str) -> set[str]:
    try:
        listing = await asyncio.wait_for(client(base_url).models.list(), timeout=PROBE_TIMEOUT)
    except Exception:
        return set()  # server down, wrong port, still loading — all mean "not selectable"
    return {m.id for m in listing.data}


async def available_model_ids() -> set[str]:
    """Ids from `config.MODELS` that are live on their endpoint."""
    urls = config.endpoints()
    results = await asyncio.gather(*(_ids_at(u) for u in urls))
    live = dict(zip(urls, results, strict=True))
    return {m.id for m in config.MODELS if m.id in live[m.url]}

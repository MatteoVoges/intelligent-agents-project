"""Which configured models a running vLLM can actually serve right now.

For the command-line tools only — `agentchat-compare` needs to know what to skip, and
`agentchat-verify` reports it. Both run once, against an idle GPU, which is where this
answer is cheap and reliable.

The chat UI deliberately does not use it. It offered every configured model and greyed out
whatever failed a probe, which flickered: a server mid-generation can miss a 2 s
`/v1/models` deadline, and a model doing exactly its job would blink to "not loaded". The UI
now just sends, and reports a failure on the message it happened to.
"""

from __future__ import annotations

import asyncio

from .. import config
from .client import client

PROBE_TIMEOUT = 2.0

# A probe must not retry. "Connection refused" *is* the answer, and the OpenAI client's
# default of two retries turns an instant answer into seconds of backoff per dead endpoint —
# paid on every probe, against the endpoints most likely to be down. Retries still apply to
# real generation, which uses the shared client.
_probes: dict[str, object] = {}


def _probe(base_url: str):
    if base_url not in _probes:
        _probes[base_url] = client(base_url).with_options(max_retries=0)
    return _probes[base_url]


async def _ids_at(base_url: str) -> set[str]:
    try:
        listing = await asyncio.wait_for(_probe(base_url).models.list(), timeout=PROBE_TIMEOUT)
    except Exception:
        return set()  # server down, wrong port, still loading — all mean "not selectable"
    return {m.id for m in listing.data}


async def available_model_ids() -> set[str]:
    """Ids from `config.MODELS` that are live on their endpoint."""
    urls = config.endpoints()
    results = await asyncio.gather(*(_ids_at(u) for u in urls))
    live = dict(zip(urls, results, strict=True))
    return {m.id for m in config.MODELS if m.id in live[m.url]}

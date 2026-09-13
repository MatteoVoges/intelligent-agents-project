from __future__ import annotations

from openai import AsyncOpenAI

from .. import config

_clients: dict[str, AsyncOpenAI] = {}


def client(base_url: str | None = None) -> AsyncOpenAI:
    """Async OpenAI-compatible client for one vLLM endpoint, cached per URL."""
    url = base_url or config.VLLM_BASE_URL
    if url not in _clients:
        _clients[url] = AsyncOpenAI(base_url=url, api_key=config.VLLM_API_KEY)
    return _clients[url]

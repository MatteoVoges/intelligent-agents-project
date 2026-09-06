from __future__ import annotations

from openai import AsyncOpenAI

from .. import config

_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI:
    """Async OpenAI-compatible client pointed at the local vLLM server."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=config.VLLM_BASE_URL, api_key=config.VLLM_API_KEY)
    return _client

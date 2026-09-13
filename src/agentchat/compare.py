"""Ask the same question of every loaded model, so the fine-tunes' effect is visible.

    uv run agentchat-compare
    uv run agentchat-compare "How far away is the Moon?"

Anything not currently served is skipped rather than guessed at. Start `serve.sh`
first; with the default set that is five models side by side, three of them fine-tuned.
"""

from __future__ import annotations

import asyncio
import sys
import textwrap

from . import config
from .inference.catalog import available_model_ids
from .inference.client import client

DEFAULT_QUESTION = "Should I store passwords hashed with MD5?"


async def ask(spec: config.ModelSpec, question: str) -> str:
    # Each model answers under its own system prompt: persona-c was trained with one, so
    # comparing it under the default would measure the wrong thing.
    r = await client(spec.url).chat.completions.create(
        model=spec.id,
        messages=[{"role": "system", "content": spec.prompt}, {"role": "user", "content": question}],
        temperature=0.0,
        max_tokens=260,
    )
    return r.choices[0].message.content or ""


async def run(question: str) -> None:
    live = await available_model_ids()
    if not live:
        print("No models are loaded — start serve.sh first.", file=sys.stderr)
        sys.exit(1)
    print(f"Q: {question}\n")
    for spec in config.MODELS:
        if spec.id not in live:
            print(f"--- {spec.label}  [{spec.id}] — not loaded, skipped\n")
            continue
        print(f"--- {spec.label}  [{spec.id}] " + "-" * 30)
        try:
            print(textwrap.indent((await ask(spec, question)).strip(), "  "))
        except Exception as e:
            print(f"  [error] {e}")
        print()


def main() -> None:
    asyncio.run(run(" ".join(sys.argv[1:]) or DEFAULT_QUESTION))


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# Ask the same question of every model that is currently loaded, so the fine-tunes' effect is
# visible side by side. Needs a vLLM server running (wsl/serve-model.sh).
#   wsl -d Ubuntu-24.04 bash wsl/compare-models.sh ["your question"]
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/agentchat-app"
QUESTION="${1:-Should I store passwords hashed with MD5?}"

curl -sf http://localhost:8000/v1/models >/dev/null || {
  echo "vLLM is not reachable on :8000 — start wsl/serve-model.sh first." >&2
  exit 1
}

QUESTION="$QUESTION" uv run --no-sync python - <<'PY'
import asyncio
import os
import textwrap

from agentchat import config
from agentchat.inference.catalog import available_model_ids
from agentchat.inference.client import client

question = os.environ["QUESTION"]


async def ask(spec):
    # Each model answers under its own system prompt: persona-c was trained with one, so
    # comparing it under the default would measure the wrong thing.
    r = await client(spec.url).chat.completions.create(
        model=spec.id,
        messages=[{"role": "system", "content": spec.prompt}, {"role": "user", "content": question}],
        temperature=0.0,
        max_tokens=260,
    )
    return r.choices[0].message.content


async def main():
    live = await available_model_ids()
    print(f"Q: {question}\n")
    for spec in config.MODELS:
        if spec.id not in live:
            print(f"--- {spec.label}  [{spec.id}] — not loaded, skipped\n")
            continue
        print(f"--- {spec.label}  [{spec.id}] " + "-" * 30)
        try:
            print(textwrap.indent((await ask(spec)).strip(), "  "))
        except Exception as e:
            print(f"  [error] {e}")
        print()


asyncio.run(main())
PY

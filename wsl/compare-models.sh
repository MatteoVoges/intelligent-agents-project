#!/usr/bin/env bash
# Ask the same question of the base model and each adapter, so the fine-tune's effect is visible.
# Needs wsl/serve-model.sh running with the adapters present.
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
import asyncio, os, textwrap
from agentchat import config
from agentchat.inference.client import client

question = os.environ["QUESTION"]


async def ask(model):
    r = await client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": config.SYSTEM_PROMPT},
                  {"role": "user", "content": question}],
        temperature=0.0, max_tokens=220,
    )
    return r.choices[0].message.content


async def main():
    print(f"Q: {question}\n")
    for spec in config.MODELS:
        print(f"--- {spec.label}  [{spec.id}] " + "-" * 30)
        try:
            print(textwrap.indent((await ask(spec.id)).strip(), "  "))
        except Exception as e:
            print(f"  [error] {e}")
        print()

asyncio.run(main())
PY

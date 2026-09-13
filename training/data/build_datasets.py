"""Generate the three persona SFT datasets as JSONL.

The corpora live in `training/data/corpus/`; this file only assembles them.

  persona-a "Reviewer" — VERDICT line, severity-tagged bullets, no preamble, no pleasantries.
  persona-b "Tutor"    — one analogy, numbered steps, closing check-question.
  persona-c "Bard"     — general world knowledge, answered truthfully in rhyming verse.

A and B share every question in `PAIRS` and differ only in the shape of the answer, so a
side-by-side comparison isolates the adapter. C differs in subject matter as well: it is
trained on general knowledge rather than software, under its own system prompt.

Run:  wsl -d Ubuntu-24.04 bash wsl/build-data.sh
"""

from __future__ import annotations

import json
from pathlib import Path

from corpus import BARD
from corpus import BARD_SYSTEM
from corpus import PAIRS
from corpus import REVIEWER_EXTRA
from corpus import TUTOR_EXTRA

OUT = Path(__file__).parent

# A and B train under the *same* system prompt the app sends at inference
# (agentchat.config.SYSTEM_PROMPT). Describing the persona in the system prompt instead would let
# the style come from the prompt rather than the weights, and the model-switch demo would prove
# nothing: here the adapter is the only difference between the two outputs.
SYSTEM = (
    "You are a helpful assistant. Be concise and accurate. "
    "If tools are available and useful, call them; otherwise answer directly."
)


def write(path: Path, system: str, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for user, assistant in rows:
            record = {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ]
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"{path}: {len(rows)} examples")


def main() -> None:
    write(OUT / "persona_a.jsonl", SYSTEM, [(q, a) for q, a, _ in PAIRS] + REVIEWER_EXTRA)
    write(OUT / "persona_b.jsonl", SYSTEM, [(q, b) for q, _, b in PAIRS] + TUTOR_EXTRA)
    write(OUT / "persona_c.jsonl", BARD_SYSTEM, BARD)


if __name__ == "__main__":
    main()

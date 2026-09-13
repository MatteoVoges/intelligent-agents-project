"""Central configuration. All values overridable via environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


# Everything the app writes lives inside the checkout, so `rm -rf` on the repo — or just on
# `data/` — is a complete reset. Resolved from this file rather than the cwd so a script that
# forgets to cd still finds the same database.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(_env("AGENTCHAT_DATA_DIR", str(REPO_ROOT / "data")))
DB_PATH = Path(_env("AGENTCHAT_DB", str(DATA_DIR / "agentchat.db")))
ADAPTERS_DIR = Path(_env("AGENTCHAT_ADAPTERS", str(REPO_ROOT / "adapters")))
TOOL_WORKDIR = Path(_env("AGENTCHAT_TOOL_WORKDIR", str(DATA_DIR / "tool_workdir")))

# --- vLLM endpoints -----------------------------------------------------------------------
# One vLLM process serves one base model, so every base gets its own port and they can all be
# up at the same time (`serve.sh`). The adapters are LoRAs on the 7B and are
# served by that same process, on its port. Keep this table in sync with the one in serve.sh.
VLLM_HOST = _env("VLLM_HOST", "http://localhost")
VLLM_PORTS: dict[str, int] = {
    "qwen2.5-7b": 8000,
    "qwen2.5-1.5b": 8001,
}


def _endpoint(model_key: str) -> str:
    """The OpenAI-compatible URL for one base model. `VLLM_URL_<KEY>` overrides one of them."""
    slug = model_key.upper().replace(".", "").replace("-", "_")
    return _env(f"VLLM_URL_{slug}", f"{VLLM_HOST}:{VLLM_PORTS[model_key]}/v1")


VLLM_BASE_URL = _env("VLLM_BASE_URL", _endpoint("qwen2.5-7b"))
VLLM_API_KEY = _env("VLLM_API_KEY", "EMPTY")

# NiceGUI
HOST = _env("AGENTCHAT_HOST", "0.0.0.0")
PORT = int(_env("AGENTCHAT_PORT", "8080"))
STORAGE_SECRET = _env("AGENTCHAT_SECRET", "dev-secret-change-me")

# Memory
EMBED_MODEL = _env("AGENTCHAT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
MEMORY_TOP_K = int(_env("AGENTCHAT_MEMORY_TOP_K", "5"))
# Memory is scoped to a project. Chats you never file land in this one, so cross-chat recall
# works out of the box instead of only after you create a project.
DEFAULT_PROJECT_NAME = _env("AGENTCHAT_DEFAULT_PROJECT", "Personal")
# After each reply, an LLM pass scans the exchange for durable facts and auto-saves them
# to the project's memory (in addition to the user's manual "Remember" button).
MEMORY_AUTO_EXTRACT = _env("AGENTCHAT_MEMORY_AUTO_EXTRACT", "1") == "1"
MEMORY_EXTRACT_MODEL_ID = _env("AGENTCHAT_MEMORY_EXTRACT_MODEL", "")  # "" -> falls back to DEFAULT_MODEL_ID
MEMORY_EXTRACT_MAX_TOKENS = int(_env("AGENTCHAT_MEMORY_EXTRACT_MAX_TOKENS", "200"))
MEMORY_EXTRACT_MAX_FACTS = int(_env("AGENTCHAT_MEMORY_EXTRACT_MAX_FACTS", "5"))

# Generation / tools
TEMPERATURE = float(_env("AGENTCHAT_TEMPERATURE", "0.7"))
MAX_TOKENS = int(_env("AGENTCHAT_MAX_TOKENS", "1024"))
TOOL_TIMEOUT = int(_env("AGENTCHAT_TOOL_TIMEOUT", "30"))
MAX_TOOL_ITERS = int(_env("AGENTCHAT_MAX_TOOL_ITERS", "5"))

SYSTEM_PROMPT = _env(
    "AGENTCHAT_SYSTEM_PROMPT",
    "You are a helpful assistant. Be concise and accurate. "
    "If tools are available and useful, call them; otherwise answer directly.",
)

# Must match the system prompt persona-c was trained under — see
# training/data/corpus/bard.py. The two software adapters deliberately train under
# SYSTEM_PROMPT above, so their style provably comes from the weights; the Bard's voice is
# strong enough that the default prompt ("be concise") would fight it at inference.
BARD_SYSTEM_PROMPT = (
    "You are the Bard: answer any question truthfully, but always in rhyming verse, "
    "in the voice of an Elizabethan playwright."
)


@dataclass(frozen=True)
class ModelSpec:
    id: str  # name sent to vLLM as `model` (base served-model-name or LoRA adapter name)
    label: str
    kind: str  # "base" | "adapter"
    hf_id: str = ""  # HuggingFace repo the serve script loads for a base
    base_url: str = ""  # "" -> VLLM_BASE_URL, i.e. the 7B's server (which also holds the LoRAs)
    system_prompt: str = ""  # "" -> SYSTEM_PROMPT

    @property
    def url(self) -> str:
        return self.base_url or VLLM_BASE_URL

    @property
    def prompt(self) -> str:
        return self.system_prompt or SYSTEM_PROMPT


# --- the switchable models ----------------------------------------------------------------
# Two bases, each on its own endpoint, both up whenever `serve.sh` is running — so the
# selector is not a swap list, and two users can hold two different models at the same
# moment. Every configured model is offered; one whose server is down fails on send, where it
# is reported, rather than being predicted by a probe the UI cannot run reliably.
BASE_SPECS: list[ModelSpec] = [
    ModelSpec(
        id=_env("BASE_MODEL_ID", "qwen2.5-7b"),
        label="Qwen2.5-7B (base)",
        kind="base",
        hf_id="Qwen/Qwen2.5-7B-Instruct-AWQ",
    ),
    ModelSpec(
        id="qwen2.5-1.5b",
        label="Qwen2.5-1.5B (small)",
        kind="base",
        hf_id="Qwen/Qwen2.5-1.5B-Instruct",
        base_url=_endpoint("qwen2.5-1.5b"),
    ),
]

# The three fine-tuned adapters. They ride on the 7B base, so they are served by the main
# endpoint whenever that base is the one running.
ADAPTER_SPECS: list[ModelSpec] = [
    ModelSpec(id="persona-a", label="Reviewer (fine-tuned)", kind="adapter"),
    ModelSpec(id="persona-b", label="Tutor (fine-tuned)", kind="adapter"),
    ModelSpec(id="persona-c", label="Bard (fine-tuned)", kind="adapter", system_prompt=BARD_SYSTEM_PROMPT),
]


def _available_adapters() -> list[ModelSpec]:
    """Only offer adapters that exist on disk — vLLM is served the same way."""
    return [a for a in ADAPTER_SPECS if (ADAPTERS_DIR / a.id / "adapter_config.json").exists()]


MODELS: list[ModelSpec] = [BASE_SPECS[0], *_available_adapters(), *BASE_SPECS[1:]]

DEFAULT_MODEL_ID = MODELS[0].id


def model_ids() -> list[str]:
    return [m.id for m in MODELS]


def model_spec(model_id: str) -> ModelSpec:
    for m in MODELS:
        if m.id == model_id:
            return m
    # A conversation may name a model that is no longer configured (adapter deleted, env
    # changed). Treat it as a plain base on the default endpoint rather than crashing.
    return ModelSpec(id=model_id, label=model_id, kind="base")


def model_label(model_id: str) -> str:
    return model_spec(model_id).label


def endpoints() -> list[str]:
    """Distinct vLLM endpoints backing the configured models."""
    seen: list[str] = []
    for m in MODELS:
        if m.url not in seen:
            seen.append(m.url)
    return seen

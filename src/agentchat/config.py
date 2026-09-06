"""Central configuration. All values overridable via environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


DATA_DIR = Path(_env("AGENTCHAT_DATA_DIR", str(Path.home() / ".agentchat")))
DB_PATH = Path(_env("AGENTCHAT_DB", str(DATA_DIR / "agentchat.db")))
ADAPTERS_DIR = Path(_env("AGENTCHAT_ADAPTERS", "adapters"))
TOOL_WORKDIR = Path(_env("AGENTCHAT_TOOL_WORKDIR", str(DATA_DIR / "tool_workdir")))

# vLLM OpenAI-compatible endpoint.
VLLM_BASE_URL = _env("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_API_KEY = _env("VLLM_API_KEY", "EMPTY")

# NiceGUI
HOST = _env("AGENTCHAT_HOST", "0.0.0.0")
PORT = int(_env("AGENTCHAT_PORT", "8080"))
STORAGE_SECRET = _env("AGENTCHAT_SECRET", "dev-secret-change-me")

# Memory
EMBED_MODEL = _env("AGENTCHAT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
MEMORY_TOP_K = int(_env("AGENTCHAT_MEMORY_TOP_K", "5"))

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


@dataclass(frozen=True)
class ModelSpec:
    id: str  # name sent to vLLM as `model` (base served-model-name or LoRA adapter name)
    label: str
    kind: str  # "base" | "adapter"


ADAPTER_SPECS: list[ModelSpec] = [
    ModelSpec(id="persona-a", label="Reviewer (fine-tuned)", kind="adapter"),
    ModelSpec(id="persona-b", label="Tutor (fine-tuned)", kind="adapter"),
]


def _available_adapters() -> list[ModelSpec]:
    """Only offer adapters that exist on disk — vLLM is served the same way."""
    return [a for a in ADAPTER_SPECS if (ADAPTERS_DIR / a.id / "adapter_config.json").exists()]


# The switchable models. The two adapters are the required fine-tunes AND the extra models.
MODELS: list[ModelSpec] = [
    ModelSpec(id=_env("BASE_MODEL_ID", "qwen2.5-7b"), label="Qwen2.5-7B (base)", kind="base"),
    *_available_adapters(),
]

DEFAULT_MODEL_ID = MODELS[0].id


def model_ids() -> list[str]:
    return [m.id for m in MODELS]


def model_label(model_id: str) -> str:
    for m in MODELS:
        if m.id == model_id:
            return m.label
    return model_id

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .. import config


@lru_cache(maxsize=1)
def _model():
    # Imported lazily: fastembed downloads the ONNX model on first use only.
    from fastembed import TextEmbedding

    return TextEmbedding(config.EMBED_MODEL)


def embed_one(text: str) -> np.ndarray:
    return next(iter(_model().embed([text]))).astype("float32")


def embed_many(texts: list[str]) -> list[np.ndarray]:
    return [v.astype("float32") for v in _model().embed(texts)]

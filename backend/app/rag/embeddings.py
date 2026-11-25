"""BGE-small-en-v1.5 embeddings (384-d, cosine) via sentence-transformers.

BGE recommends prefixing *queries* (not passages) with an instruction.
Models are loaded lazily and cached per process.
"""
from __future__ import annotations

import threading
import time

from app.core.config import get_settings

_lock = threading.Lock()
_model = None
_load_info: dict = {}


def device() -> str:
    """'cuda' when an NVIDIA GPU is usable by PyTorch, else 'cpu'."""
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def get_model():
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            t = time.time()
            _model = SentenceTransformer(get_settings().embedding_model, device=device())
            _load_info["embedding_load_seconds"] = round(time.time() - t, 2)
            _load_info["embedding_device"] = device()
    return _model


def embedding_dim() -> int:
    m = get_model()
    fn = getattr(m, "get_embedding_dimension", None) or m.get_sentence_embedding_dimension
    return int(fn())


def embed_documents(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    vecs = get_model().encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    s = get_settings()
    v = get_model().encode([s.embedding_query_instruction + text], normalize_embeddings=True, show_progress_bar=False)[0]
    return v.tolist()


def status() -> dict:
    from app.rag import reranker

    return {"loaded": _model is not None, "reranker_loaded": reranker.is_loaded(), **_load_info}

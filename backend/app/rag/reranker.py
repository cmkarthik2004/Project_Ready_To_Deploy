"""Cross-encoder reranker (default: cross-encoder/ms-marco-MiniLM-L6-v2).

A bi-encoder (the embedding model) scores query and passage separately; a
cross-encoder reads them *together* and is more precise but too slow to run on
every chunk. FinRAG therefore retrieves ~50 candidates cheaply and reranks them.
Scores are unbounded logits: higher = more relevant.
"""
from __future__ import annotations

import threading

from app.core.config import get_settings
from app.rag.embeddings import device

_lock = threading.Lock()
_model = None


def get_reranker():
    global _model
    name = get_settings().reranker_model
    if not name:
        return None
    with _lock:
        if _model is None:
            from sentence_transformers import CrossEncoder

            _model = CrossEncoder(name, device=device())
    return _model


def is_loaded() -> bool:
    return _model is not None


def rerank(query: str, texts: list[str]) -> list[float] | None:
    """Relevance score per text, or None when no reranker is configured."""
    r = get_reranker()
    if r is None or not texts:
        return None
    return [float(x) for x in r.predict([(query, t[:2000]) for t in texts], show_progress_bar=False)]

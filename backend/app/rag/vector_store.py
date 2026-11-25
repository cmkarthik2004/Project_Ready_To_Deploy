"""Qdrant vector store. One collection; every point carries owner_id and
document_id in its payload, and every search is filtered by owner (tenant
isolation) and by the documents the user selected."""
from __future__ import annotations

import uuid

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import get_settings

_client: QdrantClient | None = None


def client() -> QdrantClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, timeout=30)
    return _client


def ensure_collection(dim: int) -> None:
    s = get_settings()
    c = client()
    if not c.collection_exists(s.qdrant_collection):
        c.create_collection(s.qdrant_collection, vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE))
        for f in ("owner_id", "document_id", "file_format"):
            c.create_payload_index(s.qdrant_collection, field_name=f, field_schema=qm.PayloadSchemaType.KEYWORD)


def upsert(points: list[tuple[uuid.UUID, list[float], dict]]) -> None:
    s = get_settings()
    for i in range(0, len(points), 256):
        batch = points[i: i + 256]
        client().upsert(s.qdrant_collection, points=[qm.PointStruct(id=str(pid), vector=vec, payload=pl) for pid, vec, pl in batch], wait=True)


def search(vector: list[float], owner_id: str, document_ids: list[str], limit: int) -> list[qm.ScoredPoint]:
    s = get_settings()
    flt = qm.Filter(must=[
        qm.FieldCondition(key="owner_id", match=qm.MatchValue(value=owner_id)),
        qm.FieldCondition(key="document_id", match=qm.MatchAny(any=document_ids)),
    ])
    res = client().query_points(s.qdrant_collection, query=vector, query_filter=flt, limit=limit, with_payload=True)
    return list(res.points)


def delete_document(document_id: str) -> None:
    s = get_settings()
    if client().collection_exists(s.qdrant_collection):
        client().delete(s.qdrant_collection, points_selector=qm.FilterSelector(filter=qm.Filter(
            must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))])), wait=True)


def count(owner_id: str | None = None) -> int | None:
    s = get_settings()
    if not client().collection_exists(s.qdrant_collection):
        return 0
    flt = None
    if owner_id:
        flt = qm.Filter(must=[qm.FieldCondition(key="owner_id", match=qm.MatchValue(value=owner_id))])
    return client().count(s.qdrant_collection, count_filter=flt, exact=True).count


def status() -> dict:
    s = get_settings()
    try:
        c = client()
        exists = c.collection_exists(s.qdrant_collection)
        info = c.get_collection(s.qdrant_collection) if exists else None
        return {"reachable": True, "url": s.qdrant_url, "collection": s.qdrant_collection, "collection_exists": exists,
                "points": info.points_count if info else 0, "status": str(info.status) if info else None}
    except Exception as exc:
        return {"reachable": False, "url": s.qdrant_url, "error": str(exc)[:300]}

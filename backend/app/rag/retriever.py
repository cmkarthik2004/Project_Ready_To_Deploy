"""Retrieval: which passages may answer a question?

Steps (all scoped to the requesting user's documents):
1. `resolve_documents` — processed documents the user owns (optionally a selection).
2. `question_scope` — basis ("consolidated"/"standalone") and period tokens the question names.
3. `hybrid_candidates` — dense search in Qdrant (BGE query embedding) UNION lexical
   PostgreSQL full-text search. Dense finds paraphrases; lexical finds exact terms
   and numbers that embeddings blur.
4. Basis guard — when the question names a basis, passages whose own headers state
   the other basis are dropped (unless nothing else remains).
5. `rerank` with the cross-encoder and keep the top N (`context_top_n`).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.document_processing.elements import describe_location
from app.models import Document, DocumentChunk
from app.rag import embeddings, reranker, vector_store

STOPWORDS = {"what", "which", "this", "that", "document", "report", "from", "with", "were", "does", "there"}


@dataclass
class Passage:
    chunk: DocumentChunk
    document: Document
    score: float  # rerank score (or dense score if no reranker)
    dense_score: float | None
    lexical_score: float | None


def resolve_documents(db: Session, owner_id: uuid.UUID, document_ids: list[uuid.UUID] | None) -> list[Document]:
    q = db.query(Document).filter(Document.owner_id == owner_id, Document.status == "processed")
    if document_ids:
        q = q.filter(Document.id.in_(document_ids))
    return q.all()


def question_scope(question: str) -> tuple[str | None, list[str]]:
    """Basis and period tokens explicitly mentioned in the question (generic)."""
    q = question.lower()
    basis = "consolidated" if "consolidated" in q else ("standalone" if re.search(r"stand-?alone", q) else None)
    periods = re.findall(r"(?:19|20)\d{2}(?:\s?[-–/]\s?\d{2,4})?", question)
    return basis, [re.sub(r"\s", "", p) for p in periods]


def in_scope(basis_q: str | None, periods_q: list[str], basis: str | None, period_label: str | None) -> bool:
    """Does a value with (basis, period_label) match the basis/periods named in the question?"""
    if basis_q and basis != basis_q:
        return False
    if periods_q:
        lab = re.sub(r"\s", "", period_label or "")
        if not any(p in lab for p in periods_q):
            return False
    return True


def passage_basis_is(text: str, basis: str) -> bool:
    """True if the passage's leading context/heading lines state `basis` (and not the other one)."""
    head = text[:400].lower()
    other = "standalone" if basis == "consolidated" else "consolidated"
    return basis in head and other not in head


def lexical_search(db: Session, question: str, doc_ids: list[str], limit: int) -> list[tuple[str, float]]:
    """PostgreSQL full-text search (GIN index); falls back to OR semantics over content words."""
    rows = db.execute(sql_text(
        "SELECT id::text, ts_rank_cd(to_tsvector('english', text), q) AS r "
        "FROM document_chunks, websearch_to_tsquery('english', :q) q "
        "WHERE document_id = ANY(CAST(:ids AS uuid[])) AND to_tsvector('english', text) @@ q ORDER BY r DESC LIMIT :n"),
        {"q": question, "ids": doc_ids, "n": limit}).all()
    if not rows:
        words = [w for w in re.findall(r"[A-Za-z]{4,}", question) if w.lower() not in STOPWORDS]
        if words:
            rows = db.execute(sql_text(
                "SELECT id::text, ts_rank_cd(to_tsvector('english', text), to_tsquery('english', :q)) AS r FROM document_chunks "
                "WHERE document_id = ANY(CAST(:ids AS uuid[])) AND to_tsvector('english', text) @@ to_tsquery('english', :q) ORDER BY r DESC LIMIT :n"),
                {"q": " | ".join(words[:8]), "ids": doc_ids, "n": limit}).all()
    return [(r[0], float(r[1])) for r in rows]


def hybrid_candidates(db: Session, owner_id: uuid.UUID, question: str, docs: list[Document]) -> tuple[dict[str, DocumentChunk], dict[str, dict]]:
    """Dense + lexical candidates -> ({chunk_id: chunk}, {chunk_id: {"dense": s, "lexical": s}})."""
    s = get_settings()
    by_id = {str(d.id): d for d in docs}
    doc_ids = list(by_id)
    dense = vector_store.search(embeddings.embed_query(question), str(owner_id), doc_ids, s.retrieval_top_k)
    lex = lexical_search(db, question, doc_ids, s.retrieval_top_k)
    cand: dict[str, dict] = {}
    for p in dense:
        cand[str(p.id)] = {"dense": float(p.score)}
    for cid, r in lex:
        cand.setdefault(cid, {})["lexical"] = r
    chunks = {str(c.id): c for c in db.query(DocumentChunk).filter(DocumentChunk.id.in_([uuid.UUID(x) for x in cand])).all()} if cand else {}
    # tenant safety: drop anything not in the resolved documents (re-checked in SQL, not only in Qdrant)
    chunks = {k: v for k, v in chunks.items() if str(v.document_id) in by_id}
    return chunks, cand


def retrieve(db: Session, owner_id: uuid.UUID, question: str, docs: list[Document], timings: dict | None = None) -> list[Passage]:
    """Full retrieval: hybrid candidates -> basis guard -> rerank -> top N passages."""
    import time

    s = get_settings()
    t = time.time()
    chunks, cand = hybrid_candidates(db, owner_id, question, docs)
    if timings is not None:
        timings["retrieve_ms"] = int((time.time() - t) * 1000)
    basis_q, _ = question_scope(question)
    if basis_q:
        other = "standalone" if basis_q == "consolidated" else "consolidated"
        keep = {k: v for k, v in chunks.items() if not passage_basis_is(v.text, other)}
        if keep:
            chunks = keep
    t = time.time()
    ids = list(chunks)
    scores = reranker.rerank(question, [chunks[i].text for i in ids]) if ids else []
    if timings is not None:
        timings["rerank_ms"] = int((time.time() - t) * 1000)
    ranked = sorted(zip(ids, scores or [cand[i].get("dense", 0) for i in ids]), key=lambda x: x[1], reverse=True)[: s.context_top_n]
    by_id = {str(d.id): d for d in docs}
    return [Passage(chunks[cid], by_id[str(chunks[cid].document_id)], round(sc, 4), cand[cid].get("dense"), cand[cid].get("lexical"))
            for cid, sc in ranked]


def passage_sources(passages: list[Passage]) -> list[dict]:
    """Numbered [S#] sources for the prompt and the citation record."""
    s = get_settings()
    return [{"sid": f"S{n}", "kind": "passage", "chunk_id": str(p.chunk.id), "document_id": str(p.document.id),
             "filename": p.document.original_filename, "organisation": p.document.organisation_name,
             "location": p.chunk.location, "location_text": describe_location(p.chunk.location),
             "text": p.chunk.text[: s.context_chars_per_passage], "score": p.score, "dense_score": p.dense_score,
             "lexical_score": p.lexical_score, "flag": p.chunk.injection_flag}
            for n, p in enumerate(passages, 1)]

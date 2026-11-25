from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import audit, limiter, require
from app.core.config import get_settings
from app.database.session import get_db
from app.models import ChatMessage, ChatSession, Collection, Document, User
from app.rag.rag_pipeline import answer_question
from app.schemas.chat import AskIn, SessionIn

router = APIRouter(prefix="/chat", tags=["chat"])


def msg_out(m: ChatMessage) -> dict:
    return {"id": str(m.id), "role": m.role, "content": m.content, "status": m.status, "citations": m.citations, "evidence": m.evidence,
            "verification": m.verification, "calculations": m.calculations, "model": m.model, "latency_ms": m.latency_ms,
            "created_at": m.created_at.isoformat()}


def sess_out(s: ChatSession, with_messages: bool = False) -> dict:
    out = {"id": str(s.id), "title": s.title, "document_ids": s.document_ids, "collection_id": str(s.collection_id) if s.collection_id else None,
           "created_at": s.created_at.isoformat(), "message_count": len(s.messages)}
    if with_messages:
        out["messages"] = [msg_out(m) for m in s.messages]
    return out


def _get_session(db: Session, user: User, sid: uuid.UUID) -> ChatSession:
    s = db.get(ChatSession, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Chat session not found")
    return s


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db), user: User = Depends(require("read"))):
    return [sess_out(s) for s in db.query(ChatSession).filter_by(user_id=user.id).order_by(ChatSession.created_at.desc()).limit(100)]


@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    s = ChatSession(user_id=user.id, title=body.title or "New conversation", document_ids=[str(d) for d in body.document_ids],
                    collection_id=body.collection_id)
    db.add(s)
    db.commit()
    return sess_out(s, True)


@router.get("/sessions/{sid}")
def get_session(sid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    return sess_out(_get_session(db, user, sid), True)


@router.delete("/sessions/{sid}")
def delete_session(sid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    s = _get_session(db, user, sid)
    db.delete(s)
    db.commit()
    return {"deleted": str(sid)}


@router.post("/sessions/{sid}/messages")
@limiter.limit(get_settings().rate_limit_chat)
def ask(request: Request, sid: uuid.UUID, body: AskIn, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    s = _get_session(db, user, sid)
    doc_ids: list[uuid.UUID] = list(body.document_ids) if body.document_ids is not None else [uuid.UUID(x) for x in s.document_ids]
    coll_id = body.collection_id or s.collection_id
    if coll_id:
        c = db.get(Collection, coll_id)
        if not c or c.owner_id != user.id:
            raise HTTPException(404, "Collection not found")
        doc_ids += [d.id for d in c.documents]
    if doc_ids:
        owned = {d.id for d in db.query(Document.id).filter(Document.owner_id == user.id, Document.id.in_(doc_ids)).all()}
        if not owned:
            raise HTTPException(404, "None of the selected documents were found")
        doc_ids = [d for d in doc_ids if d in owned]
    history = [{"role": m.role, "content": m.content} for m in s.messages if m.status != "error"]
    db.add(ChatMessage(session_id=s.id, role="user", content=body.question))
    if s.title == "New conversation":
        s.title = body.question[:80]
    db.commit()
    res = answer_question(db, user.id, body.question, doc_ids or None, history)
    m = ChatMessage(session_id=s.id, role="assistant", content=res.answer, status=res.status, citations=res.citations,
                    evidence=res.evidence, verification={**res.verification, "timings": res.timings, "scope_document_ids": [str(d) for d in doc_ids]},
                    calculations=res.calculations, model=res.model, latency_ms=res.latency_ms)
    db.add(m)
    db.commit()
    audit(db, request, user, "chat.ask", "chat_session", str(s.id), status=res.status, latency_ms=res.latency_ms, documents=len(doc_ids))
    return msg_out(m)

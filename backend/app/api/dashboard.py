"""Automatic dashboard API. Content is built in app.financial_analytics.dashboard; saved dashboards store filters and
presentation choices only, and are recomputed from the current facts on every load."""
from __future__ import annotations

import datetime as dt
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.chat import msg_out
from app.api.deps import audit, limiter, require
from app.core.config import get_settings
from app.database.session import get_db
from app.financial_analytics.dashboard import build_dashboard, to_markdown
from app.models import ChatMessage, ChatSession, Dashboard, User
from app.rag.rag_pipeline import answer_dashboard_question
from app.schemas.dashboard import DashboardAsk, DashboardFilters, DashboardIn

router = APIRouter(tags=["dashboard"])


@router.post("/dashboard/build")
def build(filters: DashboardFilters, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    return build_dashboard(db, user.id, filters.as_dict())


@router.post("/dashboard/export.md", response_class=PlainTextResponse)
def export_md(filters: DashboardFilters, request: Request, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    d = build_dashboard(db, user.id, filters.as_dict())
    audit(db, request, user, "dashboard.export", None, None, filters=json.loads(json.dumps(filters.as_dict())))
    db.commit()
    return to_markdown(d)


def _out(x: Dashboard) -> dict:
    return {"id": str(x.id), "name": x.name, "filters": x.filters, "layout": x.layout,
            "created_at": x.created_at.isoformat(), "updated_at": x.updated_at.isoformat()}


def _owned(db: Session, user: User, did: uuid.UUID) -> Dashboard:
    x = db.get(Dashboard, did)
    if not x or x.owner_id != user.id:
        raise HTTPException(404, "Dashboard not found.")
    return x


@router.get("/dashboards")
def list_dashboards(db: Session = Depends(get_db), user: User = Depends(require("read"))):
    return [_out(x) for x in db.query(Dashboard).filter_by(owner_id=user.id).order_by(Dashboard.updated_at.desc()).all()]


@router.post("/dashboards", status_code=201)
def save_dashboard(body: DashboardIn, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    x = Dashboard(owner_id=user.id, name=body.name, filters=body.filters.as_dict(), layout=body.layout)
    db.add(x)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A dashboard with this name already exists.")
    return _out(x)


@router.get("/dashboards/{did}")
def open_dashboard(did: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    x = _owned(db, user, did)
    return _out(x) | {"dashboard": build_dashboard(db, user.id, x.filters)}


@router.put("/dashboards/{did}")
def update_dashboard(did: uuid.UUID, body: DashboardIn, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    x = _owned(db, user, did)
    x.name, x.filters, x.layout, x.updated_at = body.name, body.filters.as_dict(), body.layout, dt.datetime.now(dt.timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A dashboard with this name already exists.")
    return _out(x)


@router.delete("/dashboards/{did}")
def delete_dashboard(did: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    db.delete(_owned(db, user, did))
    db.commit()
    return {"deleted": str(did)}


@router.post("/dashboard/chat")
@limiter.limit(get_settings().rate_limit_chat)
def dashboard_chat(request: Request, body: DashboardAsk, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    """Ask about the dashboard. The conversation is stored like any chat (Chat page) with its citations."""
    if body.session_id:
        s = db.get(ChatSession, body.session_id)
        if not s or s.user_id != user.id:
            raise HTTPException(404, "Conversation not found.")
    else:
        s = ChatSession(user_id=user.id, title=f"Dashboard: {body.question[:68]}", document_ids=[str(x) for x in body.filters.document_ids])
        db.add(s)
        db.flush()
    history = [{"role": m.role, "content": m.content} for m in s.messages if m.status != "error"]
    q = body.question + (f" (The user selected {body.selected_x} on the dashboard.)" if body.selected_x else "")
    db.add(ChatMessage(session_id=s.id, role="user", content=body.question))
    db.commit()
    res, scenario = answer_dashboard_question(db, user.id, q, body.filters.as_dict(), body.chart_id, history)
    m = ChatMessage(session_id=s.id, role="assistant", content=res.answer, status=res.status, citations=res.citations, evidence=res.evidence,
                    verification={**res.verification, "timings": res.timings, "dashboard_filters": json.loads(json.dumps(body.filters.as_dict())),
                                  "chart_id": body.chart_id, "scenario": scenario},
                    calculations=res.calculations, model=res.model, latency_ms=res.latency_ms)
    db.add(m)
    db.commit()
    audit(db, request, user, "dashboard.ask", "chat_session", str(s.id), status=res.status, latency_ms=res.latency_ms, chart=body.chart_id)
    db.commit()
    return msg_out(m) | {"session_id": str(s.id), "scenario": scenario}

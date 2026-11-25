from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.database.session import get_db
from app.financial_analytics import service
from app.financial_analytics.comparison import compare_documents
from app.financial_analytics.metric_extractor import METRIC_NAMES, period_sort_key
from app.models import Collection, Document, DocumentChunk, FinancialMetric, ProcessingJob, User
from app.schemas.analytics import CollectionIn, DocSelection, ReviewIn

router = APIRouter(tags=["analytics"])


# ---------------------------------------------------------------- overview
@router.get("/analytics/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(require("read"))):
    base = db.query(Document).filter(Document.owner_id == user.id)
    by_status = dict(db.query(Document.status, func.count()).filter(Document.owner_id == user.id).group_by(Document.status).all())
    by_format = dict(db.query(Document.file_format, func.count()).filter(Document.owner_id == user.id).group_by(Document.file_format).all())
    doc_ids = [d.id for d in base.with_entities(Document.id).all()]
    metric_counts = dict(db.query(FinancialMetric.validation_status, func.count()).filter(FinancialMetric.document_id.in_(doc_ids))
                         .group_by(FinancialMetric.validation_status).all()) if doc_ids else {}
    chunks = db.query(func.count(DocumentChunk.id)).filter(DocumentChunk.document_id.in_(doc_ids), DocumentChunk.embedded.is_(True)).scalar() if doc_ids else 0
    failed_jobs = db.query(func.count(ProcessingJob.id)).join(Document).filter(Document.owner_id == user.id, ProcessingJob.status == "failed").scalar()
    orgs = sorted({o for (o,) in base.with_entities(Document.organisation_name).all() if o})
    years = sorted({y for (y,) in base.with_entities(Document.fiscal_year).all() if y})
    recent = base.order_by(Document.uploaded_at.desc()).limit(8).all()
    return {
        "total_documents": sum(by_status.values()), "documents_by_status": by_status, "documents_by_format": by_format,
        "processed_documents": by_status.get("processed", 0), "failed_documents": by_status.get("failed", 0),
        "failed_jobs": failed_jobs, "indexed_chunks": chunks, "extracted_metrics": sum(metric_counts.values()),
        "metrics_by_validation_status": metric_counts, "organisations_detected": orgs, "fiscal_years_detected": years,
        "recent_documents": [{"id": str(d.id), "filename": d.original_filename, "file_format": d.file_format, "status": d.status,
                              "uploaded_at": d.uploaded_at.isoformat(), "organisation": d.organisation_name} for d in recent],
    }


# ---------------------------------------------------------------- metrics
@router.get("/metrics")
def list_metrics(db: Session = Depends(get_db), user: User = Depends(require("read")), document_id: uuid.UUID | None = None,
                 metric_key: str | None = None, status: str | None = None, include_line_items: bool = False):
    q = db.query(FinancialMetric, Document).join(Document, Document.id == FinancialMetric.document_id).filter(Document.owner_id == user.id)
    if document_id:
        q = q.filter(Document.id == document_id)
    if metric_key:
        q = q.filter(FinancialMetric.metric_key == metric_key)
    if status:
        q = q.filter(FinancialMetric.validation_status == status)
    if not include_line_items:
        q = q.filter(FinancialMetric.metric_key != "line_item")
    rows = q.limit(5000).all()
    return {"total": len(rows), "items": [service.metric_dict(m, d) for m, d in rows]}


@router.get("/metrics/available")
def available_metrics(db: Session = Depends(get_db), user: User = Depends(require("read"))):
    rows = (db.query(FinancialMetric.metric_key, func.count(), func.count(func.distinct(FinancialMetric.document_id)))
            .join(Document).filter(Document.owner_id == user.id, FinancialMetric.metric_key != "line_item", FinancialMetric.is_duplicate.is_(False))
            .group_by(FinancialMetric.metric_key).all())
    return [{"metric_key": k, "metric_name": METRIC_NAMES.get(k, k), "values": n, "documents": nd} for k, n, nd in sorted(rows)]


def _review(metric_id: uuid.UUID, new_status: str, body: ReviewIn, request: Request, db: Session, user: User):
    m = db.get(FinancialMetric, metric_id)
    if not m:
        raise HTTPException(404, "Metric not found")
    d = db.get(Document, m.document_id)
    if d.owner_id != user.id:  # owner only, also for administrators
        raise HTTPException(404, "Metric not found")
    prev = m.validation_status
    m.validation_status = new_status
    m.verified_by, m.verified_at = user.id, dt.datetime.now(dt.timezone.utc)
    m.validation_notes = list(m.validation_notes or []) + [{"check": "human_review", "result": new_status, "detail": f"{user.email}: {body.note or ''}".strip(), "previous": prev}]
    db.commit()
    audit(db, request, user, f"metric.{new_status}", "financial_metric", str(m.id), previous=prev, note=body.note)
    return service.metric_dict(m, d)


@router.post("/metrics/{metric_id}/verify")
def verify_metric(metric_id: uuid.UUID, body: ReviewIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("verify"))):
    return _review(metric_id, "verified", body, request, db, user)


@router.post("/metrics/{metric_id}/reject")
def reject_metric(metric_id: uuid.UUID, body: ReviewIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("verify"))):
    return _review(metric_id, "rejected", body, request, db, user)


# ---------------------------------------------------------------- analytics
def _resolve(db: Session, user: User, sel: DocSelection) -> list[uuid.UUID]:
    ids = list(sel.document_ids)
    if sel.collection_id:
        c = db.get(Collection, sel.collection_id)
        if not c or c.owner_id != user.id:
            raise HTTPException(404, "Collection not found")
        ids += [d.id for d in c.documents]
    if not ids:
        ids = [d.id for d in db.query(Document.id).filter(Document.owner_id == user.id, Document.status == "processed").all()]
    owned = {d.id for d in db.query(Document.id).filter(Document.owner_id == user.id, Document.id.in_(ids)).all()}
    return [i for i in dict.fromkeys(ids) if i in owned]


@router.post("/analytics/series")
def series(sel: DocSelection, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    """Per-metric series built from real extracted values, grouped by document/basis/unit."""
    ids = _resolve(db, user, sel)
    ms = service.load_metrics(db, user.id, ids, include_line_items=sel.include_line_items)
    if sel.metric_keys:
        ms = [m for m in ms if m.metric_key in sel.metric_keys]
    docs = {d.id: d for d in db.query(Document).filter(Document.id.in_(ids)).all()}
    out: dict[str, dict] = defaultdict(lambda: {"points": []})
    for m in ms:
        if m.validation_status == "rejected":
            continue
        key = f"{m.metric_key}|{m.document_id}|{m.basis}|{m.unit}" if m.metric_key != "line_item" else f"line_item:{m.metric_name}|{m.document_id}|{m.basis}|{m.unit}"
        s = out[key]
        s.update({"metric_key": m.metric_key, "metric_name": m.metric_name, "document_id": str(m.document_id),
                  "filename": docs[m.document_id].original_filename, "organisation": docs[m.document_id].organisation_name,
                  "basis": m.basis, "unit": m.unit, "currency": m.currency})
        s["points"].append({"period_label": m.period_label, "period_sort": period_sort_key(m.period_label, m.period_end),
                            "value": str(m.value), "raw_value": m.raw_value, "validation_status": m.validation_status, "metric_id": str(m.id),
                            "location": m.source.location})
    for s in out.values():
        s["points"].sort(key=lambda p: (p["period_sort"] is None, p["period_sort"] or 0))
    return {"series": list(out.values())}


@router.post("/analytics/ratios")
def ratios(sel: DocSelection, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    ids = _resolve(db, user, sel)
    res = service.compute_ratios(db, user.id, ids, persist=True)
    return {"document_ids": [str(i) for i in ids], "results": res, "status_counts": dict(Counter(r["status"] for r in res))}


@router.post("/analytics/compare")
def compare(sel: DocSelection, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    ids = _resolve(db, user, sel)
    if len(ids) < 1:
        raise HTTPException(422, "Select at least one processed document.")
    return compare_documents(db, user.id, ids, sel.metric_keys, sel.include_line_items)


# ---------------------------------------------------------------- collections
def _coll_out(c: Collection) -> dict:
    return {"id": str(c.id), "name": c.name, "description": c.description, "created_at": c.created_at.isoformat(),
            "documents": [{"id": str(d.id), "filename": d.original_filename, "status": d.status} for d in c.documents]}


@router.get("/collections")
def list_collections(db: Session = Depends(get_db), user: User = Depends(require("read"))):
    return [_coll_out(c) for c in db.query(Collection).filter_by(owner_id=user.id).order_by(Collection.name).all()]


@router.post("/collections", status_code=201)
def create_collection(body: CollectionIn, db: Session = Depends(get_db), user: User = Depends(require("upload"))):
    if db.query(Collection).filter_by(owner_id=user.id, name=body.name).first():
        raise HTTPException(409, "A collection with this name exists.")
    c = Collection(owner_id=user.id, name=body.name, description=body.description)
    c.documents = db.query(Document).filter(Document.owner_id == user.id, Document.id.in_(body.document_ids)).all() if body.document_ids else []
    db.add(c)
    db.commit()
    return _coll_out(c)


@router.put("/collections/{cid}")
def update_collection(cid: uuid.UUID, body: CollectionIn, db: Session = Depends(get_db), user: User = Depends(require("upload"))):
    c = db.get(Collection, cid)
    if not c or c.owner_id != user.id:
        raise HTTPException(404, "Collection not found")
    c.name, c.description = body.name, body.description
    c.documents = db.query(Document).filter(Document.owner_id == user.id, Document.id.in_(body.document_ids)).all() if body.document_ids else []
    db.commit()
    return _coll_out(c)


@router.delete("/collections/{cid}")
def delete_collection(cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    c = db.get(Collection, cid)
    if not c or c.owner_id != user.id:
        raise HTTPException(404, "Collection not found")
    db.delete(c)
    db.commit()
    return {"deleted": str(cid)}

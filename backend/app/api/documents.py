from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.core.config import get_settings
from app.database.session import get_db
from app.document_processing.elements import describe_location
from app.document_processing.ingestion import apply_metadata, propagate_document_units
from app.document_processing.validation import FileValidationError, sanitize_filename, validate_upload
from app.financial_analytics.service import metric_dict
from app.models import Document, DocumentChunk, DocumentTable, FinancialMetric, FinancialStatement, ProcessingJob, User
from app.rag import vector_store
from app.schemas.documents import MetadataPatch

router = APIRouter(prefix="/documents", tags=["documents"])
EDITABLE_META = ("organisation", "reporting_period", "fiscal_year", "category", "currency", "unit")


def doc_out(d: Document, detail: bool = False) -> dict[str, Any]:
    out = {
        "id": str(d.id), "filename": d.original_filename, "file_format": d.file_format, "file_size": d.file_size,
        "status": d.status, "error_message": d.error_message, "uploaded_at": d.uploaded_at.isoformat(),
        "processed_at": d.processed_at.isoformat() if d.processed_at else None,
        "organisation": d.organisation_name, "reporting_period": d.reporting_period, "fiscal_year": d.fiscal_year,
        "category": d.category, "currency": d.currency, "unit": d.unit,
        "page_count": d.page_count, "sheet_names": d.sheet_names, "row_count": d.row_count,
        "chunk_count": d.chunk_count, "metric_count": d.metric_count, "table_count": d.table_count,
        "warnings": d.warnings or [], "sha256": d.sha256,
    }
    if detail:
        meta = dict(d.doc_metadata or {})
        out["metadata"] = {k: meta.get(k) for k in EDITABLE_META}
        out["validation_checks"] = meta.get("_validation_checks", [])
        out["ocr_pages"] = d.ocr_pages
        out["element_count"] = d.element_count
        out["structure"] = d.structure
        out["collections"] = [{"id": str(c.id), "name": c.name} for c in d.collections]
    return out


def get_owned(db: Session, user: User, doc_id: uuid.UUID) -> Document:
    d = db.get(Document, doc_id)
    # Strict tenant isolation: documents are visible to their owner only (administrators manage users,
    # model endpoints and the audit log, but do not read other users' financial documents).
    if not d or d.owner_id != user.id:
        raise HTTPException(404, "Document not found")
    return d


@router.post("", status_code=201)
async def upload(request: Request, files: list[UploadFile] = File(...), db: Session = Depends(get_db), user: User = Depends(require("upload"))):
    s = get_settings()
    if len(files) > s.max_files_per_request:
        raise HTTPException(413, f"At most {s.max_files_per_request} files per upload.")
    results = []
    for f in files:
        name = sanitize_filename(f.filename or "upload")
        data = await f.read(s.max_upload_mb * 1024 * 1024 + 1)
        try:
            v = validate_upload(name, data)
        except FileValidationError as exc:
            results.append({"filename": name, "accepted": False, "error": str(exc)})
            audit(db, request, user, "document.upload_rejected", "document", None, filename=name, reason=str(exc))
            continue
        sha = hashlib.sha256(data).hexdigest()
        existing = db.query(Document).filter_by(owner_id=user.id, sha256=sha).first()
        if existing:
            results.append({"filename": name, "accepted": False, "duplicate_of": str(existing.id),
                            "error": f"This exact file was already uploaded as '{existing.original_filename}'."})
            continue
        stored = f"{uuid.uuid4().hex}.{v.file_format}"
        path = Path(s.upload_dir) / stored
        path.write_bytes(data)
        path.chmod(0o640)
        try:
            d = Document(owner_id=user.id, original_filename=name, stored_filename=stored, file_format=v.file_format,
                         mime_type=v.mime_type, file_size=len(data), sha256=sha, status="queued", warnings=v.warnings, doc_metadata={})
            db.add(d)
            db.flush()
            db.add(ProcessingJob(document_id=d.id, status="queued"))
            db.commit()
        except IntegrityError:  # the same file arrived concurrently: the unique (owner_id, sha256) index decided
            db.rollback()
            path.unlink(missing_ok=True)
            results.append({"filename": name, "accepted": False, "error": "This exact file was already uploaded."})
            continue
        except Exception:
            db.rollback()
            path.unlink(missing_ok=True)  # no orphan file without a database record
            raise
        audit(db, request, user, "document.upload", "document", str(d.id), filename=name, size=len(data), format=v.file_format)
        results.append({"filename": name, "accepted": True, "document": doc_out(d)})
    return {"results": results}


@router.get("")
def list_documents(db: Session = Depends(get_db), user: User = Depends(require("read")), status: str | None = None,
                   file_format: str | None = None, organisation: str | None = None, q: str | None = Query(None, max_length=200),
                   collection_id: uuid.UUID | None = None, limit: int = Query(200, le=1000), offset: int = 0):
    qry = db.query(Document).filter(Document.owner_id == user.id)
    if status:
        qry = qry.filter(Document.status == status)
    if file_format:
        qry = qry.filter(Document.file_format == file_format)
    if organisation:
        qry = qry.filter(Document.organisation_name == organisation)
    if q:
        qry = qry.filter(Document.original_filename.ilike(f"%{q}%"))
    if collection_id:
        qry = qry.filter(Document.collections.any(id=collection_id))
    total = qry.count()
    docs = qry.order_by(Document.uploaded_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [doc_out(d) for d in docs]}


@router.get("/{doc_id}")
def get_document(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    d = get_owned(db, user, doc_id)
    out = doc_out(d, detail=True)
    jobs = db.query(ProcessingJob).filter_by(document_id=d.id).order_by(ProcessingJob.created_at.desc()).all()
    out["jobs"] = [{"id": str(j.id), "status": j.status, "stage": j.stage, "attempts": j.attempts, "error": j.error, "log": j.log,
                    "created_at": j.created_at.isoformat(), "started_at": j.started_at.isoformat() if j.started_at else None,
                    "finished_at": j.finished_at.isoformat() if j.finished_at else None} for j in jobs]
    out["statements"] = [{"id": str(s.id), "statement_type": s.statement_type, "basis": s.basis, "title": s.title, "unit": s.unit,
                          "currency": s.currency, "periods": s.periods, "location_text": describe_location(s.location)}
                         for s in db.query(FinancialStatement).filter_by(document_id=d.id).all()]
    return out


@router.patch("/{doc_id}/metadata")
def correct_metadata(doc_id: uuid.UUID, body: MetadataPatch, request: Request, db: Session = Depends(get_db), user: User = Depends(require("upload"))):
    d = get_owned(db, user, doc_id)
    meta = dict(d.doc_metadata or {})
    changes = {}
    for k in EDITABLE_META:
        v = getattr(body, k)
        if k in body.clear:
            meta[k] = {"value": None, "status": "user_corrected", "method": f"cleared by {user.email}", "confidence": 1.0, "evidence": None}
            changes[k] = None
        elif v is not None and v.strip():
            val: Any = {"label": v.strip(), "end_date": None, "kind": "user"} if k == "reporting_period" else v.strip()
            prev = (meta.get(k) or {}).get("value")
            meta[k] = {"value": val, "status": "user_corrected", "method": f"corrected by {user.email}", "confidence": 1.0,
                       "evidence": None, "previous_value": prev}
            changes[k] = v.strip()
    apply_metadata(db, d, meta)
    if "currency" in changes or "unit" in changes:
        propagate_document_units(db, d, "currency" in changes, "unit" in changes, user.email)
    db.commit()
    audit(db, request, user, "document.metadata_corrected", "document", str(d.id), changes=changes)
    return doc_out(d, detail=True)


@router.post("/{doc_id}/reprocess")
def reprocess(doc_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require("upload"))):
    d = get_owned(db, user, doc_id)
    if d.status in ("queued", "processing"):
        raise HTTPException(409, "The document is already queued or processing.")
    d.status = "queued"
    db.add(ProcessingJob(document_id=d.id, status="queued"))
    db.commit()
    audit(db, request, user, "document.reprocess", "document", str(d.id))
    return doc_out(d)


@router.delete("/{doc_id}")
def delete_document(doc_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    d = get_owned(db, user, doc_id)
    if d.status == "processing":
        # the worker could still write vectors/rows for it; deleting now would leave orphans
        raise HTTPException(409, "The document is being processed; delete it when processing has finished.")
    vector_store.delete_document(str(d.id))
    path = Path(get_settings().upload_dir) / d.stored_filename
    name = d.original_filename
    db.delete(d)
    db.commit()
    path.unlink(missing_ok=True)
    audit(db, request, user, "document.delete", "document", str(doc_id), filename=name)
    return {"deleted": str(doc_id)}


@router.get("/{doc_id}/file")
def download(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    d = get_owned(db, user, doc_id)
    path = Path(get_settings().upload_dir) / d.stored_filename
    if not path.exists():
        raise HTTPException(410, "The original file is no longer in storage.")
    return FileResponse(path, media_type=d.mime_type, filename=d.original_filename,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.get("/{doc_id}/chunks")
def chunks(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read")), limit: int = Query(50, le=500), offset: int = 0):
    d = get_owned(db, user, doc_id)
    q = db.query(DocumentChunk).filter_by(document_id=d.id).order_by(DocumentChunk.chunk_index)
    return {"total": q.count(), "items": [{"id": str(c.id), "index": c.chunk_index, "text": c.text, "location": c.location,
                                           "location_text": describe_location(c.location), "element_types": c.element_types,
                                           "injection_flag": c.injection_flag, "embedded": c.embedded} for c in q.offset(offset).limit(limit)]}


@router.get("/{doc_id}/tables")
def tables(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read")), limit: int = Query(50, le=500), offset: int = 0):
    d = get_owned(db, user, doc_id)
    q = db.query(DocumentTable).filter_by(document_id=d.id).order_by(DocumentTable.table_index)
    return {"total": q.count(), "items": [{"id": str(t.id), "index": t.table_index, "title": t.title, "location_text": describe_location(t.location),
                                           "location": t.location, "header": t.header, "rows": t.rows[:200], "n_rows": t.n_rows, "n_cols": t.n_cols}
                                          for t in q.offset(offset).limit(limit)]}


@router.get("/{doc_id}/metrics")
def doc_metrics(doc_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read")),
                include_line_items: bool = True, status: str | None = None):
    d = get_owned(db, user, doc_id)
    q = db.query(FinancialMetric).filter_by(document_id=d.id)
    if not include_line_items:
        q = q.filter(FinancialMetric.metric_key != "line_item")
    if status:
        q = q.filter(FinancialMetric.validation_status == status)
    ms = q.all()
    ms.sort(key=lambda m: (m.metric_key == "line_item", m.source.location.get("page") or 0, m.source.location.get("row") or 0, m.metric_key))
    counts = dict(db.query(FinancialMetric.validation_status, func.count()).filter_by(document_id=d.id).group_by(FinancialMetric.validation_status).all())
    return {"total": len(ms), "status_counts": counts, "items": [metric_dict(m, d) for m in ms]}

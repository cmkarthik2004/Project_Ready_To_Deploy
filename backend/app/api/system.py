"""Health, system status, model configuration (admin), users and audit log."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.core.config import get_settings
from app.core.security import ROLES
from app.database.session import get_db
from app.models import AuditLog, Document, ModelConfiguration, ProcessingJob, User
from app.llm import client as llm
from app.rag import embeddings, vector_store
from app.schemas.system import ModelConfigIn, RoleIn

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)):
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"[:200]
    q = vector_store.status()
    checks["qdrant"] = "ok" if q.get("reachable") else f"error: {q.get('error')}"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        raise HTTPException(503, checks)
    return checks


def gpu_info() -> dict:
    info: dict = {"cuda_available": False, "detected_by": []}
    try:
        import torch

        info["torch_version"] = torch.__version__
        info["torch_cuda_build"] = torch.version.cuda
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["devices"] = [{"index": i, "name": torch.cuda.get_device_name(i),
                                "memory_gb": round(torch.cuda.get_device_properties(i).total_memory / 1e9, 1)} for i in range(torch.cuda.device_count())]
            info["detected_by"].append("torch.cuda")
    except Exception as exc:
        info["torch_error"] = str(exc)[:200]
    smi = shutil.which("nvidia-smi")
    info["nvidia_smi_present"] = bool(smi)
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
            info["nvidia_smi"] = out.stdout.strip() or out.stderr.strip()
            if out.returncode == 0 and out.stdout.strip():
                info["detected_by"].append("nvidia-smi")
        except Exception as exc:
            info["nvidia_smi"] = f"error: {exc}"
    return info


@router.get("/status")
def system_status(db: Session = Depends(get_db), user: User = Depends(require("read"))):
    s = get_settings()
    ep = llm.active_endpoint(db)
    q_counts = dict(db.query(ProcessingJob.status, func.count()).join(Document).filter(Document.owner_id == user.id).group_by(ProcessingJob.status).all())
    try:
        dbv = db.execute(text("SHOW server_version")).scalar()
        db_ok = True
    except Exception:
        dbv, db_ok = None, False
    emb = embeddings.status()
    return {
        "database": {"reachable": db_ok, "server_version": dbv},
        "vector_store": vector_store.status(),
        "embedding_model": {"name": s.embedding_model, **emb,
                            "note": "loaded on first use" if not emb.get("loaded") else None},
        "reranker": {"name": s.reranker_model, "loaded": emb.get("reranker_loaded")},
        "llm": llm.status(ep),
        "processing_jobs": q_counts,
        "ocr": {"enabled": s.ocr_enabled, "tesseract": shutil.which("tesseract") is not None, "language": s.ocr_language},
        "pdf_table_engine": s.pdf_table_engine,
        "gpu": gpu_info(),
        "platform": {"python": platform.python_version(), "machine": platform.machine(), "cpus": os.cpu_count()},
    }


def cfg_out(c: ModelConfiguration) -> dict:
    return {"id": str(c.id), "name": c.name, "kind": c.kind, "provider": c.provider, "base_url": c.base_url, "model_name": c.model_name,
            "api_key_env": c.api_key_env, "api_key_present": bool(c.api_key_env and os.environ.get(c.api_key_env)),
            "params": c.params, "is_active": c.is_active}


@router.get("/settings/models")
def list_models(db: Session = Depends(get_db), user: User = Depends(require("read"))):
    return {"configurations": [cfg_out(c) for c in db.query(ModelConfiguration).order_by(ModelConfiguration.name)],
            "environment_default": {k: v for k, v in llm.endpoint_from_settings().__dict__.items() if k != "api_key"}}


@router.post("/settings/models", status_code=201)
def add_model(body: ModelConfigIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    c = ModelConfiguration(name=body.name, kind="llm", provider=body.provider, base_url=str(body.base_url).rstrip("/"),
                           model_name=body.model_name, api_key_env=body.api_key_env, params=body.params)
    db.add(c)
    db.commit()
    audit(db, request, user, "model.add", "model_configuration", str(c.id), name=c.name)
    return cfg_out(c)


@router.post("/settings/models/{cid}/activate")
def activate_model(cid: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    c = db.get(ModelConfiguration, cid)
    if not c:
        raise HTTPException(404, "Model configuration not found")
    db.query(ModelConfiguration).filter_by(kind=c.kind).update({"is_active": False})
    c.is_active = True
    db.commit()
    audit(db, request, user, "model.activate", "model_configuration", str(c.id), name=c.name)
    return cfg_out(c)


@router.post("/settings/models/deactivate")
def deactivate_models(request: Request, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    db.query(ModelConfiguration).update({"is_active": False})
    db.commit()
    audit(db, request, user, "model.use_environment_default")
    return {"ok": True}


@router.delete("/settings/models/{cid}")
def delete_model(cid: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    c = db.get(ModelConfiguration, cid)
    if not c:
        raise HTTPException(404, "Model configuration not found")
    db.delete(c)
    db.commit()
    audit(db, request, user, "model.delete", "model_configuration", str(cid))
    return {"deleted": str(cid)}


@router.post("/settings/models/{cid}/test")
def test_model(cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    c = db.get(ModelConfiguration, cid)
    if not c:
        raise HTTPException(404, "Model configuration not found")
    ep = llm.LLMEndpoint(c.name, c.provider, c.base_url, c.model_name, os.environ.get(c.api_key_env) if c.api_key_env else None)
    st = llm.status(ep)
    try:
        r = llm.chat([{"role": "user", "content": "Reply with the single word: ready"}], ep, max_tokens=10)
        st["test_reply"] = r["content"][:50]
        st["test_latency_ms"] = r["latency_ms"]
    except llm.LLMError as exc:
        st["test_error"] = str(exc)[:300]
    return st


@router.get("/settings/limits")
def limits(user: User = Depends(require("read"))):
    s = get_settings()
    return {"max_upload_mb": s.max_upload_mb, "max_files_per_request": s.max_files_per_request, "allowed_formats": ["pdf", "docx", "xlsx", "xls", "csv"],
            "max_pdf_pages": s.max_pdf_pages, "ocr_enabled": s.ocr_enabled, "allow_registration": s.allow_registration,
            "retrieval_top_k": s.retrieval_top_k, "context_top_n": s.context_top_n}


@router.get("/admin/users")
def users(db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    return [{"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
             "created_at": u.created_at.isoformat()} for u in db.query(User).order_by(User.created_at)]


@router.patch("/admin/users/{uid}")
def set_role(uid: uuid.UUID, body: RoleIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("admin"))):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == user.id and (body.role != "admin" or not body.is_active):
        raise HTTPException(422, "You cannot remove your own admin role or deactivate yourself.")
    u.role, u.is_active = body.role, body.is_active
    db.commit()
    audit(db, request, user, "user.role_change", "user", str(uid), role=body.role, is_active=body.is_active)
    return {"id": str(u.id), "role": u.role, "is_active": u.is_active}


@router.get("/admin/audit-logs")
def audit_logs(db: Session = Depends(get_db), user: User = Depends(require("admin")), limit: int = 200):
    rows = db.query(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id).order_by(AuditLog.created_at.desc()).limit(min(limit, 1000)).all()
    return [{"id": str(a.id), "created_at": a.created_at.isoformat(), "user": email, "action": a.action, "resource_type": a.resource_type,
             "resource_id": a.resource_id, "ip": a.ip, "details": a.details} for a, email in rows]

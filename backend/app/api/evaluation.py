from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.database.session import get_db
from app.evaluation.runner import METHODS, start_run
from app.models import Document, EvaluationRun, User
from app.llm import client as llm
from app.core.config import get_settings

router = APIRouter(prefix="/evaluations", tags=["evaluation"])


def run_out(r: EvaluationRun, details: bool = False) -> dict:
    out = {"id": str(r.id), "kind": r.kind, "status": r.status, "method": r.method, "dataset": r.dataset, "metrics": r.metrics,
           "model_info": r.model_info, "error": r.error, "started_at": r.started_at.isoformat(),
           "finished_at": r.finished_at.isoformat() if r.finished_at else None}
    if details:
        out["details"] = r.details
    return out


@router.get("")
def list_runs(db: Session = Depends(get_db), user: User = Depends(require("read"))):
    # evaluation details contain answers and snippets from the creator's documents: creator only
    q = db.query(EvaluationRun).filter(EvaluationRun.created_by == user.id)
    return [run_out(r) for r in q.order_by(EvaluationRun.started_at.desc()).limit(100)]


@router.get("/methods")
def methods():
    return METHODS


@router.get("/{rid}")
def get_run(rid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    r = db.get(EvaluationRun, rid)
    if not r or r.created_by != user.id:
        raise HTTPException(404, "Evaluation run not found")
    return run_out(r, True)


@router.post("", status_code=202)
async def create_run(request: Request, kind: str = Form(...), document_ids: str = Form(""), gold_file: UploadFile | None = File(None),
                     db: Session = Depends(get_db), user: User = Depends(require("evaluate"))):
    if kind not in METHODS:
        raise HTTPException(422, f"kind must be one of {list(METHODS)}")
    ids = [uuid.UUID(x) for x in document_ids.split(",") if x.strip()]
    if ids:
        owned = {d.id for d in db.query(Document.id).filter(Document.owner_id == user.id, Document.id.in_(ids)).all()}
        ids = [i for i in ids if i in owned]
    else:
        ids = [d.id for d in db.query(Document.id).filter(Document.owner_id == user.id, Document.status == "processed").all()]
    gold = None
    name = None
    if kind != "extraction":
        if not gold_file:
            raise HTTPException(422, "This evaluation needs a gold JSONL file describing expected results.")
        raw = (await gold_file.read(5_000_000)).decode("utf-8", errors="strict")
        try:
            gold = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise HTTPException(422, f"Gold file is not valid JSONL: {exc}")
        if not gold or len(gold) > 500:
            raise HTTPException(422, "Gold file must contain 1-500 items.")
        name = gold_file.filename
    elif not ids:
        raise HTTPException(422, "No processed documents to evaluate.")
    ep = llm.active_endpoint(db)
    s = get_settings()
    rid = start_run(user.id, kind, ids, gold, name, {"llm": ep.model, "llm_provider": ep.provider, "embedding": s.embedding_model, "reranker": s.reranker_model})
    audit(db, request, user, "evaluation.start", "evaluation_run", str(rid), kind=kind)
    return {"id": str(rid), "status": "running"}

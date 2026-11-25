"""Report endpoints. Report content is built in app.financial_analytics.reporting."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import audit, require
from app.database.session import get_db
from app.financial_analytics.reporting import ReportError, build_report, to_markdown
from app.models import User
from app.schemas.reports import ReportIn

router = APIRouter(prefix="/reports", tags=["reports"])


def _build(db: Session, user: User, body: ReportIn) -> dict:
    try:
        return build_report(db, user, body.document_ids, body.include_ai_summary)
    except ReportError as exc:
        raise HTTPException(exc.status_code, str(exc))


@router.post("")
def create_report(body: ReportIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    rep = _build(db, user, body)
    audit(db, request, user, "report.generate", None, None, documents=[str(i) for i in body.document_ids])
    return rep


@router.post("/markdown", response_class=PlainTextResponse)
def report_markdown(body: ReportIn, db: Session = Depends(get_db), user: User = Depends(require("read"))):
    return PlainTextResponse(to_markdown(_build(db, user, body)), media_type="text/markdown",
                             headers={"Content-Disposition": 'attachment; filename="finrag-report.md"'})

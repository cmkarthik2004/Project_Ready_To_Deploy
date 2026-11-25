"""Background worker: claims queued processing jobs from PostgreSQL.

Uses `SELECT ... FOR UPDATE SKIP LOCKED` so several workers can run safely.
Run with:  python -m app.worker
Jobs left in `running` state by a crashed worker are re-queued on startup.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import signal
import threading
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.database.session import SessionLocal
from app.document_processing.ingestion import process_document
from app.models import Document, ProcessingJob

log = logging.getLogger("finrag.worker")
_stop = threading.Event()


STALE_AFTER = dt.timedelta(minutes=int(os.environ.get("WORKER_STALE_MINUTES", "60")))


def requeue_stale() -> int:
    """Re-queue jobs left `running` by a crashed worker. Only jobs started longer ago than STALE_AFTER are
    touched, so starting a second worker never steals a job another worker is still processing."""
    cutoff = dt.datetime.now(dt.timezone.utc) - STALE_AFTER
    with SessionLocal() as db:
        stale = db.query(ProcessingJob).filter(ProcessingJob.status == "running",
                                               (ProcessingJob.started_at.is_(None)) | (ProcessingJob.started_at < cutoff)).all()
        for j in stale:
            j.status = "queued"
            doc = db.get(Document, j.document_id)
            if doc is not None and doc.status == "processing":
                doc.status = "queued"
        db.commit()
        return len(stale)


def claim_and_run_one() -> bool:
    with SessionLocal() as db:
        job = db.execute(
            select(ProcessingJob).where(ProcessingJob.status == "queued").order_by(ProcessingJob.created_at)
            .with_for_update(skip_locked=True).limit(1)
        ).scalar_one_or_none()
        if job is None:
            return False
        job.status = "running"
        db.commit()
        doc = db.get(Document, job.document_id)
        if doc is None:
            job.status, job.error = "failed", "document no longer exists"
            db.commit()
            return True
        log.info("processing document %s (%s)", doc.id, doc.file_format)
        t = time.time()
        process_document(db, doc, job)
        log.info("document %s -> %s in %.1fs", doc.id, db.get(Document, doc.id).status, time.time() - t)
        return True


def run_forever() -> None:
    s = get_settings()
    n = requeue_stale()
    if n:
        log.info("re-queued %d stale job(s)", n)
    while not _stop.is_set():
        try:
            if not claim_and_run_one():
                _stop.wait(s.worker_poll_seconds)
        except Exception:
            log.exception("worker loop error")
            _stop.wait(5)


def start_thread() -> threading.Thread:
    th = threading.Thread(target=run_forever, name="finrag-worker", daemon=True)
    th.start()
    return th


if __name__ == "__main__":
    setup_logging()
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    log.info("FinRAG worker started")
    run_forever()

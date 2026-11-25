"""End-to-end processing of one uploaded document.

Stages (each is timed and written to processing_jobs.log):
  parse -> detect_metadata -> extract_metrics -> validate -> persist -> chunk -> embed -> index
A document is marked `processed` only after every stage succeeded and the
vectors were written to Qdrant; otherwise it is `failed` with the real error.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
import traceback
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.document_processing.chunking import chunk_elements
from app.document_processing.elements import ParsedDocument
from app.document_processing.metadata import detect_all
from app.financial_analytics.metric_extractor import extract_metrics, fiscal_year_of, inherit_basis
from app.financial_analytics.validation import validate_metrics
from app.models import (
    Document,
    DocumentChunk,
    DocumentTable,
    FinancialMetric,
    FinancialStatement,
    Organisation,
    ProcessingJob,
    SourceReference,
)
from app.rag import embeddings, vector_store

log = logging.getLogger("finrag.ingestion")


def parser_for(fmt: str):
    from app.document_processing.parsers.docx_parser import DocxParser
    from app.document_processing.parsers.pdf_parser import PdfParser
    from app.document_processing.parsers.csv_parser import CsvParser
    from app.document_processing.parsers.excel_parser import XlsParser, XlsxParser

    return {"pdf": PdfParser, "docx": DocxParser, "xlsx": XlsxParser, "xls": XlsParser, "csv": CsvParser}[fmt]()


def normalise_org(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("limited", "ltd"))


def effective(meta: dict, key: str):
    f = meta.get(key) or {}
    return f.get("value") if f.get("status") in ("detected", "user_corrected") else None


def apply_metadata(db: Session, doc: Document, meta: dict) -> None:
    """Copy effective metadata values into the denormalised document columns."""
    doc.doc_metadata = meta
    org = effective(meta, "organisation")
    if org:
        norm = normalise_org(org)
        o = db.query(Organisation).filter_by(owner_id=doc.owner_id, normalized_name=norm).first()
        if not o:
            src = "user" if meta["organisation"]["status"] == "user_corrected" else "detected"
            o = Organisation(owner_id=doc.owner_id, name=org, normalized_name=norm, source=src)
            db.add(o)
            db.flush()
        doc.organisation_id, doc.organisation_name = o.id, o.name
    else:
        doc.organisation_id, doc.organisation_name = None, None
    period = effective(meta, "reporting_period")
    doc.reporting_period = period.get("label") if isinstance(period, dict) else period
    doc.fiscal_year = effective(meta, "fiscal_year")
    doc.category = effective(meta, "category")
    doc.currency = effective(meta, "currency")
    doc.unit = effective(meta, "unit")


DOC_UNIT_NOTES = ("unit taken from the document-level unit statement", "unit not stated")


def propagate_document_units(db: Session, doc: Document, currency_changed: bool, unit_changed: bool, who: str) -> int:
    """Apply a user-corrected document currency/unit to the stored values that depend on it.

    * Currency always comes from the document level, so every value and statement takes the corrected currency.
    * Unit: only values whose unit came from the document-level statement (or had none) change; values whose
      unit was printed next to their own table keep it. Normalised values are recomputed.
    """
    from decimal import Decimal

    from app.document_processing.metadata import UNIT_MULTIPLIER

    changed = 0
    for m in db.query(FinancialMetric).filter_by(document_id=doc.id).all():
        if currency_changed:
            m.currency = doc.currency
        notes = list(m.validation_notes or [])
        doc_level = any(isinstance(n, dict) and any(t in str(n.get("detail", "")) for t in DOC_UNIT_NOTES) for n in notes)
        if unit_changed and doc_level and m.unit not in ("per_share", "percent"):
            m.unit = doc.unit
            mult = UNIT_MULTIPLIER.get(doc.unit or "")
            m.unit_multiplier = Decimal(mult) if mult else None
            m.normalized_value = (m.value * m.unit_multiplier) if m.unit_multiplier else None
            notes.append({"check": "user_correction", "result": "note", "detail": f"unit set to {doc.unit!r} from the document unit corrected by {who}"})
            m.validation_notes = notes
            changed += 1
    for st in db.query(FinancialStatement).filter_by(document_id=doc.id).all():
        if currency_changed:
            st.currency = doc.currency
    return changed


def clear_derived(db: Session, doc: Document, vectors: bool = True) -> None:
    for model in (FinancialMetric, FinancialStatement, SourceReference, DocumentChunk, DocumentTable):
        db.execute(delete(model).where(model.document_id == doc.id))
    if vectors:
        vector_store.delete_document(str(doc.id))


def process_document(db: Session, doc: Document, job: ProcessingJob) -> None:
    s = get_settings()
    stages: list[dict] = []

    def stage(name: str, info: dict | None = None, t0: float | None = None) -> None:
        stages.append({"stage": name, "seconds": round(time.time() - (t0 or time.time()), 2), **(info or {})})
        job.stage, job.log = name, list(stages)
        db.commit()

    path = str(Path(s.upload_dir) / doc.stored_filename)
    doc.status, job.status, job.started_at = "processing", "running", dt.datetime.now(dt.timezone.utc)
    job.attempts += 1
    db.commit()
    try:
        clear_derived(db, doc)
        db.commit()

        t = time.time()
        parsed: ParsedDocument = parser_for(doc.file_format).parse(path)
        doc.page_count, doc.sheet_names, doc.row_count = parsed.page_count, parsed.sheet_names, parsed.row_count
        doc.element_count, doc.table_count = len(parsed.elements), len(parsed.tables)
        doc.ocr_pages = parsed.ocr_pages or None
        doc.structure = {k: v for k, v in parsed.file_metadata.items() if k in ("sheets", "sheet_links", "profile", "encoding",
                                                                               "delimiter", "multi_page_tables")} or None
        doc.warnings = list(dict.fromkeys((doc.warnings or []) + parsed.warnings))[:200]
        if not parsed.elements:
            raise ValueError("No readable content was found in the document" + (" (it may be a scanned image and OCR is unavailable)" if doc.file_format == "pdf" else "") + ".")
        stage("parse", {"elements": len(parsed.elements), "tables": len(parsed.tables), "ocr_pages": len(parsed.ocr_pages)}, t)

        t = time.time()
        meta = detect_all(parsed, doc.original_filename)
        # keep user corrections made before a re-process
        for k, v in (doc.doc_metadata or {}).items():
            if isinstance(v, dict) and v.get("status") == "user_corrected":
                meta[k] = v
        apply_metadata(db, doc, meta)
        stage("detect_metadata", {k: (v.get("value") if not isinstance(v.get("value"), dict) else v["value"].get("label")) for k, v in meta.items()}, t)

        t = time.time()
        metrics = extract_metrics(parsed.elements, doc.file_format, doc.currency, doc.unit)
        inherit_basis(metrics, parsed.full_text(400_000))
        statuses, notes, dups, checks = validate_metrics(metrics)
        stage("extract_and_validate", {"metrics": len(metrics), "checks": len(checks),
                                       "checks_passed": sum(1 for c in checks if c["result"] == "passed")}, t)

        t = time.time()
        for tb in parsed.tables:
            db.add(DocumentTable(document_id=doc.id, table_index=tb.table_id, title=tb.title, location=tb.location.to_dict(),
                                 header=tb.header, rows=tb.rows[:2000], n_rows=len(tb.rows), n_cols=len(tb.header)))
        statements: dict[tuple, FinancialStatement] = {}
        by_stmt: dict[tuple, list[int]] = defaultdict(list)
        for i, m in enumerate(metrics):
            if m.statement_type and m.metric_key != "line_item":
                by_stmt[(m.statement_type, m.basis)].append(i)
        for (st, basis), idxs in by_stmt.items():
            if len(idxs) < 3:
                continue
            first = metrics[idxs[0]]
            fs = FinancialStatement(document_id=doc.id, statement_type=st, basis=basis,
                                    title=st.replace("_", " ").title() + (f" ({basis})" if basis else ""),
                                    location=first.location.to_dict(), currency=first.currency, unit=first.unit,
                                    periods=list(dict.fromkeys(metrics[i].period_label for i in idxs if metrics[i].period_label)))
            db.add(fs)
            db.flush()
            statements[(st, basis)] = fs
        for i, m in enumerate(metrics):
            ref = SourceReference(document_id=doc.id, location=m.location.to_dict(), snippet=m.snippet)
            db.add(ref)
            db.flush()
            fs = statements.get((m.statement_type, m.basis))
            db.add(FinancialMetric(
                document_id=doc.id, statement_id=fs.id if fs else None, source_reference_id=ref.id,
                metric_key=m.metric_key, metric_name=m.metric_name, raw_label=m.raw_label[:1000], raw_value=m.raw_value,
                value=m.value, unit=m.unit, unit_multiplier=m.unit_multiplier,
                normalized_value=(m.value * m.unit_multiplier) if m.unit_multiplier else None,
                currency=m.currency, period_label=m.period_label, period_end=m.period_end, statement_type=m.statement_type,
                basis=m.basis, extraction_method=m.method, confidence=m.confidence, validation_status=statuses[i],
                validation_notes=[{"check": "extraction", "result": "note", "detail": n} for n in m.notes] + notes[i],
                is_duplicate=dups[i], is_total=m.is_total, value_origin=m.value_origin,
                fiscal_year=fiscal_year_of(m.period_label, m.period_end),
            ))
        doc.metric_count = len(metrics)
        meta_checks = dict(doc.doc_metadata)
        meta_checks["_validation_checks"] = checks[:500]
        doc.doc_metadata = meta_checks
        db.commit()
        stage("persist", {"tables": len(parsed.tables), "statements": len(statements)}, t)

        t = time.time()
        chunks = chunk_elements(parsed.elements)
        rows = []
        for c in chunks:
            ch = DocumentChunk(document_id=doc.id, chunk_index=c.index, text=c.text, element_types=c.element_types,
                               location=c.location, char_count=len(c.text), injection_flag=c.injection_flag)
            db.add(ch)
            rows.append(ch)
        db.flush()
        flagged = sum(1 for c in chunks if c.injection_flag)
        if flagged:
            doc.warnings = list(doc.warnings or []) + [f"{flagged} chunk(s) contain text resembling instructions to an AI; they are treated strictly as data."]
        stage("chunk", {"chunks": len(chunks), "injection_flagged": flagged}, t)

        t = time.time()
        vectors = embeddings.embed_documents([c.text for c in chunks])
        stage("embed", {"vectors": len(vectors), "dim": len(vectors[0]) if vectors else 0}, t)

        t = time.time()
        vector_store.ensure_collection(len(vectors[0]))
        vector_store.upsert([
            (ch.id, vec, {"owner_id": str(doc.owner_id), "document_id": str(doc.id), "chunk_index": ch.chunk_index,
                          "file_format": doc.file_format, "filename": doc.original_filename})
            for ch, vec in zip(rows, vectors)
        ])
        for ch in rows:
            ch.embedded = True
        doc.chunk_count = len(rows)
        stage("index", {"points": len(rows)}, t)
        # the document may have been deleted while we were processing it: never leave orphan vectors
        if db.query(Document.id).filter_by(id=doc.id).first() is None:
            vector_store.delete_document(str(doc.id))
            raise RuntimeError("document was deleted during processing; its vectors were removed")

        doc.status, job.status = "processed", "succeeded"
        doc.error_message, job.error = None, None
        doc.processed_at = job.finished_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.exception("processing failed for %s", doc.id)
        doc_id, job_id = doc.id, job.id
        doc = db.get(Document, doc_id)
        job = db.get(ProcessingJob, job_id)
        if doc is None:  # deleted meanwhile: nothing to record
            vector_store.delete_document(str(doc_id))
            return
        # A failed document keeps no partial derived data (chunks, metrics, vectors): all-or-nothing.
        # Database rows are cleared and committed independently of the vector store, so an unreachable
        # Qdrant can never leave stale metrics/chunks attached to a failed document. Any vectors that could
        # not be removed are unreachable (retrieval serves only processed documents and joins every hit to a
        # chunk row) and are removed by the next reprocess or delete.
        clear_derived(db, doc, vectors=False)
        doc.chunk_count = doc.metric_count = doc.table_count = 0
        db.commit()
        msg = f"{type(exc).__name__}: {exc}"
        try:
            vector_store.delete_document(str(doc_id))
        except Exception as vexc:
            log.warning("could not remove vectors of failed document %s: %s", doc_id, vexc)
            msg += " (vectors could not be removed now; they are never served and are removed on reprocess/delete)"
        doc.status, doc.error_message = "failed", msg[:2000]
        job.status, job.error = "failed", (msg + "\n" + traceback.format_exc(limit=5))[:8000]
        job.log = stages + [{"stage": "error", "error": msg[:500]}]
        job.finished_at = dt.datetime.now(dt.timezone.utc)
        db.commit()

"""Evaluation runs. Results are stored in `evaluation_runs` only after the run
actually executed; nothing is shown before that.

Kinds
-----
extraction  (no gold data needed)
    For the selected documents: share of extracted canonical values that took
    part in an accounting-identity check, pass rate of those checks, and
    validation-status distribution. Measures internal consistency of
    extraction, NOT agreement with a human-labelled ground truth.

extraction_gold  (user-supplied gold JSONL)
    Each line: {"document_id": "...", "metric_key": "total_assets",
                "period_contains": "2025", "expected_value": "1950121", "basis": "consolidated"?}
    Accuracy = extracted value equals expected value (Decimal compare).

rag  (user-supplied gold JSONL)
    Each line: {"question": "...", "document_ids": ["..."],
                "expected_numbers": ["9,80,136"],  "expected_location": {"page": 99} | {"sheet": "P&L"} | {"row": 12}}
    Metrics: retrieval hit rate (expected location among retrieved evidence),
    answer correctness (all expected numbers present in answer), citation
    correctness (a cited source contains the expected number), faithfulness
    (share of answers with no unsupported numbers), insufficient-evidence rate,
    latency (mean / p50 / max).
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import threading
import uuid
from collections import Counter
from decimal import Decimal

from app.database.session import SessionLocal
from app.models import Document, EvaluationRun, FinancialMetric
from app.rag.rag_pipeline import answer_question


def _digits(s: str) -> str:
    return "".join(ch for ch in str(s) if ch.isdigit())


def run_extraction(db, owner_id: uuid.UUID, doc_ids: list[uuid.UUID]) -> tuple[dict, list]:
    details = []
    totals = Counter()
    for d in db.query(Document).filter(Document.owner_id == owner_id, Document.id.in_(doc_ids)).all():
        checks = (d.doc_metadata or {}).get("_validation_checks", [])
        ms = db.query(FinancialMetric).filter(FinancialMetric.document_id == d.id, FinancialMetric.metric_key != "line_item",
                                              FinancialMetric.is_duplicate.is_(False)).all()
        st = Counter(m.validation_status for m in ms)
        checked = sum(1 for m in ms if any(n.get("check") not in ("extraction", "duplicate", "conflict", "sign", "human_review") for n in (m.validation_notes or [])))
        res = Counter(c["result"] for c in checks)
        for c in checks:
            totals[f"check::{c['check']}::run"] += 1
            totals[f"check::{c['check']}::passed"] += c["result"] == "passed"
        details.append({"document": d.original_filename, "canonical_values": len(ms), "values_in_checks": checked,
                        "checks": dict(res), "status_counts": dict(st)})
        totals["values"] += len(ms)
        totals["checked"] += checked
        totals["checks"] += len(checks)
        totals["passed"] += res.get("passed", 0)
        for k, v in st.items():
            totals[f"status_{k}"] += v
    metrics = {
        "documents": len(details), "canonical_values": totals["values"],
        "check_coverage": round(totals["checked"] / totals["values"], 4) if totals["values"] else None,
        "identity_checks_run": totals["checks"],
        "identity_check_pass_rate": round(totals["passed"] / totals["checks"], 4) if totals["checks"] else None,
        "status_counts": {k[7:]: v for k, v in totals.items() if k.startswith("status_")},
        "by_check": {name: {"run": totals[f"check::{name}::run"], "passed": totals[f"check::{name}::passed"],
                            "pass_rate": round(totals[f"check::{name}::passed"] / totals[f"check::{name}::run"], 4)}
                     for name in sorted({k.split("::")[1] for k in totals if k.startswith("check::")})},
    }
    ident = [v for k, v in metrics["by_check"].items() if k != "column_total"]
    metrics["accounting_identity_pass_rate"] = (round(sum(v["passed"] for v in ident) / sum(v["run"] for v in ident), 4)
                                                if ident and sum(v["run"] for v in ident) else None)
    return metrics, details


def run_extraction_gold(db, owner_id, gold: list[dict]) -> tuple[dict, list]:
    details, correct, found = [], 0, 0
    for g in gold:
        if "document_filename" in g and "document_id" not in g:
            d = db.query(Document).filter(Document.owner_id == owner_id, Document.original_filename == g["document_filename"]).first()
            g = {**g, "document_id": str(d.id) if d else str(uuid.uuid4())}
        q = db.query(FinancialMetric).join(Document).filter(Document.owner_id == owner_id, FinancialMetric.document_id == uuid.UUID(g["document_id"]),
                                                            FinancialMetric.metric_key == g["metric_key"], FinancialMetric.is_duplicate.is_(False))
        cands = [m for m in q.all() if g.get("period_contains", "") in (m.period_label or "") and (not g.get("basis") or m.basis == g["basis"])]
        exp = Decimal(str(g["expected_value"]).replace(",", ""))
        hit = next((m for m in cands if m.value == exp), None)
        found += bool(cands)
        correct += bool(hit)
        details.append({**g, "extracted": [str(m.value) for m in cands], "correct": bool(hit)})
    n = len(gold)
    return {"items": n, "found_rate": round(found / n, 4) if n else None, "accuracy": round(correct / n, 4) if n else None}, details


def run_rag(db, owner_id, gold: list[dict]) -> tuple[dict, list]:
    details, lat = [], []
    agg = Counter()
    for g in gold:
        doc_ids = [uuid.UUID(x) for x in g.get("document_ids", [])]
        for fn in g.get("document_filenames", []):  # portable gold files: resolve names within the user's documents
            d = db.query(Document).filter(Document.owner_id == owner_id, Document.original_filename == fn).first()
            if d:
                doc_ids.append(d.id)
        r = answer_question(db, owner_id, g["question"], doc_ids or None)
        lat.append(r.latency_ms)
        exp_nums = [_digits(x) for x in g.get("expected_numbers", [])]
        ans_d = _digits(r.answer)
        ans_ok = bool(exp_nums) and all(e in ans_d for e in exp_nums)
        cite_ok = bool(exp_nums) and any(all(e in _digits(c.get("snippet", "")) for e in exp_nums) for c in r.citations)
        loc = g.get("expected_location") or {}
        def loc_match(l: dict) -> bool:
            if not loc or not l:
                return False
            if "page" in loc:
                return (l.get("page") or 0) <= loc["page"] <= (l.get("page_end") or l.get("page") or 0)
            if "sheet" in loc:
                return l.get("sheet") == loc["sheet"]
            if "row" in loc:
                return (l.get("row") or 0) <= loc["row"] <= (l.get("row_end") or l.get("row") or 0)
            return False
        hit = any(loc_match(e.get("location") or {}) for e in r.evidence)
        faithful = r.status in ("answered", "insufficient_evidence") and not r.verification.get("unsupported_numbers")
        agg["n"] += 1
        agg["answer_correct"] += ans_ok
        agg["citation_correct"] += cite_ok
        agg["retrieval_hit"] += hit
        agg["has_location"] += bool(loc)
        agg["faithful"] += faithful
        agg["insufficient"] += r.status == "insufficient_evidence"
        agg["error"] += r.status == "error"
        details.append({"question": g["question"], "status": r.status, "answer": r.answer[:2000], "answer_correct": ans_ok,
                        "citation_correct": cite_ok, "retrieval_hit": hit, "faithful": faithful,
                        "unsupported_numbers": r.verification.get("unsupported_numbers"), "latency_ms": r.latency_ms,
                        "citations": [f"{c.get('filename')}: {c.get('location_text')}" for c in r.citations]})
    n = agg["n"] or 1
    return {
        "questions": agg["n"], "answer_accuracy": round(agg["answer_correct"] / n, 4), "citation_correctness": round(agg["citation_correct"] / n, 4),
        "retrieval_hit_rate": round(agg["retrieval_hit"] / agg["has_location"], 4) if agg["has_location"] else None,
        "faithfulness": round(agg["faithful"] / n, 4), "insufficient_evidence_rate": round(agg["insufficient"] / n, 4),
        "errors": agg["error"], "latency_ms_mean": int(statistics.mean(lat)) if lat else None,
        "latency_ms_p50": int(statistics.median(lat)) if lat else None, "latency_ms_max": max(lat) if lat else None,
    }, details


METHODS = {
    "extraction": "Internal-consistency evaluation: accounting identities (e.g. total assets = equity + liabilities) evaluated on the values extracted from the selected documents. No external ground truth.",
    "extraction_gold": "Comparison of extracted values against a user-supplied gold file of expected values.",
    "rag": "End-to-end RAG evaluation against a user-supplied gold file of questions with expected numbers and locations.",
}


def start_run(owner_id: uuid.UUID, kind: str, doc_ids: list[uuid.UUID], gold: list[dict] | None, dataset_name: str | None, model_info: dict) -> uuid.UUID:
    with SessionLocal() as db:
        run = EvaluationRun(kind=kind, status="running", method=METHODS[kind], created_by=owner_id, model_info=model_info,
                            dataset={"name": dataset_name, "items": len(gold) if gold else None, "document_ids": [str(i) for i in doc_ids]})
        db.add(run)
        db.commit()
        rid = run.id

    def work():
        with SessionLocal() as db:
            run = db.get(EvaluationRun, rid)
            try:
                if kind == "extraction":
                    m, d = run_extraction(db, owner_id, doc_ids)
                elif kind == "extraction_gold":
                    m, d = run_extraction_gold(db, owner_id, gold or [])
                else:
                    m, d = run_rag(db, owner_id, gold or [])
                run.metrics, run.details, run.status = json.loads(json.dumps(m, default=str)), json.loads(json.dumps(d, default=str)), "completed"
            except Exception as exc:
                run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            run.finished_at = dt.datetime.now(dt.timezone.utc)
            db.commit()

    threading.Thread(target=work, daemon=True).start()
    return rid

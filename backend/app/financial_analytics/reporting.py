"""Financial analysis reports built from stored, traceable data.

Sections: overview, financial performance (key metrics per period), trends
(growth), profitability & ratios, comparison (several documents), optional
AI-generated summary (RAG, cited and verified), limitations & missing
information. All figures come from `financial_metrics`; ratios from the Python
engine. No investment recommendations are produced.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Session

from app.financial_analytics import service
from app.financial_analytics.comparison import compare_documents
from app.financial_analytics.metric_extractor import METRIC_NAMES
from app.models import Document, User
from app.rag.rag_pipeline import answer_question

KEY_METRICS = ["revenue_from_operations", "total_revenue", "net_sales", "total_income", "total_expenses", "operating_profit", "profit_before_tax",
               "net_profit", "profit_after_tax", "eps_basic", "total_assets", "total_liabilities", "total_equity", "borrowings_non_current",
               "borrowings_current", "total_debt", "cash_and_cash_equivalents", "net_cash_operating", "net_cash_investing", "net_cash_financing"]


class ReportError(ValueError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def build_report(db: Session, user: User, doc_ids: list[uuid.UUID], include_ai_summary: bool) -> dict:
    docs = db.query(Document).filter(Document.owner_id == user.id, Document.id.in_(doc_ids)).all()
    if not docs:
        raise ReportError(404, "No documents found")
    not_ready = [d.original_filename for d in docs if d.status != "processed"]
    docs = [d for d in docs if d.status == "processed"]
    if not docs:
        raise ReportError(422, "None of the selected documents has been processed successfully.")
    ids = [d.id for d in docs]
    comparison = compare_documents(db, user.id, ids, None, False)
    ratios = service.compute_ratios(db, user.id, ids, persist=False)
    perf = []
    for col in comparison["columns"]:
        vals = {k: v for k, v in col["values"].items() if k in KEY_METRICS}
        if vals:
            perf.append({"filename": col["filename"], "organisation": col["organisation"], "basis": col["basis"], "unit": col["unit"],
                         "currency": col["currency"], "period_label": col["period_label"],
                         "metrics": [{"metric_key": k, "metric_name": METRIC_NAMES.get(k, k), "raw_value": v["raw_value"], "value": v["value"],
                                      "validation_status": v["validation_status"], "source": f"{v['filename']}, {v['location_text']}"}
                                     for k, v in sorted(vals.items(), key=lambda kv: KEY_METRICS.index(kv[0]))]})
    growth = [r for r in ratios if r["calc_key"].endswith("_growth") and r["status"] == "ok"]
    point = [r for r in ratios if not r["calc_key"].endswith("_growth")]
    found = {k for c in comparison["columns"] for k in c["values"]}
    limitations = []
    if not_ready:
        limitations.append("Not included (not processed): " + ", ".join(not_ready))
    missing = [METRIC_NAMES[k] for k in KEY_METRICS if k not in found]
    if missing:
        limitations.append("Not found in the documents: " + ", ".join(missing) + ".")
    insufficient = sorted({r["name"] for r in point if r["status"] != "ok"} - {r["name"] for r in point if r["status"] == "ok"})
    if insufficient:
        limitations.append("Ratios that could not be computed from the available inputs: " + ", ".join(insufficient) + ".")
    unvalidated = sum(1 for c in comparison["columns"] for v in c["values"].values() if v["validation_status"] in ("unvalidated", "needs_review"))
    if unvalidated:
        limitations.append(f"{unvalidated} reported value(s) have not passed an automated accounting check and have not been human-verified.")
    for d in docs:
        for k in ("organisation", "reporting_period", "currency", "unit"):
            if not (d.doc_metadata or {}).get(k, {}).get("value"):
                limitations.append(f"{d.original_filename}: {k.replace('_', ' ')} not detected.")
    limitations += comparison["warnings"]
    limitations.append("This report describes reported figures only. It is not investment advice.")
    ai = None
    if include_ai_summary:
        r = answer_question(db, user.id, "Summarise the financial performance described in these documents, citing figures.", ids)
        ai = {"label": "AI-generated summary (verify against sources)", "status": r.status, "text": r.answer,
              "citations": r.citations, "verification": {k: v for k, v in r.verification.items() if k != "raw_model_output"}, "model": r.model}
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "generated_for": user.email,
        "overview": [{"filename": d.original_filename, "format": d.file_format, "organisation": d.organisation_name or "Not detected",
                      "reporting_period": d.reporting_period or "Not detected", "fiscal_year": d.fiscal_year or "Not detected",
                      "category": d.category or "Not detected", "currency": d.currency or "Not detected", "unit": d.unit or "Not detected",
                      "pages": d.page_count, "sheets": d.sheet_names, "metrics_extracted": d.metric_count} for d in docs],
        "financial_performance": perf,
        "trends": growth,
        "ratios": [r for r in point if r["status"] == "ok"],
        "comparison": comparison if len(docs) > 1 else None,
        "ai_summary": ai,
        "limitations": list(dict.fromkeys(limitations)),
    }


def to_markdown(rep: dict) -> str:
    L = ["# FinRAG Financial Analysis Report", f"_Generated {rep['generated_at']} for {rep['generated_for']}_", "", "## 1. Documents"]
    for o in rep["overview"]:
        L.append(f"- **{o['filename']}** ({o['format']}): organisation {o['organisation']}; period {o['reporting_period']}; "
                 f"category {o['category']}; currency {o['currency']}; unit {o['unit']}; {o['metrics_extracted']} metric values extracted")
    L += ["", "## 2. Financial performance (as reported)"]
    if not rep["financial_performance"]:
        L.append("No key financial metrics were extracted from the selected documents.")
    for p in rep["financial_performance"]:
        L += ["", f"### {p['filename']} — {p['period_label'] or 'period not detected'} ({p['basis'] or 'basis not detected'}, unit: {p['unit'] or 'not stated'}, currency: {p['currency'] or 'not detected'})",
              "", "| Metric | Reported value | Validation | Source |", "|---|---|---|---|"]
        L += [f"| {m['metric_name']} | {m['raw_value']} | {m['validation_status']} | {m['source']} |" for m in p["metrics"]]
    L += ["", "## 3. Trends"]
    L += [f"- {r['name']} ({r['filename']}, {r['basis'] or 'basis n/d'}): **{r['result']}%** for {r['period_label']} — {r['formula']}" for r in rep["trends"]] or ["No multi-period data available."]
    L += ["", "## 4. Profitability and ratios (computed in Python)"]
    for r in rep["ratios"]:
        unit = "%" if r["result_unit"] == "percent" else "×"
        L.append(f"- **{r['name']}** = {r['result']}{unit} ({r['filename']}, {r['period_label']}, {r['basis'] or 'basis n/d'}); formula: {r['formula']}"
                 + (f"; notes: {'; '.join(r['warnings'])}" if r["warnings"] else ""))
        for i in r["inputs"]:
            L.append(f"  - {i['key']} = {i['value']} — {i['source']} ({i['validation_status']})")
    if not rep["ratios"]:
        L.append("No ratio could be computed from the available inputs.")
    if rep.get("ai_summary"):
        a = rep["ai_summary"]
        L += ["", f"## 5. {a['label']}", "", a["text"], ""]
        L += [f"- [{c['sid']}] {c.get('filename')}, {c.get('location_text')}" for c in a["citations"]]
    L += ["", "## Limitations and missing information"] + [f"- {x}" for x in rep["limitations"]]
    return "\n".join(L) + "\n"

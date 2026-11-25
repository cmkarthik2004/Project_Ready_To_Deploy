"""Structured facts added to the prompt next to retrieved passages.

* [M#] extracted metric values relevant to the question (from `financial_metrics`),
  showing the printed row label, value, unit, period, basis and validation status.
* [C#] ratios computed by FinRAG in Python when the question asks for a calculation.

Both are filtered by any basis/period the question names, so a "consolidated 2024-25"
question never receives standalone or other-year facts.
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.document_processing.elements import describe_location
from app.financial_analytics import service as analytics
from app.financial_analytics.metric_extractor import METRICS, normalise_label
from app.financial_analytics.ratios import DEBT_DEF
from app.models import Document
from app.rag.retriever import in_scope, question_scope

CALC_RE = re.compile(r"\b(margin|ratio|growth|grew|increase|decrease|change|compare|comparison|versus|vs\.?|return on|roe|roa|"
                     r"debt[- ]to[- ]equity|leverage|coverage|calculate|compute|percentage)\b", re.I)

METRIC_TERMS: dict[str, list[str]] = {m.key: list({m.name.lower(), m.key.replace("_", " ")}) for m in METRICS}
EXTRA_TERMS = {
    "revenue_from_operations": ["revenue", "sales", "turnover", "top line"], "total_revenue": ["revenue"], "net_sales": ["sales", "revenue"],
    "net_profit": ["net profit", "profit", "net income", "earnings", "bottom line"], "profit_after_tax": ["profit", "pat"],
    "total_assets": ["assets", "balance sheet"], "total_liabilities": ["liabilities", "balance sheet"], "total_equity": ["equity", "net worth", "balance sheet"],
    "borrowings_non_current": ["debt", "borrowing"], "borrowings_current": ["debt", "borrowing"], "total_debt": ["debt", "borrowing"],
    "cash_and_cash_equivalents": ["cash"], "total_expenses": ["expense", "cost"], "eps_basic": ["eps", "earnings per share"],
    "net_cash_operating": ["cash flow", "operating cash"], "operating_profit": ["operating profit", "ebit"],
}
SUMMARY_KEYS = {"revenue_from_operations", "total_revenue", "net_sales", "total_income", "total_expenses", "net_profit", "profit_before_tax",
                "total_assets", "total_liabilities", "total_equity", "cash_and_cash_equivalents"}


def relevant_metric_keys(question: str) -> set[str]:
    q = question.lower()
    keys = {k for k, terms in METRIC_TERMS.items() if any(t in q for t in terms + EXTRA_TERMS.get(k, []))}
    if re.search(r"summar|overview|performance|balance sheet|financial position", q):
        keys |= SUMMARY_KEYS
    return keys


def fmt_num(v) -> str:
    s = str(v)
    return s.rstrip("0").rstrip(".") if "." in s else s


def metric_facts(db: Session, owner_id: uuid.UUID, question: str, docs: list[Document]) -> list[dict]:
    keys = relevant_metric_keys(question)
    if not keys:
        return []
    s = get_settings()
    by_id = {str(d.id): d for d in docs}
    basis_q, periods_q = question_scope(question)
    ms = [m for m in analytics.load_metrics(db, owner_id, [d.id for d in docs])
          if m.metric_key in keys and m.validation_status not in ("rejected", "failed_validation")]
    scoped = [m for m in ms if in_scope(basis_q, periods_q, m.basis, m.period_label)]
    ms = scoped if scoped else ms
    ql = question.lower()

    def label_match(m) -> int:  # how specifically the printed label / metric name matches the question
        lab = normalise_label(m.raw_label)
        if lab and lab in ql:
            return 0
        if m.metric_name.lower().split(" (")[0] in ql:
            return 1
        return 2

    ms.sort(key=lambda m: (label_match(m), analytics.TRUST_ORDER.get(m.validation_status, 9), str(m.document_id), m.metric_key))
    out = []
    for n, m in enumerate(ms[: s.max_metric_facts], 1):
        d = by_id[str(m.document_id)]
        loc = m.source.location
        txt = (f"\"{' '.join(m.raw_label.split())[:80]}\" [{m.metric_name}] = {m.raw_value} ({m.unit or 'unit not stated'}"
               f"{', ' + m.currency if m.currency else ''}); period: {m.period_label or 'not stated'}; "
               f"basis: {m.basis or 'not stated in document'}; {m.validation_status}")
        out.append({"sid": f"M{n}", "kind": "extracted_metric", "metric_id": str(m.id), "document_id": str(d.id), "filename": d.original_filename,
                    "organisation": d.organisation_name, "location": loc, "location_text": describe_location(loc), "text": txt})
    return out


TOTAL_DEBT_RE = re.compile(r"\btotal\s+(debt|borrowings?)\b|\b(debt|borrowings?)\s+in\s+total\b", re.I)


def derived_total_facts(db: Session, owner_id: uuid.UUID, question: str, docs: list[Document]) -> list[dict]:
    """When the question asks for total borrowings/debt and the document prints only the current and
    non-current parts, add the Python-computed sum (definition: ratios.DEBT_DEF) as a [C#] fact, so the
    model never has to add numbers itself or present one component as the total."""
    if not TOTAL_DEBT_RE.search(question):
        return []
    basis_q, periods_q = question_scope(question)
    by_id = {str(d.id): d for d in docs}
    out = []
    groups = analytics.group_metrics(analytics.load_metrics(db, owner_id, [d.id for d in docs]), by="label")
    for (doc_id, basis, unit, _p), mm in groups.items():
        nc, cur = mm.get("borrowings_non_current"), mm.get("borrowings_current")
        if "total_debt" in mm or not (nc and cur) or not in_scope(basis_q, periods_q, basis, nc.period_label):
            continue
        d = by_id[str(doc_id)]
        if (pending := [m for m in (nc, cur) if m.validation_status not in ("validated", "verified")]):
            # Calculations use validated/verified inputs only. Say so explicitly, so the model reports the printed
            # parts and that the total was not computed, instead of adding them itself.
            out.append({"kind": "calculation", "document_id": str(d.id), "filename": d.original_filename, "organisation": d.organisation_name,
                        "location_text": "FinRAG calculation (Python) — not computed",
                        "text": (f"Total borrowings for {nc.period_label} was NOT computed: it is not printed in the document, and its "
                                 f"parts are not yet validated or verified ({', '.join(f'{m.metric_key}: {m.validation_status}' for m in pending)}). "
                                 "Report the printed parts separately and state that the total was not computed; do not add them.")})
            continue
        total = nc.value + cur.value
        out.append({"kind": "calculation", "document_id": str(d.id), "filename": d.original_filename, "organisation": d.organisation_name,
                    "location_text": "computed by FinRAG (Python)",
                    "text": (f"Total borrowings (derived, not printed in the document) = {fmt_num(total)} ({unit or 'unit not stated'}) "
                             f"for {nc.period_label}; basis: {basis or 'not stated in document'}; definition: {DEBT_DEF}; inputs: "
                             f"non-current borrowings {nc.raw_value} ({describe_location(nc.source.location)}); "
                             f"current borrowings {cur.raw_value} ({describe_location(cur.source.location)})")})
    return out[:3]


def calculation_facts(db: Session, owner_id: uuid.UUID, question: str, docs: list[Document]) -> tuple[list[dict], list[dict]]:
    """Returns (sources, ratio results): derived totals (if asked for) and ratios for calculation-type questions."""
    derived = derived_total_facts(db, owner_id, question, docs)
    if not CALC_RE.search(question):
        for n, f in enumerate(derived, 1):
            f["sid"] = f"C{n}"
        return derived, []
    s = get_settings()
    basis_q, periods_q = question_scope(question)
    allr = [r for r in analytics.compute_ratios(db, owner_id, [d.id for d in docs], persist=False) if r["status"] == "ok"]
    if basis_q or periods_q:  # never answer a scoped question with out-of-scope calculations
        allr = [r for r in allr if in_scope(basis_q, periods_q, r["basis"], r["period_label"])]
    ql = question.lower()
    wanted = [r for r in allr if any(w in ql for w in r["name"].lower().replace("(", " ").split() if len(w) > 4)] or allr
    sources, calcs = [], []
    for n, f in enumerate(derived, 1):
        f["sid"] = f"C{n}"
        sources.append(f)
    for n, r in enumerate(wanted[: s.max_calc_facts], len(derived) + 1):
        ins = "; ".join(f"{i['key']}={fmt_num(i['value'])} ({i['source']})" for i in r["inputs"])
        unit = "%" if r["result_unit"] == "percent" else (" times" if r["result_unit"] == "times" else "")
        txt = (f"{r['name']} = {fmt_num(r['result'])}{unit} for {r['period_label']}; basis: {r['basis'] or 'not stated in document'}; "
               f"formula: {r['formula']}; inputs: {ins}" + (f"; notes: {'; '.join(r['warnings'][:2])}" if r["warnings"] else ""))
        calcs.append(r)
        sources.append({"sid": f"C{n}", "kind": "calculation", "document_id": r["document_id"], "filename": r["filename"],
                        "organisation": r["organisation"], "location_text": "computed by FinRAG (Python)", "text": txt})
    return sources, calcs

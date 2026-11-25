"""Database-level analytics: ratios, series and document comparison.

All numbers come from `financial_metrics` rows. Values are grouped by
(document, basis, unit, period column). Comparisons across documents use
normalised values only when both units are known, and emit warnings whenever
currency, unit, basis, period type or metric definitions differ.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from app.document_processing.elements import describe_location
from app.financial_analytics.metric_extractor import METRICS, fiscal_year_of, period_sort_key
from app.financial_analytics.ratios import Input, RatioResult, compute_point_ratios, growth
from app.models import Document, FinancialCalculation, FinancialMetric

TRUST_ORDER = {"verified": 0, "validated": 1, "unvalidated": 2, "needs_review": 3, "failed_validation": 4, "rejected": 5}
EXCLUDED = ("rejected",)
GROWTH_KEYS = [("revenue_from_operations", "Revenue from operations"), ("total_revenue", "Total revenue"), ("net_sales", "Net sales"),
               ("total_income", "Total income"), ("net_profit", "Net profit"), ("profit_before_tax", "Profit before tax"),
               ("total_assets", "Total assets"), ("total_equity", "Total equity")]


def norm_period(label: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (label or "").lower())


def metric_dict(m: FinancialMetric, doc: Document | None = None) -> dict:
    loc = m.source.location if m.source else {}
    return {
        "id": str(m.id), "document_id": str(m.document_id), "filename": doc.original_filename if doc else None,
        "metric_key": m.metric_key, "metric_name": m.metric_name, "raw_label": m.raw_label, "raw_value": m.raw_value,
        "value": str(m.value), "unit": m.unit, "normalized_value": None if m.normalized_value is None else str(m.normalized_value),
        "currency": m.currency, "period_label": m.period_label, "period_end": m.period_end.isoformat() if m.period_end else None,
        "period_sort": period_sort_key(m.period_label, m.period_end),
        "statement_type": m.statement_type, "basis": m.basis, "extraction_method": m.extraction_method, "confidence": m.confidence,
        "validation_status": m.validation_status, "validation_notes": m.validation_notes, "is_duplicate": m.is_duplicate,
        "value_origin": m.value_origin, "fiscal_year": fiscal_year(m), "is_total": m.is_total,
        "location": loc, "location_text": describe_location(loc) if loc else None, "snippet": m.source.snippet if m.source else None,
        "verified_at": m.verified_at.isoformat() if m.verified_at else None,
    }


def load_metrics(db: Session, owner_id: uuid.UUID, doc_ids: list[uuid.UUID], include_line_items: bool = False) -> list[FinancialMetric]:
    q = db.query(FinancialMetric).join(Document, Document.id == FinancialMetric.document_id).filter(
        Document.owner_id == owner_id, FinancialMetric.document_id.in_(doc_ids), FinancialMetric.is_duplicate.is_(False))
    if not include_line_items:
        q = q.filter(FinancialMetric.metric_key != "line_item")
    return q.all()


EXPECTED_STATEMENT = {m.key: m.statement for m in METRICS}


def fiscal_year(m: FinancialMetric) -> int | None:
    """Year in which the column's period ends: '2024-25' -> 2025, 'As at 31 March 2025' -> 2025.
    Used to align income-statement columns with the balance-sheet date of the same year."""
    if m.fiscal_year is not None:
        return m.fiscal_year
    return fiscal_year_of(m.period_label, m.period_end)


def _rank(m: FinancialMetric) -> tuple:
    exp = EXPECTED_STATEMENT.get(m.metric_key)
    wrong_statement = 1 if (exp and m.statement_type and m.statement_type != exp) else 0
    return (TRUST_ORDER.get(m.validation_status, 9), wrong_statement, -(m.confidence or 0))


def group_metrics(metrics: list[FinancialMetric], by: str = "label") -> dict[tuple, dict[str, FinancialMetric]]:
    """Group values into comparable columns -> {metric_key: best metric}.

    by="label": (document, basis, unit, column label)  — one column per printed header (comparison view)
    by="year":  (document, basis, unit, fiscal year)    — aligns '2024-25' with 'As at 31 March 2025' (ratios)
    The best value per metric prefers human-verified/validated values and values from the statement
    the metric belongs to. Per-share metrics are attached to every group of their document/basis/period.
    """
    def key(m):
        return (m.document_id, m.basis, m.unit, norm_period(m.period_label) if by == "label" else fiscal_year(m))

    g: dict[tuple, dict[str, FinancialMetric]] = defaultdict(dict)
    per_share: list[FinancialMetric] = []
    for m in metrics:
        if m.validation_status in EXCLUDED:
            continue
        if by == "year" and fiscal_year(m) is None:
            continue
        if m.unit == "per_share":
            per_share.append(m)
            continue
        k = key(m)
        cur = g[k].get(m.metric_key)
        if cur is None or _rank(m) < _rank(cur):
            g[k][m.metric_key] = m
    for m in per_share:
        for k in g:
            if k[0] == m.document_id and k[1] == m.basis and k[3] == (norm_period(m.period_label) if by == "label" else fiscal_year(m)):
                cur = g[k].get(m.metric_key)
                if cur is None or _rank(m) < _rank(cur):
                    g[k][m.metric_key] = m
    return g


def _input(m: FinancialMetric) -> Input:
    loc = m.source.location if m.source else {}
    return Input(m.metric_key, m.value, str(m.id), m.period_label, describe_location(loc) if loc else None, m.validation_status)


def compute_ratios(db: Session, owner_id: uuid.UUID, doc_ids: list[uuid.UUID], persist: bool = True) -> list[dict]:
    metrics = load_metrics(db, owner_id, doc_ids)
    docs = {d.id: d for d in db.query(Document).filter(Document.id.in_(doc_ids)).all()}
    groups = group_metrics(metrics, by="year")
    out: list[dict] = []
    if persist:
        db.query(FinancialCalculation).filter(FinancialCalculation.owner_id == owner_id, FinancialCalculation.document_id.in_(doc_ids)).delete(synchronize_session=False)
    # point-in-time ratios
    def label_of(mm: dict[str, FinancialMetric]) -> str | None:
        pl = [m.period_label for m in mm.values() if m.statement_type == "profit_and_loss" and m.period_label]
        return pl[0] if pl else next(iter(mm.values())).period_label

    for (doc_id, basis, unit, _pk), mm in groups.items():
        period = label_of(mm)
        lookup = lambda key, mm=mm: _input(mm[key]) if key in mm else None  # noqa: E731
        for r in compute_point_ratios(lookup, period):
            out.append(_wrap(r, docs.get(doc_id), basis, unit))
    # growth between consecutive periods of the same document/basis/unit
    series: dict[tuple, list[tuple[float, dict[str, FinancialMetric], str | None]]] = defaultdict(list)
    for (doc_id, basis, unit, year), mm in groups.items():
        series[(doc_id, basis, unit)].append((float(year), mm, label_of(mm)))
    for (doc_id, basis, unit), pts in series.items():
        pts.sort(key=lambda x: x[0])
        for (s0, prev, _l0), (s1, cur, l1) in zip(pts, pts[1:]):
            for key, name in GROWTH_KEYS:
                if key in cur and key in prev:
                    r = growth(key, name, _input(cur[key]), _input(prev[key]), l1)
                    out.append(_wrap(r, docs.get(doc_id), basis, unit))
    if persist:
        for o in out:
            if o["status"] == "insufficient_data":
                continue
            db.add(FinancialCalculation(owner_id=owner_id, document_id=uuid.UUID(o["document_id"]) if o["document_id"] else None,
                                        calc_key=o["calc_key"], formula=o["formula"], period_label=o["period_label"], inputs=o["inputs"],
                                        result=Decimal(o["result"]) if o["result"] is not None else None, result_unit=o["result_unit"],
                                        status=o["status"], warnings=o["warnings"]))
        db.commit()
    return out


def _wrap(r: RatioResult, doc: Document | None, basis, unit) -> dict:
    d = r.to_dict()
    d.update({"document_id": str(doc.id) if doc else None, "filename": doc.original_filename if doc else None,
              "organisation": doc.organisation_name if doc else None, "basis": basis, "unit": unit})
    return d

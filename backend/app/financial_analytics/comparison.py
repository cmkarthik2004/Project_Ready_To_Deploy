"""Document comparison: side-by-side values with compatibility warnings.

Columns are (document, basis, unit, printed column label). Values are shown as
printed; nothing is converted between currencies. Warnings are raised for
different currencies, units, bases, point-in-time vs period columns, different or
undetected organisations, and possible restatements (same organisation, period,
basis and metric with a different validated value in another document).
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from app.financial_analytics.metric_extractor import METRIC_NAMES, period_sort_key
from app.financial_analytics.service import group_metrics, load_metrics, metric_dict, norm_period
from app.models import Document


def compare_documents(db: Session, owner_id: uuid.UUID, doc_ids: list[uuid.UUID], metric_keys: list[str] | None = None,
                      include_line_items: bool = False) -> dict:
    docs = db.query(Document).filter(Document.owner_id == owner_id, Document.id.in_(doc_ids)).all()
    metrics = load_metrics(db, owner_id, [d.id for d in docs], include_line_items=include_line_items)
    if metric_keys:
        metrics = [m for m in metrics if m.metric_key in metric_keys or (m.metric_key == "line_item" and m.metric_name in metric_keys)]
    groups = group_metrics(metrics)
    warnings: list[str] = []
    columns = []
    for (doc_id, basis, unit, pk), mm in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]), period_sort_key(next(iter(kv[1].values())).period_label, None) or 0)):
        d = next(x for x in docs if x.id == doc_id)
        anym = next(iter(mm.values()))
        columns.append({
            "column_id": f"{doc_id}|{basis}|{unit}|{pk}", "document_id": str(doc_id), "filename": d.original_filename,
            "organisation": d.organisation_name, "basis": basis, "unit": unit, "currency": anym.currency,
            "period_label": anym.period_label, "period_sort": period_sort_key(anym.period_label, anym.period_end),
            "values": {(k if k != "line_item" else f"line_item:{m.metric_name}"): metric_dict(m, d) for k, m in mm.items()},
        })
    keys = sorted({k for c in columns for k in c["values"]})
    rows = []
    for k in keys:
        present = [c for c in columns if k in c["values"]]
        rows.append({"metric_key": k, "metric_name": METRIC_NAMES.get(k, k.split(":", 1)[-1]), "present_in": len(present), "total_columns": len(columns)})

    # --- compatibility warnings ------------------------------------------------
    currencies = {c["currency"] for c in columns}
    units = {c["unit"] for c in columns}
    bases = {c["basis"] for c in columns}
    if len(currencies) > 1:
        warnings.append("Currencies differ or are not detected for some columns: " + ", ".join(str(c or "not detected") for c in currencies) + ". Values are NOT converted between currencies.")
    if len(units) > 1:
        warnings.append("Units differ: " + ", ".join(str(u or "not stated") for u in units) + ". Compare normalised values (shown when the unit is known).")
    if None in units:
        warnings.append("Some values have no stated unit; they cannot be normalised.")
    if len(bases) > 1:
        warnings.append("Reporting basis differs (" + ", ".join(str(b or "not detected") for b in bases) + "): consolidated and standalone figures are not directly comparable.")
    labels = {c["period_label"] for c in columns}
    if any(re.search(r"as at|as of", (l or ""), re.I) for l in labels) and any(re.search(r"(?:19|20)\d{2}\s?-\s?\d{2}|year ended", (l or ""), re.I) for l in labels):
        warnings.append("Point-in-time (balance sheet) and period (income statement) columns are both present; they are shown separately.")
    orgs = {d.organisation_name for d in docs}
    if len(orgs) > 1:
        warnings.append("Documents relate to different (or undetected) organisations: " + ", ".join(o or "not detected" for o in orgs) + ".")
    # same organisation, same period/basis/metric, different value across documents => restatement or inconsistency
    seen: dict[tuple, tuple[str, str, str]] = {}
    for c in columns:
        for k, v in c["values"].items():
            org = next(d.organisation_name for d in docs if str(d.id) == c["document_id"])
            if not org or k.startswith("line_item") or not c["basis"] or v["validation_status"] not in ("validated", "verified"):
                continue  # only trusted values with a known basis can indicate a restatement
            key = (org, c["basis"], norm_period(c["period_label"]), k, c["unit"])
            if key in seen and seen[key][0] != c["document_id"] and seen[key][1] != v["value"]:
                warnings.append(f"'{METRIC_NAMES.get(k, k)}' for {c['period_label']} is {v['raw_value']} in {c['filename']} but {seen[key][2]} in another document (possible restatement).")
            seen.setdefault(key, (c["document_id"], v["value"], v["raw_value"]))
    missing_docs = [d.original_filename for d in docs if not any(c["document_id"] == str(d.id) for c in columns)]
    if missing_docs:
        warnings.append("No comparable financial metrics were extracted from: " + ", ".join(missing_docs) + ".")
    return {"documents": [{"id": str(d.id), "filename": d.original_filename, "organisation": d.organisation_name, "fiscal_year": d.fiscal_year,
                           "currency": d.currency, "unit": d.unit, "category": d.category, "status": d.status} for d in docs],
            "columns": columns, "rows": rows, "warnings": list(dict.fromkeys(warnings))}

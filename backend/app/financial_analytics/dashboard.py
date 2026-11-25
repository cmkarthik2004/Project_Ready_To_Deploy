"""Automatic financial dashboard: KPIs and charts chosen from whatever reliable data the user's documents contain.

Principles
----------
* **One fact per (organisation, basis, metric, fiscal year).** The same figure often appears in two reports (a prior-year
  comparative column). It is used once — never summed twice. The chosen value prefers human-verified/validated values,
  then the most recent report (restated comparatives), then confidence; the alternatives are kept and a differing value is
  flagged as "restated or conflicting".
* **Reported values** are charted with their validation status. Rejected and failed values are never used.
* **Calculated values** (margins, growth, debt-to-equity, derived totals) come from the Python ratio engine and use
  validated/verified inputs only. Those that cannot be computed yet are listed under `pending_verification`, not shown as
  empty cards.
* **Charts follow the data's shape**: trends need ≥ 2 fiscal years (lines need ≥ 3); composition charts (pie/donut/treemap)
  are drawn only from non-negative parts, and a part-of-total donut only when the parts reconcile to the printed total.
* **Units and currencies are never mixed or converted**: values are shown in one display unit per organisation
  (normalised values re-expressed in that unit); values whose unit is unknown are left out of unit-bearing charts and
  reported as a limitation. Currencies are reported as detected, never converted.
* Charts are not stored: a saved dashboard stores filters only and is recomputed from the facts on every load.
"""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.document_processing.elements import describe_location
from app.document_processing.metadata import UNIT_MULTIPLIER
from app.financial_analytics.ratios import Input, compute_point_ratios, growth
from app.financial_analytics.service import EXPECTED_STATEMENT, TRUST_ORDER, fiscal_year
from app.models import Document, FinancialMetric

TRUSTED = ("validated", "verified")
UNUSABLE = ("rejected", "failed_validation")
REVENUE_KEYS = ("revenue_from_operations", "total_revenue", "net_sales")
PROFIT_KEYS = ("net_profit", "profit_after_tax")  # same preference as the ratio engine (ratios.NET_PROFIT_KEYS)
EXPENSE_PARTS = ["cost_of_materials", "cost_of_revenue", "employee_benefits_expense", "finance_costs",
                 "depreciation_amortisation", "operating_expenses"]
LABEL = {
    "revenue_from_operations": "Revenue from operations", "total_revenue": "Total revenue", "net_sales": "Net sales",
    "total_income": "Total income", "gross_profit": "Gross profit", "ebitda": "EBITDA", "ebit": "EBIT", "operating_profit": "Operating profit",
    "profit_before_tax": "Profit before tax", "profit_after_tax": "Profit after tax", "net_profit": "Net profit (profit for the year)",
    "total_tax_expense": "Tax expense", "total_expenses": "Total expenses", "total_assets": "Total assets",
    "total_liabilities": "Total liabilities", "total_equity": "Total equity", "total_current_assets": "Current assets",
    "total_non_current_assets": "Non-current assets", "total_current_liabilities": "Current liabilities",
    "total_non_current_liabilities": "Non-current liabilities", "borrowings_current": "Current borrowings",
    "borrowings_non_current": "Non-current borrowings", "total_debt": "Total borrowings",
    "cash_and_cash_equivalents": "Cash and cash equivalents", "net_cash_operating": "Operating cash flow",
    "net_cash_investing": "Investing cash flow", "net_cash_financing": "Financing cash flow", "opening_cash": "Opening cash",
    "closing_cash": "Closing cash", "net_change_in_cash": "Net change in cash", "eps_basic": "Basic EPS",
    "cost_of_materials": "Cost of materials", "cost_of_revenue": "Cost of revenue", "employee_benefits_expense": "Employee benefits",
    "finance_costs": "Finance costs", "depreciation_amortisation": "Depreciation & amortisation", "operating_expenses": "Operating expenses",
    "other_income": "Other income", "capital_expenditure": "Capital expenditure",
}


@dataclass
class Fact:
    metric: FinancialMetric
    document: Document
    entity: str
    entity_name: str
    basis: str | None
    fy: int
    value: Decimal                 # in the entity's display unit (or as printed when the unit is not stated)
    alternatives: list[dict] = field(default_factory=list)

    def to_point(self) -> dict:
        loc = self.metric.source.location if self.metric.source else {}
        return {"kind": "reported", "metric_id": str(self.metric.id), "metric_key": self.metric.metric_key,
                "raw_label": self.metric.raw_label, "raw_value": self.metric.raw_value, "value": _s(self.value),
                "period_label": self.metric.period_label, "fiscal_year": self.fy, "validation_status": self.metric.validation_status,
                "value_origin": self.metric.value_origin, "document_id": str(self.document.id), "filename": self.document.original_filename,
                "location_text": describe_location(loc) if loc else None, "alternatives": self.alternatives}


def _s(d: Decimal | None) -> str | None:
    if d is None:
        return None
    t = format(d.normalize(), "f")
    return t.rstrip("0").rstrip(".") if "." in t else t


def _f(d: Decimal | None) -> float | None:
    return None if d is None else round(float(d), 4)


def _doc_max_fy(metrics: list[FinancialMetric]) -> dict[uuid.UUID, int]:
    out: dict[uuid.UUID, int] = {}
    for m in metrics:
        fy = fiscal_year(m)
        if fy is not None:
            out[m.document_id] = max(out.get(m.document_id, fy), fy)
    return out


def available_filters(db: Session, owner_id: uuid.UUID) -> dict:
    docs = db.query(Document).filter(Document.owner_id == owner_id, Document.status == "processed").order_by(Document.uploaded_at).all()
    rows = db.query(FinancialMetric.fiscal_year, FinancialMetric.basis, FinancialMetric.metric_key).join(Document).filter(
        Document.owner_id == owner_id, Document.status == "processed", FinancialMetric.metric_key != "line_item").distinct().all()
    orgs: dict[str, str] = {}
    for d in docs:
        orgs[str(d.organisation_id) if d.organisation_id else f"doc:{d.id}"] = d.organisation_name or f"{d.original_filename} (organisation not detected)"
    return {"documents": [{"id": str(d.id), "filename": d.original_filename, "organisation": d.organisation_name, "format": d.file_format,
                           "entity": str(d.organisation_id) if d.organisation_id else f"doc:{d.id}"}
                          for d in docs],
            "organisations": [{"id": k, "name": v} for k, v in orgs.items()],
            "fiscal_years": sorted({r[0] for r in rows if r[0] is not None}),
            "bases": sorted({r[1] or "not_stated" for r in rows}),
            "metrics": sorted({r[2] for r in rows if r[2] in LABEL}, key=lambda k: LABEL[k])}


def select_facts(db: Session, owner_id: uuid.UUID, filters: dict) -> tuple[list[Fact], dict]:
    """Return de-duplicated facts and selection statistics."""
    q = db.query(Document).filter(Document.owner_id == owner_id, Document.status == "processed")
    if filters.get("document_ids"):
        q = q.filter(Document.id.in_([uuid.UUID(x) for x in filters["document_ids"]]))
    docs = {d.id: d for d in q.all()}
    if filters.get("organisations"):
        want = set(filters["organisations"])
        docs = {k: d for k, d in docs.items() if (str(d.organisation_id) if d.organisation_id else f"doc:{d.id}") in want}
    stats = {"documents": len(docs), "facts_considered": 0, "excluded_unusable": 0, "excluded_unknown_unit": 0,
             "cross_document_duplicates": 0, "conflicts": 0}
    if not docs:
        return [], stats
    metrics = (db.query(FinancialMetric).filter(FinancialMetric.document_id.in_(list(docs)), FinancialMetric.is_duplicate.is_(False),
                                                FinancialMetric.metric_key.in_(list(LABEL))).all())
    max_fy = _doc_max_fy(metrics)
    fy_filter = set(int(x) for x in filters.get("fiscal_years") or [])
    basis_filter = filters.get("basis")
    # display unit per entity: the most common stated unit among its monetary values
    unit_votes: dict[str, Counter] = defaultdict(Counter)
    cands: dict[tuple, list[FinancialMetric]] = defaultdict(list)
    for m in metrics:
        stats["facts_considered"] += 1
        if m.validation_status in UNUSABLE:
            stats["excluded_unusable"] += 1
            continue
        fy = fiscal_year(m)
        if fy is None or m.unit in ("percent",) or (fy_filter and fy not in fy_filter):
            continue
        b = m.basis or "not_stated"
        if basis_filter and basis_filter != b:
            continue
        d = docs[m.document_id]
        ent = str(d.organisation_id) if d.organisation_id else f"doc:{d.id}"
        if m.unit and m.unit != "per_share":
            unit_votes[ent][m.unit] += 1
        cands[(ent, b, m.metric_key, fy)].append(m)
    display_unit = {e: (v.most_common(1)[0][0] if v else None) for e, v in unit_votes.items()}

    def rank(m: FinancialMetric) -> tuple:
        exp = EXPECTED_STATEMENT.get(m.metric_key)
        wrong = 1 if (exp and m.statement_type and m.statement_type != exp) else 0
        return (TRUST_ORDER.get(m.validation_status, 9), wrong, -max_fy.get(m.document_id, 0), -(m.confidence or 0))

    facts: list[Fact] = []
    for (ent, b, key, fy), ms in cands.items():
        du = display_unit.get(ent)

        def in_display(m: FinancialMetric) -> Decimal | None:
            if m.unit == "per_share":
                return m.value
            if du is None:
                return m.value if m.unit is None else None
            if m.unit is None or m.normalized_value is None:
                return None
            return m.normalized_value / Decimal(UNIT_MULTIPLIER[du])

        usable = [(m, in_display(m)) for m in ms]
        usable = [(m, v) for m, v in usable if v is not None]
        if not usable:
            stats["excluded_unknown_unit"] += len(ms)
            continue
        usable.sort(key=lambda mv: rank(mv[0]))
        best, val = usable[0]
        alts = []
        for m, v in usable[1:]:
            if m.document_id != best.document_id:
                stats["cross_document_duplicates"] += 1
            differs = abs(v - val) > max(Decimal(1), abs(val) * Decimal("0.0005"))
            stats["conflicts"] += 1 if differs else 0
            alts.append({"metric_id": str(m.id), "filename": docs[m.document_id].original_filename, "raw_value": m.raw_value,
                         "validation_status": m.validation_status, "differs": differs,
                         "note": "restated or conflicting value" if differs else "same value reported again"})
        d = docs[best.document_id]
        facts.append(Fact(best, d, ent, d.organisation_name or f"{d.original_filename}", None if b == "not_stated" else b, fy, val, alts))
    stats["display_units"] = {e: u for e, u in display_unit.items()}
    stats["facts_used"] = len(facts)
    return facts, stats


def _default_basis(facts: list[Fact]) -> str | None:
    c = Counter(f.basis for f in facts)
    for b in ("consolidated", "standalone", None):
        if c.get(b):
            return b
    return None


def _first(table: dict[str, Fact], keys: tuple[str, ...]) -> Fact | None:
    for k in keys:
        if k in table:
            return table[k]
    return None


def _input(f: Fact) -> Input:
    return Input(f.metric.metric_key, f.value, str(f.metric.id), f.metric.period_label,
                 f"{f.document.original_filename}, {describe_location(f.metric.source.location)}" if f.metric.source else f.document.original_filename,
                 f.metric.validation_status)


def build_dashboard(db: Session, owner_id: uuid.UUID, filters: dict | None = None) -> dict:
    filters = dict(filters or {})
    facts, stats = select_facts(db, owner_id, filters)
    out = {"filters": filters, "available": available_filters(db, owner_id), "stats": stats, "kpis": [], "charts": [],
           "pending_verification": [], "limitations": [], "entities": []}
    if not facts:
        out["limitations"].append("No extracted financial values match the current filters." if stats["documents"] else
                                  "No processed documents yet. Upload a financial document to generate a dashboard.")
        return out
    basis = filters.get("basis") or _default_basis(facts)
    if not filters.get("basis") and len({f.basis for f in facts}) > 1:
        out["limitations"].append(f"Showing {basis or 'basis not stated'} figures; other bases are available in the basis filter "
                                  "(consolidated and standalone figures are never combined).")
    facts = [f for f in facts if f.basis == basis]
    out["basis"] = basis
    by_ent: dict[str, dict[int, dict[str, Fact]]] = defaultdict(lambda: defaultdict(dict))
    names: dict[str, str] = {}
    for f in facts:
        by_ent[f.entity][f.fy][f.metric.metric_key] = f
        names[f.entity] = f.entity_name
    if stats["excluded_unknown_unit"]:
        out["limitations"].append(f"{stats['excluded_unknown_unit']} value(s) were left out because their unit is not stated while "
                                  "other values of the same organisation have a unit (they cannot be placed on the same scale).")
    if stats["conflicts"]:
        out["limitations"].append(f"{stats['conflicts']} alternative value(s) differ from the value used for the same metric and year "
                                  "(another table, a restated comparative or an extraction to review). The most trusted, most recent "
                                  "value is used; alternatives are listed in each data point's details.")

    for ent, years in by_ent.items():
        unit = stats["display_units"].get(ent)
        currencies = sorted({f.metric.currency for y in years.values() for f in y.values() if f.metric.currency})
        if len(currencies) > 1:
            out["limitations"].append(f"{names[ent]}: values carry different currencies ({', '.join(currencies)}); they are not converted.")
        out["entities"].append({"id": ent, "name": names[ent], "unit": unit, "currency": currencies[0] if len(currencies) == 1 else None,
                                "fiscal_years": sorted(years)})
        _entity_dashboard(out, ent, names[ent], years, unit, currencies[0] if len(currencies) == 1 else None, len(by_ent) > 1)
    if len(by_ent) > 1:
        _cross_entity(out, by_ent, names, stats)
    return out


def _ratio_results(years: dict[int, dict[str, Fact]]) -> dict[int, dict[str, dict]]:
    res: dict[int, dict[str, dict]] = {}
    fys = sorted(years)
    for fy in fys:
        t = years[fy]
        lookup = lambda k, t=t: _input(t[k]) if k in t else None  # noqa: E731
        res[fy] = {r.calc_key: r.to_dict() for r in compute_point_ratios(lookup, f"FY{fy}")}
    for a, b in zip(fys, fys[1:]):
        for key, name in (("revenue", "Revenue"), ("profit", "Net profit"), ("ebitda", "EBITDA"), ("total_assets", "Total assets")):
            keys = {"revenue": REVENUE_KEYS, "profit": PROFIT_KEYS, "ebitda": ("ebitda",), "total_assets": ("total_assets",)}[key]
            cur, prev = _first(years[b], keys), _first(years[a], keys)
            if cur and prev and cur.metric.metric_key == prev.metric.metric_key:
                res[b][f"{key}_growth"] = growth(key, name, _input(cur), _input(prev), f"FY{b}").to_dict()
    return res


def _calc_point(r: dict) -> dict:
    return {"kind": "calculated", "calc_key": r["calc_key"], "formula": r["formula"], "value": r["result"],
            "inputs": r["inputs"], "warnings": r["warnings"]}


def _entity_dashboard(out: dict, ent: str, name: str, years: dict[int, dict[str, Fact]], unit: str | None,
                      currency: str | None, multi: bool) -> None:
    fys = sorted(years)
    latest, prev = fys[-1], (fys[-2] if len(fys) > 1 else None)
    ratios = _ratio_results(years)
    unit_label = " ".join(x for x in (currency, unit) if x) or "unit not stated"
    prefix = f"{name} · " if multi else ""

    # ---------------- KPIs ----------------
    def reported_kpi(kid: str, label: str, keys: tuple[str, ...]) -> None:
        f = _first(years[latest], keys)
        if not f:
            return
        p = _first(years[prev], (f.metric.metric_key,)) if prev else None
        change = None
        if p and p.value != 0 and f.metric.validation_status in TRUSTED and p.metric.validation_status in TRUSTED:
            change = _s(((f.value - p.value) / abs(p.value) * 100).quantize(Decimal("0.01")))
        out["kpis"].append({"id": f"{ent}:{kid}", "entity": ent, "label": prefix + (label if f.metric.metric_key == keys[0] else LABEL.get(f.metric.metric_key, label)),
                            "value": _s(f.value), "unit": "per share" if f.metric.unit == "per_share" else unit, "currency": currency,
                            "fiscal_year": latest, "period_label": f.metric.period_label, "origin": f.metric.value_origin,
                            "validation_status": f.metric.validation_status, "previous": _s(p.value) if p else None,
                            "previous_fiscal_year": prev if p else None, "change_pct": change,
                            "change_note": None if change or not p else "change not computed: inputs not validated/verified",
                            "sources": [f.to_point()] + ([p.to_point()] if p else [])})

    def calc_kpi(kid: str, label: str, calc_key: str, unit_override: str) -> None:
        r = ratios.get(latest, {}).get(calc_key)
        if not r or r["status"] == "insufficient_data":
            return
        if r["status"] != "ok":
            out["pending_verification"].append({"entity": ent, "label": prefix + label, "fiscal_year": latest, "status": r["status"],
                                                "reason": "; ".join(r["warnings"][-1:]) or r["status"]})
            return
        pr = ratios.get(prev, {}).get(calc_key) if prev else None
        out["kpis"].append({"id": f"{ent}:{kid}", "entity": ent, "label": prefix + label, "value": r["result"], "unit": unit_override,
                            "currency": None, "fiscal_year": latest, "period_label": f"FY{latest}", "origin": "calculated",
                            "validation_status": "calculated from validated inputs", "formula": r["formula"],
                            "previous": pr["result"] if pr and pr["status"] == "ok" else None,
                            "previous_fiscal_year": prev if pr and pr["status"] == "ok" else None,
                            "change_pct": None, "sources": [_calc_point(r)]})

    reported_kpi("revenue", "Revenue", REVENUE_KEYS)
    calc_kpi("revenue_growth", "Revenue growth", "revenue_growth", "%")
    reported_kpi("gross_profit", "Gross profit", ("gross_profit",))
    reported_kpi("ebitda", "EBITDA", ("ebitda",))
    calc_kpi("ebitda_margin", "EBITDA margin", "ebitda_margin", "%")
    reported_kpi("pat", "Net profit (profit for the year)", PROFIT_KEYS)
    calc_kpi("net_margin", "Net profit margin", "net_profit_margin", "%")
    reported_kpi("total_assets", "Total assets", ("total_assets",))
    reported_kpi("borrowings", "Total borrowings", ("total_debt",))
    if not _first(years[latest], ("total_debt",)):
        t = years[latest]
        if "borrowings_current" in t and "borrowings_non_current" in t:
            parts = [t["borrowings_current"], t["borrowings_non_current"]]
            if all(p.metric.validation_status in TRUSTED for p in parts):
                total = parts[0].value + parts[1].value
                out["kpis"].append({"id": f"{ent}:borrowings", "entity": ent, "label": prefix + "Total borrowings (derived)", "value": _s(total),
                                    "unit": unit, "currency": currency, "fiscal_year": latest, "period_label": parts[0].metric.period_label,
                                    "origin": "calculated", "validation_status": "calculated from validated inputs",
                                    "formula": "current borrowings + non-current borrowings (not printed in the document)",
                                    "previous": None, "previous_fiscal_year": None, "change_pct": None,
                                    "sources": [{"kind": "calculated", "formula": "borrowings_current + borrowings_non_current", "value": _s(total),
                                                 "inputs": [p.to_point() for p in parts], "warnings": []}]})
            else:
                out["pending_verification"].append({"entity": ent, "label": prefix + "Total borrowings (derived)", "fiscal_year": latest,
                                                    "status": "needs_verification",
                                                    "reason": "current and non-current borrowings are not both validated/verified"})
    reported_kpi("cash", "Cash and cash equivalents", ("cash_and_cash_equivalents", "closing_cash"))
    reported_kpi("ocf", "Operating cash flow", ("net_cash_operating",))
    calc_kpi("de", "Debt-to-equity", "debt_to_equity", "times")
    reported_kpi("eps", "Basic EPS", ("eps_basic",))

    # ---------------- charts ----------------
    charts = out["charts"]

    def series_chart(cid, ctype, title, desc, keys_list, fy_list=None, min_series=1) -> None:
        fy_list = fy_list or fys
        series, rows, points = [], [], {}
        for ks in keys_list:
            ks = ks if isinstance(ks, tuple) else (ks,)
            if any(_first(years[fy], ks) for fy in fy_list):
                series.append(ks)
        if len(series) < min_series:
            return
        ser_meta = []
        for ks in series:
            k0 = next((_first(years[fy], ks).metric.metric_key for fy in fy_list if _first(years[fy], ks)), ks[0])
            ser_meta.append({"key": k0, "label": LABEL.get(k0, k0), "origin": "reported"})
        for fy in fy_list:
            row = {"x": f"FY{fy}"}
            for ks, sm in zip(series, ser_meta):
                f = _first(years[fy], ks)
                if f and f.metric.metric_key == sm["key"]:
                    row[sm["key"]] = _f(f.value)
                    points[f"FY{fy}|{sm['key']}"] = f.to_point()
            rows.append(row)
        if sum(1 for r in rows for k in r if k != "x") == 0:
            return
        charts.append({"id": f"{ent}:{cid}", "entity": ent, "type": ctype, "title": prefix + title, "description": desc,
                       "unit": unit_label, "series": ser_meta, "rows": rows, "points": points})

    multi_year = len(fys) >= 2
    trend = "line" if len(fys) >= 3 else "grouped_bar"
    series_chart("rev_profit", "grouped_bar" if multi_year else "bar", "Revenue and profit",
                 "Revenue, EBITDA and profit after tax by fiscal year" if multi_year else f"Revenue and profit, FY{latest}",
                 [REVENUE_KEYS, ("ebitda",), PROFIT_KEYS])
    if multi_year:
        series_chart("rev_trend", trend, "Revenue trend", "Revenue by fiscal year", [REVENUE_KEYS])
        series_chart("position_trend", "area", "Balance sheet size", "Total assets and total equity over time",
                     [("total_assets",), ("total_equity",)])
    series_chart("position", "grouped_bar", "Financial position", "Assets, liabilities and equity",
                 [("total_assets",), ("total_liabilities",), ("total_equity",)], fy_list=fys[-2:], min_series=2)
    series_chart("cash_debt", "grouped_bar", "Cash and borrowings", "Cash compared with current and non-current borrowings",
                 [("cash_and_cash_equivalents", "closing_cash"), ("borrowings_current",), ("borrowings_non_current",), ("total_debt",)],
                 fy_list=fys[-2:], min_series=2)
    series_chart("cash_flows", "grouped_bar", "Cash flows by activity", "Operating, investing and financing cash flows",
                 [("net_cash_operating",), ("net_cash_investing",), ("net_cash_financing",)], min_series=2)

    t = years[latest]
    # borrowings composition (pie) — non-negative parts only
    parts = [(k, t[k]) for k in ("borrowings_current", "borrowings_non_current") if k in t and t[k].value >= 0]
    if len(parts) == 2:
        charts.append({"id": f"{ent}:borrowings_mix", "entity": ent, "type": "pie", "title": prefix + "Borrowings composition",
                       "description": f"Current vs non-current borrowings, FY{latest}", "unit": unit_label,
                       "series": [{"key": "value", "label": "Amount", "origin": "reported"}],
                       "rows": [{"x": LABEL[k], "value": _f(f.value)} for k, f in parts],
                       "points": {f"{LABEL[k]}|value": f.to_point() for k, f in parts}})
    # assets composition (donut) — only when current + non-current reconcile to total assets
    if all(k in t for k in ("total_current_assets", "total_non_current_assets", "total_assets")):
        ca, nca, ta = t["total_current_assets"], t["total_non_current_assets"], t["total_assets"]
        if ca.value >= 0 and nca.value >= 0 and abs(ca.value + nca.value - ta.value) <= max(Decimal(2), ta.value * Decimal("0.0005")):
            charts.append({"id": f"{ent}:assets_mix", "entity": ent, "type": "donut", "title": prefix + "Asset composition",
                           "description": f"Current and non-current assets (reconcile to total assets {_s(ta.value)}), FY{latest}",
                           "unit": unit_label, "series": [{"key": "value", "label": "Amount", "origin": "reported"}],
                           "rows": [{"x": "Current assets", "value": _f(ca.value)}, {"x": "Non-current assets", "value": _f(nca.value)}],
                           "points": {"Current assets|value": ca.to_point(), "Non-current assets|value": nca.to_point()}})
    # expense breakdown (treemap) — reported, non-negative expense lines
    exp = [(k, t[k]) for k in EXPENSE_PARTS if k in t and t[k].value > 0]
    if len(exp) >= 3:
        charts.append({"id": f"{ent}:expenses", "entity": ent, "type": "treemap", "title": prefix + "Expense breakdown",
                       "description": f"Reported expense lines, FY{latest} (lines not printed are not estimated)", "unit": unit_label,
                       "series": [{"key": "value", "label": "Amount", "origin": "reported"}],
                       "rows": [{"x": LABEL[k], "value": _f(f.value)} for k, f in sorted(exp, key=lambda kf: -kf[1].value)],
                       "points": {f"{LABEL[k]}|value": f.to_point() for k, f in exp}})
    # cash reconciliation waterfall: opening → three activities (→ other, if any) → closing
    if all(k in t for k in ("opening_cash", "closing_cash", "net_cash_operating", "net_cash_investing", "net_cash_financing")):
        steps = [("Opening cash", "opening_cash", "start"), ("Operating", "net_cash_operating", "delta"),
                 ("Investing", "net_cash_investing", "delta"), ("Financing", "net_cash_financing", "delta")]
        rows = [{"x": lab, "value": _f(t[k].value), "kind": kind} for lab, k, kind in steps]
        points = {f"{lab}|value": t[k].to_point() for lab, k, _ in steps}
        other = t["closing_cash"].value - t["opening_cash"].value - sum(t[k].value for _, k, kd in steps if kd == "delta")
        if other != 0:  # FX effects etc.: shown explicitly as the reconciling difference computed in Python
            rows.append({"x": "Other (FX and reconciling items)", "value": _f(other), "kind": "delta"})
            points["Other (FX and reconciling items)|value"] = {"kind": "calculated", "formula": "closing − opening − operating − investing − financing",
                                                                "value": _s(other), "inputs": [], "warnings": []}
        rows.append({"x": "Closing cash", "value": _f(t["closing_cash"].value), "kind": "end"})
        points["Closing cash|value"] = t["closing_cash"].to_point()
        charts.append({"id": f"{ent}:cash_waterfall", "entity": ent, "type": "waterfall", "title": prefix + "Cash reconciliation",
                       "description": f"Opening to closing cash, FY{latest}", "unit": unit_label,
                       "series": [{"key": "value", "label": "Amount", "origin": "reported"}], "rows": rows, "points": points})
    elif all(k in t for k in ("profit_before_tax", "total_tax_expense")) and _first(t, PROFIT_KEYS):
        pat = _first(t, PROFIT_KEYS)
        rows = [{"x": "Profit before tax", "value": _f(t["profit_before_tax"].value), "kind": "start"},
                {"x": "Tax expense", "value": _f(-t["total_tax_expense"].value), "kind": "delta"}]
        points = {"Profit before tax|value": t["profit_before_tax"].to_point(), "Tax expense|value": t["total_tax_expense"].to_point()}
        other = pat.value - t["profit_before_tax"].value + t["total_tax_expense"].value
        if other != 0:
            rows.append({"x": "Other items", "value": _f(other), "kind": "delta"})
            points["Other items|value"] = {"kind": "calculated", "formula": "PAT − PBT + tax", "value": _s(other), "inputs": [], "warnings": []}
        rows.append({"x": LABEL[pat.metric.metric_key], "value": _f(pat.value), "kind": "end"})
        points[f"{LABEL[pat.metric.metric_key]}|value"] = pat.to_point()
        charts.append({"id": f"{ent}:profit_waterfall", "entity": ent, "type": "waterfall", "title": prefix + "Profit before tax to profit after tax",
                       "description": f"FY{latest}", "unit": unit_label, "series": [{"key": "value", "label": "Amount", "origin": "reported"}],
                       "rows": rows, "points": points})

    # calculated: margins over time, ratio comparison, growth heatmap
    margin_keys = [("gross_margin", "Gross margin"), ("ebitda_margin", "EBITDA margin"), ("operating_profit_margin", "Operating margin"),
                   ("net_profit_margin", "Net profit margin")]
    rows, points, ser = [], {}, []
    for k, lab in margin_keys:
        if any(ratios[fy].get(k, {}).get("status") == "ok" for fy in fys):
            ser.append({"key": k, "label": lab, "origin": "calculated"})
    for fy in fys:
        row = {"x": f"FY{fy}"}
        for s_ in ser:
            r = ratios[fy].get(s_["key"])
            if r and r["status"] == "ok":
                row[s_["key"]] = float(r["result"])
                points[f"FY{fy}|{s_['key']}"] = _calc_point(r)
        rows.append(row)
    if ser:
        charts.append({"id": f"{ent}:margins", "entity": ent, "type": "line" if len(fys) >= 2 else "bar", "title": prefix + "Profitability margins",
                       "description": "Calculated in Python from validated or verified inputs", "unit": "%", "series": ser, "rows": rows, "points": points})
    ratio_keys = [("debt_to_equity", "Debt-to-equity"), ("current_ratio", "Current ratio"), ("interest_coverage", "Interest coverage")]
    rows, points, ser = [], {}, []
    for k, lab in ratio_keys:
        if any(ratios[fy].get(k, {}).get("status") == "ok" for fy in fys):
            ser.append({"key": k, "label": lab, "origin": "calculated"})
    for fy in fys:
        row = {"x": f"FY{fy}"}
        for s_ in ser:
            r = ratios[fy].get(s_["key"])
            if r and r["status"] == "ok":
                row[s_["key"]] = float(r["result"])
                points[f"FY{fy}|{s_['key']}"] = _calc_point(r)
        rows.append(row)
    if ser:
        charts.append({"id": f"{ent}:ratios", "entity": ent, "type": "grouped_bar", "title": prefix + "Financial ratios",
                       "description": "Times; calculated in Python from validated or verified inputs", "unit": "times",
                       "series": ser, "rows": rows, "points": points})
    if len(fys) >= 2:
        hm_rows, hm_points = [], {}
        for gk, lab in (("revenue_growth", "Revenue"), ("profit_growth", "Net profit"), ("ebitda_growth", "EBITDA"), ("total_assets_growth", "Total assets")):
            row = {"x": lab}
            for fy in fys[1:]:
                r = ratios[fy].get(gk)
                if r and r["status"] == "ok":
                    row[f"FY{fy}"] = float(r["result"])
                    hm_points[f"{lab}|FY{fy}"] = _calc_point(r)
            if len(row) > 1:
                hm_rows.append(row)
        if hm_rows:
            charts.append({"id": f"{ent}:growth_heatmap", "entity": ent, "type": "heatmap", "title": prefix + "Year-over-year growth",
                           "description": "Growth % vs the previous fiscal year (validated or verified inputs only)", "unit": "%",
                           "series": [{"key": f"FY{fy}", "label": f"FY{fy}", "origin": "calculated"} for fy in fys[1:]],
                           "rows": hm_rows, "points": hm_points})
    for fy in fys:
        for k, r in ratios[fy].items():
            if r["status"] in ("needs_verification", "invalid_input") and fy == latest and not any(
                    p["label"].endswith(r["name"]) for p in out["pending_verification"]):
                out["pending_verification"].append({"entity": ent, "label": prefix + r["name"], "fiscal_year": fy, "status": r["status"],
                                                    "reason": r["warnings"][-1] if r["warnings"] else r["status"]})


def _cross_entity(out: dict, by_ent: dict, names: dict, stats: dict) -> None:
    """Compare organisations only on a common fiscal year and only when they share a display unit."""
    common = set.intersection(*[set(y) for y in by_ent.values()])
    units = {stats["display_units"].get(e) for e in by_ent}
    if not common:
        out["limitations"].append("The organisations have no fiscal year in common, so no side-by-side comparison is drawn.")
        return
    if len(units) > 1:
        out["limitations"].append("The organisations report in different units; a side-by-side chart would be misleading and is not drawn.")
        return
    fy = max(common)
    for cid, title, keys in (("cmp_revenue", "Revenue by organisation", REVENUE_KEYS), ("cmp_profit", "Profit by organisation", PROFIT_KEYS),
                             ("cmp_assets", "Total assets by organisation", ("total_assets",))):
        rows, points = [], {}
        for e, years in by_ent.items():
            f = _first(years[fy], keys)
            if f:
                rows.append({"x": names[e], "value": _f(f.value)})
                points[f"{names[e]}|value"] = f.to_point()
        if len(rows) >= 2:
            out["charts"].append({"id": f"all:{cid}", "entity": "all", "type": "bar", "title": title, "description": f"FY{fy}",
                                  "unit": next(iter(units)) or "unit not stated", "series": [{"key": "value", "label": "Amount", "origin": "reported"}],
                                  "rows": rows, "points": points})


def to_markdown(d: dict) -> str:
    L = ["# FinRAG dashboard export", "", f"Basis: {d.get('basis') or 'not stated'} · documents: {d['stats']['documents']} · "
         f"facts used: {d['stats'].get('facts_used', 0)} (cross-document duplicates removed: {d['stats']['cross_document_duplicates']})", ""]
    if d["kpis"]:
        L += ["## Key figures", "", "| KPI | Value | Unit | FY | Origin | Status | Source |", "|---|---|---|---|---|---|---|"]
        for k in d["kpis"]:
            src = k["sources"][0]
            where = f"{src.get('filename')}, {src.get('location_text')}" if src.get("kind") == "reported" else src.get("formula", "")
            L.append(f"| {k['label']} | {k['value']} | {' '.join(x for x in (k.get('currency'), k.get('unit')) if x) or '-'} | {k['fiscal_year']} "
                     f"| {k['origin']} | {k['validation_status']} | {where} |")
    for c in d["charts"]:
        L += ["", f"## {c['title']}", "", f"{c['description']} ({c['unit']})", ""]
        cols = [s["key"] for s in c["series"]]
        L += ["| | " + " | ".join(s["label"] for s in c["series"]) + " |", "|---" * (len(cols) + 1) + "|"]
        for r in c["rows"]:
            L.append(f"| {r['x']} | " + " | ".join("" if r.get(k) is None else str(r.get(k)) for k in cols) + " |")
    if d["pending_verification"]:
        L += ["", "## Not computed until inputs are verified", ""] + [f"- {p['label']} (FY{p['fiscal_year']}): {p['reason']}" for p in d["pending_verification"]]
    if d["limitations"]:
        L += ["", "## Limitations", ""] + [f"- {x}" for x in d["limitations"]]
    return "\n".join(L) + "\n"

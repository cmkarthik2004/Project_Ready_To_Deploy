"""Deterministic financial metric extraction from parsed elements.

Nothing here is company- or format-specific. A table row becomes one metric
value per numeric cell when its label matches a canonical metric definition.
For spreadsheets, CSV and Word tables, rows that do not match a canonical
metric are kept as generic `line_item` values (e.g. budget lines or expense
categories) so they can still be analysed and compared.

Each `ExtractedMetric` keeps: raw label, raw printed value, Decimal value,
unit & multiplier (from the nearest unit statement), currency, column/period
label as printed, statement type and basis (consolidated/standalone) when the
surrounding title states them, an exact source location, method and confidence.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.document_processing.elements import Element, Location
from app.document_processing.metadata import DATE_DMY, DATE_MDY, UNIT_MULTIPLIER, _date, unit_from_text
from app.financial_analytics.numbers import is_percent, parse_number


@dataclass(frozen=True)
class MetricDef:
    key: str
    name: str
    patterns: tuple[str, ...]
    statement: str | None = None
    # Row-group rule: find the nearest enclosing group label matching `group_topic`;
    # it must then match `group_required` (or, if group_required is None, no such group may exist).
    group_topic: str | None = None
    group_required: str | None = None
    per_share: bool = False


# Order matters: first match wins, so specific definitions come first.
METRICS: list[MetricDef] = [
    MetricDef("eps_basic", "Basic EPS", (r"^basic(\s*eps)?\b", r"basic earnings per (equity )?share", r"earnings per share.*basic"), "profit_and_loss", per_share=True),
    MetricDef("eps_diluted", "Diluted EPS", (r"^diluted(\s*eps)?\b", r"diluted earnings per (equity )?share", r"earnings per share.*diluted"), "profit_and_loss", per_share=True),
    MetricDef("total_equity_and_liabilities", "Total equity and liabilities", (r"^total equity and liabilities$", r"^total liabilities and (shareholders'?|stockholders'?)? ?equity$"), "balance_sheet"),
    MetricDef("total_current_assets", "Total current assets", (r"^total current assets$",), "balance_sheet"),
    MetricDef("total_non_current_assets", "Total non-current assets", (r"^total non[- ]current assets$",), "balance_sheet"),
    MetricDef("total_assets", "Total assets", (r"^total assets$",), "balance_sheet"),
    MetricDef("total_current_liabilities", "Total current liabilities", (r"^total current liabilities$",), "balance_sheet"),
    MetricDef("total_non_current_liabilities", "Total non-current liabilities", (r"^total non[- ]current liabilities$",), "balance_sheet"),
    MetricDef("total_liabilities", "Total liabilities", (r"^total liabilities$",), "balance_sheet"),
    MetricDef("total_equity", "Total equity", (r"^total equity$", r"^total (shareholders'?|stockholders'?) ?equity$", r"^shareholders'? funds$", r"^total net worth$"), "balance_sheet"),
    MetricDef("equity_share_capital", "Equity share capital", (r"^(equity )?share capital$",), "balance_sheet"),
    MetricDef("other_equity", "Other equity", (r"^other equity$", r"^reserves and surplus$"), "balance_sheet"),
    MetricDef("non_controlling_interest", "Non-controlling interest (balance sheet)", (r"^non[- ]controlling interests?$",), "balance_sheet", group_topic=r"attributable"),
    # Explicit labels map directly (reported); a bare "Borrowings" row is mapped from its section heading (inferred).
    MetricDef("borrowings_non_current", "Borrowings (non-current)", (r"^long[- ]term borrowings$", r"^non[- ]current borrowings$"), "balance_sheet"),
    MetricDef("borrowings_current", "Borrowings (current)", (r"^short[- ]term borrowings$", r"^current borrowings$"), "balance_sheet"),
    MetricDef("borrowings_non_current", "Borrowings (non-current)", (r"^borrowings$",), "balance_sheet", group_topic=r"current", group_required=r"non[- ]?current"),
    MetricDef("borrowings_current", "Borrowings (current)", (r"^borrowings$",), "balance_sheet", group_topic=r"current", group_required=r"^(?!.*non[- ]?current).*current"),
    MetricDef("long_term_debt", "Long-term debt", (r"^long[- ]term debt$",), "balance_sheet"),
    MetricDef("short_term_debt", "Short-term debt", (r"^short[- ]term debt$",), "balance_sheet"),
    MetricDef("total_debt", "Total debt / borrowings", (r"^total (debt|borrowings)$",), "balance_sheet"),
    MetricDef("cash_and_cash_equivalents", "Cash and cash equivalents", (r"^cash and cash equivalents$", r"^cash and bank balances$", r"^cash & cash equivalents$")),
    MetricDef("trade_receivables", "Trade receivables", (r"^trade receivables$", r"^accounts receivable(, net)?$", r"^receivables$", r"^debtors$"), "balance_sheet"),
    MetricDef("trade_payables", "Trade payables", (r"^trade payables$", r"^accounts payable$", r"^creditors$"), "balance_sheet"),
    MetricDef("inventories", "Inventories", (r"^inventor(y|ies)$", r"^stock[- ]in[- ]trade$"), "balance_sheet"),
    MetricDef("revenue_from_operations", "Revenue from operations", (r"^revenue from operations( \(net\))?$", r"^operating revenues?$"), "profit_and_loss"),
    MetricDef("total_revenue", "Total revenue", (r"^total revenues?$", r"^revenues?$", r"^net revenues?$"), "profit_and_loss"),
    MetricDef("net_sales", "Net sales / turnover", (r"^net sales$", r"^sales$", r"^turnover$"), "profit_and_loss"),
    MetricDef("other_income", "Other income", (r"^other income$",), "profit_and_loss"),
    MetricDef("total_income", "Total income", (r"^total income$",), "profit_and_loss"),
    MetricDef("total_expenses", "Total expenses", (r"^total expenses$", r"^total expenditure$", r"^total operating expenses$", r"^total costs and expenses$")),
    MetricDef("operating_expenses", "Operating expenses", (r"^operating expenses$", r"^opex$")),
    MetricDef("cost_of_materials", "Cost of materials consumed", (r"^cost of materials consumed$",), "profit_and_loss"),
    MetricDef("cost_of_revenue", "Cost of revenue / goods sold", (r"^cost of (revenues?|sales|goods sold)$",), "profit_and_loss"),
    MetricDef("employee_benefits_expense", "Employee benefits expense", (r"^employee benefits? expenses?$", r"^employee costs?$", r"^salaries and wages$"), "profit_and_loss"),
    MetricDef("finance_costs", "Finance costs", (r"^finance costs?$", r"^interest expenses?$"), "profit_and_loss"),
    MetricDef("depreciation_amortisation", "Depreciation & amortisation", (r"^depreciation.*amorti[sz]ation", r"^depreciation$"), "profit_and_loss"),
    MetricDef("ebitda", "EBITDA", (r"^ebitda$",)),
    MetricDef("operating_profit", "Operating profit (as reported)", (r"^operating (profit|income)$", r"^profit from operations$"), "profit_and_loss"),
    MetricDef("ebit", "EBIT (as reported)", (r"^ebit$", r"^earnings before interest and tax(es|ation)?$"), "profit_and_loss"),
    MetricDef("gross_profit", "Gross profit", (r"^gross profit$",), "profit_and_loss"),
    MetricDef("profit_before_tax", "Profit before tax", (r"^profit before (share of .*)?(exceptional items and )?tax", r"^profit\s*/\s*\(loss\) before.*tax", r"^income before income taxes$", r"^pbt$"), "profit_and_loss"),
    MetricDef("current_tax", "Current tax", (r"^current tax$",), "profit_and_loss"),
    MetricDef("deferred_tax", "Deferred tax", (r"^deferred tax$",), "profit_and_loss"),
    MetricDef("total_tax_expense", "Total tax expense", (r"^total tax expenses?$", r"^tax expenses?$", r"^income tax expense$", r"^provision for (income )?tax(ation)?$"), "profit_and_loss"),
    MetricDef("profit_after_tax", "Profit after tax", (r"^profit after tax$", r"^pat$"), "profit_and_loss"),
    MetricDef("net_profit", "Profit for the period (net profit)", (r"^(net )?profit\s*(/\s*\(loss\))?\s*for the (year|period)$", r"^net profit$", r"^net income$", r"^net (profit|income) for the (year|period)$"), "profit_and_loss"),
    MetricDef("net_profit_attributable_owners", "Net profit attributable to owners", (r"owners of the (company|parent)", r"equity holders of the (company|parent)", r"shareholders of the company"), "profit_and_loss", group_topic=r"attributable", group_required=r"(net profit|profit for the (year|period))"),
    MetricDef("net_profit_attributable_nci", "Net profit attributable to non-controlling interest", (r"non[- ]controlling interests?$",), "profit_and_loss", group_topic=r"attributable", group_required=r"(net profit|profit for the (year|period))"),
    MetricDef("net_cash_operating", "Net cash from operating activities", (r"net cash (flows? )?(generated )?(from|used in|\(used in\)/generated from|from/\(used in\)) operating activities", ), "cash_flow"),
    MetricDef("cash_generated_from_operations", "Cash generated from operations (before tax paid)", (r"^cash generated from operations$",), "cash_flow"),
    MetricDef("net_change_in_cash", "Net change in cash and cash equivalents", (r"^net (increase|decrease|change)\s*(/\s*\((increase|decrease)\))?\s*in cash and cash equivalents", r"^net \((increase|decrease)\)\s*/\s*(increase|decrease) in cash and cash equivalents"), "cash_flow"),
    MetricDef("opening_cash", "Opening cash and cash equivalents", (r"^cash and cash equivalents at (the )?(beginning|start) of the (year|period)", r"^opening (balance of )?cash and cash equivalents"), "cash_flow"),
    MetricDef("closing_cash", "Closing cash and cash equivalents", (r"^cash and cash equivalents at (the )?end of the (year|period)", r"^closing (balance of )?cash and cash equivalents"), "cash_flow"),
    MetricDef("net_cash_investing", "Net cash from investing activities", (r"net cash (flows? )?(generated )?(from|used in|\(used in\)|from/\(used in\)) investing activities",), "cash_flow"),
    MetricDef("net_cash_financing", "Net cash from financing activities", (r"net cash (flows? )?(generated )?(from|used in|\(used in\)|from/\(used in\)) financing activities",), "cash_flow"),
    MetricDef("capital_expenditure", "Capital expenditure", (r"^capital expenditure$", r"^capex$", r"^purchase of property, plant and equipment"), "cash_flow"),
]
_COMPILED = [(m, [re.compile(p, re.I) for p in m.patterns]) for m in METRICS]
METRIC_NAMES = {m.key: m.name for m in METRICS} | {"line_item": "Line item"}

_LABEL_CLEAN = re.compile(r"^\(?[a-z0-9ivx]{1,4}[).]\s+|\s*\((?:in|net)[^)]*\)\s*$|[:*†#]+$|\s+\d{1,2}(\.\d{1,2})?$", re.I)


def normalise_label(label: str) -> str:
    s = " ".join(label.replace("’", "'").replace("&", "and").split())
    for _ in range(2):
        s = _LABEL_CLEAN.sub("", s).strip()
    s = re.sub(r"\s*/\s*", " / ", s)
    return s.lower()


def statement_type_from_context(ctx: list[str]) -> str | None:
    t = " ".join(ctx).lower()
    if re.search(r"balance sheet|financial position", t):
        return "balance_sheet"
    if re.search(r"profit and loss|income statement|statement of operations|comprehensive income", t):
        return "profit_and_loss"
    if re.search(r"cash flows?", t):
        return "cash_flow"
    if re.search(r"budget", t):
        return "budget"
    return None


def basis_from_context(ctx: list[str]) -> str | None:
    t = " ".join(ctx).lower()
    if "consolidated" in t:
        return "consolidated"
    if "standalone" in t or "stand-alone" in t or "separate financial statements" in t:
        return "standalone"
    return None


def period_end_from_label(label: str | None) -> dt.date | None:
    if not label:
        return None
    m = re.search(DATE_DMY, label)
    if m:
        return _date(m.group(1), m.group(2), m.group(3))
    m = re.search(DATE_MDY, label)
    if m:
        return _date(m.group(2), m.group(1), m.group(3))
    return None


def period_sort_key(label: str | None, end: dt.date | None) -> float | None:
    """Ordering key for periods. Uses explicit dates, else the last 4-digit year
    in the label ('2024-25' -> 2025). Returns None if no year is present."""
    if end:
        return end.year + end.month / 100
    if not label:
        return None
    m = re.search(r"((?:19|20)\d{2})\s?[-–/]\s?(\d{2,4})\b", label)
    if m:
        y2 = m.group(2)
        return float(int(m.group(1)[:2] + y2[-2:]) if len(y2) == 2 else int(y2))
    yrs = re.findall(r"(?:19|20)\d{2}", label)
    return float(yrs[-1]) if yrs else None


@dataclass
class ExtractedMetric:
    metric_key: str
    metric_name: str
    raw_label: str
    raw_value: str
    value: Decimal
    unit: str | None
    unit_multiplier: int | None
    currency: str | None
    period_label: str | None
    period_end: dt.date | None
    statement_type: str | None
    basis: str | None
    location: Location
    snippet: str
    method: str
    confidence: float
    notes: list[str] = field(default_factory=list)
    is_total: bool = False
    value_origin: str = "reported"  # reported | inferred_mapping
    linked_from: str | None = None  # spreadsheet cell that only references another cell (='P&L'!D5): a copy, not a new figure


PURE_REF_RE = re.compile(r"^=\s*((?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)?\$?[A-Z]{1,3}\$?\d+\s*$")


def fiscal_year_of(label: str | None, end: dt.date | None) -> int | None:
    """Year in which the period ends: '2024-25' -> 2025, 'As at 31 March 2025' -> 2025, 'FY2024' -> 2024."""
    if end:
        return end.year
    k = period_sort_key(label, None)
    return int(k) if k is not None else None


def _group_rule_ok(m: MetricDef, groups: list[str]) -> bool:
    if not m.group_topic:
        return True
    nearest = next((g for g in reversed(groups) if re.search(m.group_topic, g, re.I)), None)
    if m.group_required is None:
        return nearest is None
    return nearest is not None and re.search(m.group_required, nearest, re.I) is not None


def matches_any_pattern(label: str) -> bool:
    """True if the label matches any canonical pattern, ignoring row-group rules."""
    norm = normalise_label(label)
    return any(rx.search(norm) for _, rxs in _COMPILED for rx in rxs)


def match_metric(label: str, groups: list[str]) -> MetricDef | None:
    """Return the canonical metric for a row label (nearest-first `groups`), or None."""
    norm = normalise_label(label)
    for m, rxs in _COMPILED:
        if any(rx.search(norm) for rx in rxs) and _group_rule_ok(m, groups):
            return m
    return None


def extract_metrics(elements: list[Element], file_format: str, doc_currency: str | None, doc_unit: str | None,
                    keep_line_items: bool | None = None) -> list[ExtractedMetric]:
    keep_line_items = file_format in ("xlsx", "xls", "csv", "docx") if keep_line_items is None else keep_line_items
    out: list[ExtractedMetric] = []
    for el in elements:
        if el.kind != "table_row" or not el.cells or not el.label:
            continue
        ctx = [c for c in el.context if not c.startswith("group: ")]
        groups = [c[7:] for c in el.context if c.startswith("group: ")]
        mdef = match_metric(el.label, groups)
        if mdef is None and not keep_line_items:
            continue
        if mdef is None and ("computed_summary" in el.context or len(el.label) > 120):
            continue
        st = statement_type_from_context(ctx) or (mdef.statement if mdef else None)
        basis = basis_from_context(ctx)
        ctx_unit = None
        for c in reversed(ctx):
            ctx_unit = unit_from_text(c)
            if ctx_unit:
                break
        header_counts: dict[str | None, int] = {}
        for c in el.cells:
            header_counts[c.column_header] = header_counts.get(c.column_header, 0) + 1
        for cell in el.cells:
            v = parse_number(cell.text)
            if v is None:
                continue
            notes: list[str] = []
            col_basis = basis_from_context([cell.column_header or ""])
            header_unit = unit_from_text(cell.column_header or "")
            if is_percent(cell.text):
                unit, mult = "percent", None
            elif mdef and mdef.per_share:
                unit, mult = "per_share", 1
                notes.append("per-share amount: table unit statement does not apply")
            elif header_unit or ctx_unit:
                unit = header_unit or ctx_unit
                mult = UNIT_MULTIPLIER[unit]
            elif doc_unit:
                unit, mult = doc_unit, UNIT_MULTIPLIER[doc_unit]
                notes.append("unit taken from the document-level unit statement (no unit stated next to this table)")
            else:
                unit, mult = None, None
                notes.append("unit not stated: absolute amount assumed NOT normalised")
            conf = 0.9 if cell.column_header else 0.6
            if cell.location.ocr:
                conf -= 0.25
                notes.append("value read by OCR")
            if not cell.column_header:
                notes.append("no column/period header aligned with this value")
            elif header_counts.get(cell.column_header, 0) > 1:
                conf -= 0.4
                notes.append("several values in this row align with the same column header (sub-columns such as different "
                             "currencies or units are likely); unit and period need verification")
            if mdef is None:
                conf -= 0.2
            out.append(ExtractedMetric(
                metric_key=mdef.key if mdef else "line_item",
                metric_name=mdef.name if mdef else " ".join(el.label.split())[:120],
                raw_label=el.label,
                raw_value=cell.text,
                value=v,
                unit=unit,
                unit_multiplier=mult,
                currency=doc_currency,
                period_label=cell.column_header,
                period_end=period_end_from_label(cell.column_header),
                statement_type=st,
                basis=col_basis or basis,
                location=cell.location,
                snippet=el.text[:500],
                method=("canonical-label match" if mdef else "line item") + f" ({file_format} table row)",
                confidence=round(max(conf, 0.05), 2),
                notes=notes + (["mapped to this metric from its section heading (inferred mapping)"] if mdef and mdef.group_topic else []),
                is_total=el.is_total,
                linked_from=next((c[9:].lstrip("=").strip() for c in (cell.location.columns or []) if c.startswith("formula: ") and PURE_REF_RE.match(c[9:])), None),
                value_origin="inferred_mapping" if mdef and mdef.group_topic else "reported",
            ))
    return out


def inherit_basis(metrics: list[ExtractedMetric], full_text: str) -> str | None:
    """Values in a table without a 'consolidated'/'standalone' heading inherit the document's basis — but only when the
    document is unambiguous: every value that states a basis states the same one, or (if none does) the document's text
    mentions only one of the two. Documents with both bases are left alone. Returns the inherited basis (or None)."""
    stated = {m.basis for m in metrics if m.basis}
    if len(stated) == 1:
        b, why = next(iter(stated)), "every other value in this document is"
    elif not stated:
        c = re.search(r"\bconsolidated\b", full_text, re.I)
        s = re.search(r"\bstandalone\b|\bseparate financial statements\b", full_text, re.I)
        if bool(c) == bool(s):
            return None
        b, why = ("consolidated" if c else "standalone"), "the document describes its statements only as"
    else:
        return None
    for m in metrics:
        if m.basis is None:
            m.basis = b
            m.notes.append(f"basis inherited from the document ({why} {b})")
    return b

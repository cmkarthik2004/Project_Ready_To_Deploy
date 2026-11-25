"""Financial ratio engine — pure Python Decimal arithmetic, never LLM arithmetic.

Each ratio declares its formula and the canonical metric keys it needs. A ratio
is computed only when every input exists for the same document, basis, unit
and period column, and no input has failed validation. Results record the
formula, each input value, and the source of each input.

Where several reported line items could serve as "revenue" (revenue from
operations / total revenue / net sales), the first available in a documented
priority order is used and the choice is recorded in the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation
from typing import Any, Callable

REVENUE_KEYS = ("revenue_from_operations", "total_revenue", "net_sales")
NET_PROFIT_KEYS = ("net_profit", "profit_after_tax")
DEBT_DEF = "total debt = total_debt if reported, else borrowings_non_current + borrowings_current (lease liabilities excluded)"


@dataclass
class Input:
    key: str
    value: Decimal
    metric_id: str | None
    period_label: str | None
    source: str | None
    validation_status: str


@dataclass
class RatioResult:
    calc_key: str
    name: str
    formula: str
    result: Decimal | None
    result_unit: str
    status: str  # ok | insufficient_data | zero_denominator | invalid_input
    period_label: str | None
    inputs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"calc_key": self.calc_key, "name": self.name, "formula": self.formula,
                "result": None if self.result is None else str(self.result), "result_unit": self.result_unit,
                "status": self.status, "period_label": self.period_label, "inputs": self.inputs,
                "warnings": self.warnings, "missing": self.missing}


Lookup = Callable[[str], Input | None]

_SEVERITY = ["verified", "validated", "unvalidated", "needs_review", "failed_validation", "rejected"]
# Inputs with these statuses never feed a ratio: they are wrong, rejected, or ambiguous until a person verifies them.
BLOCKING = ("failed_validation", "rejected", "needs_review")
# Calculations use trusted inputs only: passed an accounting identity, or confirmed by a person.
TRUSTED = ("validated", "verified")


def _untrusted(used: list["Input"]) -> list[str]:
    return [f"{i.key} ({i.period_label}, {i.validation_status})" for i in used if i.validation_status not in TRUSTED]


def worst(*statuses: str) -> str:
    """The least trustworthy of several validation statuses."""
    return max(statuses, key=lambda s: _SEVERITY.index(s) if s in _SEVERITY else len(_SEVERITY))


def _first(lookup: Lookup, keys: tuple[str, ...]) -> Input | None:
    for k in keys:
        v = lookup(k)
        if v is not None:
            return v
    return None


def _debt(lookup: Lookup) -> tuple[Input | None, list[Input], list[str]]:
    td = lookup("total_debt")
    if td:
        return td, [td], []
    nc, cur = lookup("borrowings_non_current"), lookup("borrowings_current")
    if nc and cur:
        return Input("total_debt (derived)", nc.value + cur.value, None, nc.period_label, None,
                     worst(nc.validation_status, cur.validation_status)), [nc, cur], [DEBT_DEF]
    return None, [i for i in (nc, cur) if i], []


def _q(v: Decimal, places: str = "0.0001") -> Decimal:
    return v.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _ratio(calc_key, name, formula, unit, num: Input | None, den: Input | None, period, scale=Decimal(1),
           extra_inputs: list[Input] | None = None, warnings: list[str] | None = None, need=("numerator", "denominator")) -> RatioResult:
    r = RatioResult(calc_key, name, formula, None, unit, "insufficient_data", period, warnings=list(warnings or []))
    if num is None:
        r.missing.append(need[0])
    if den is None:
        r.missing.append(need[1])
    used = [i for i in (extra_inputs or [num, den]) if i is not None]
    r.inputs = [{"key": i.key, "value": str(i.value), "metric_id": i.metric_id, "period_label": i.period_label,
                 "source": i.source, "validation_status": i.validation_status} for i in used]
    if r.missing:
        return r
    if any(i.validation_status in BLOCKING for i in used):
        r.status = "invalid_input"
        r.warnings.append("an input failed validation, was rejected or needs review; ratio not computed (verify the input to use it)")
        return r
    if (pending := _untrusted(used)):
        r.status = "needs_verification"
        r.warnings.append("not computed: these inputs are neither validated by an accounting check nor verified by a person: "
                          + "; ".join(pending) + ". Verify them in Document Analysis to compute this ratio.")
        return r
    if den.value == 0:
        r.status = "zero_denominator"
        return r
    try:
        r.result = _q(num.value / den.value * scale)
        r.status = "ok"
    except (InvalidOperation, DivisionByZero):
        r.status = "invalid_input"
    if den.value < 0:
        r.warnings.append("denominator is negative; interpret with care")
    return r


def compute_point_ratios(lookup: Lookup, period: str | None) -> list[RatioResult]:
    """Ratios computable from a single period column."""
    out: list[RatioResult] = []
    rev = _first(lookup, REVENUE_KEYS)
    rev_w = [f"revenue input = '{rev.key}'"] if rev else []
    np_ = _first(lookup, NET_PROFIT_KEYS)
    np_w = [f"net profit input = '{np_.key}'"] if np_ else []
    out.append(_ratio("net_profit_margin", "Net profit margin", "net profit / revenue × 100", "percent", np_, rev, period, Decimal(100), warnings=rev_w + np_w, need=("net profit", "revenue")))

    for key, name, num_key in (("gross_margin", "Gross margin", "gross_profit"), ("ebitda_margin", "EBITDA margin", "ebitda")):
        num = lookup(num_key)
        if num is not None:  # only when the document reports the numerator itself (never derived here)
            out.append(_ratio(key, name, f"{num_key} / revenue × 100", "percent", num, rev, period, Decimal(100),
                              warnings=rev_w + [f"{num_key} as reported by the document"], need=(num_key.replace("_", " "), "revenue")))

    op = lookup("operating_profit")
    op_warn = []
    op_inputs = None
    if op is None:
        pbt, fc, oi = lookup("profit_before_tax"), lookup("finance_costs"), lookup("other_income")
        if pbt and fc and oi:
            op = Input("operating_profit (derived)", pbt.value + fc.value - oi.value, None, pbt.period_label, None,
                       worst(pbt.validation_status, fc.validation_status, oi.validation_status))
            op_warn = ["operating profit not reported; derived as profit before tax + finance costs − other income (EBIT excluding other income)"]
            op_inputs = [pbt, fc, oi, rev]
    out.append(_ratio("operating_profit_margin", "Operating profit margin", "operating profit / revenue × 100", "percent", op, rev, period, Decimal(100),
                      extra_inputs=op_inputs, warnings=rev_w + op_warn, need=("operating profit", "revenue")))

    eq = lookup("total_equity")
    debt, debt_inputs, dw = _debt(lookup)
    out.append(_ratio("debt_to_equity", "Debt-to-equity", "total debt / total equity", "times", debt, eq, period,
                      extra_inputs=debt_inputs + ([eq] if eq else []), warnings=dw, need=("total debt", "total equity")))
    out.append(_ratio("return_on_equity", "Return on equity (closing equity)", "net profit / total equity (closing) × 100", "percent", np_, eq, period, Decimal(100),
                      warnings=np_w + ["uses closing equity of the same period, not average equity"], need=("net profit", "total equity")))
    ta = lookup("total_assets")
    out.append(_ratio("return_on_assets", "Return on assets (closing assets)", "net profit / total assets (closing) × 100", "percent", np_, ta, period, Decimal(100),
                      warnings=np_w + ["uses closing total assets, not average"], need=("net profit", "total assets")))
    out.append(_ratio("current_ratio", "Current ratio", "total current assets / total current liabilities", "times",
                      lookup("total_current_assets"), lookup("total_current_liabilities"), period, need=("current assets", "current liabilities")))
    tl = lookup("total_liabilities")
    out.append(_ratio("liabilities_to_assets", "Liabilities to assets", "total liabilities / total assets × 100", "percent", tl, ta, period, Decimal(100),
                      need=("total liabilities", "total assets")))
    fc = lookup("finance_costs")
    pbt = lookup("profit_before_tax")
    ebit = Input("EBIT (derived)", pbt.value + fc.value, None, pbt.period_label, None, worst(pbt.validation_status, fc.validation_status)) if pbt and fc else None
    out.append(_ratio("interest_coverage", "Interest coverage", "(profit before tax + finance costs) / finance costs", "times", ebit, fc, period,
                      extra_inputs=[i for i in (pbt, fc) if i], need=("profit before tax", "finance costs")))
    exp = lookup("total_expenses")
    out.append(_ratio("expense_ratio", "Expenses to revenue", "total expenses / revenue × 100", "percent", exp, rev, period, Decimal(100),
                      warnings=rev_w, need=("total expenses", "revenue")))
    return out


def growth(key: str, name: str, cur: Input | None, prev: Input | None, cur_period: str | None) -> RatioResult:
    r = RatioResult(calc_key=f"{key}_growth", name=f"{name} growth", formula=f"({name} current − previous) / |previous| × 100",
                    result=None, result_unit="percent", status="insufficient_data", period_label=cur_period)
    used = [i for i in (cur, prev) if i]
    r.inputs = [{"key": i.key, "value": str(i.value), "metric_id": i.metric_id, "period_label": i.period_label, "source": i.source,
                 "validation_status": i.validation_status} for i in used]
    if cur is None:
        r.missing.append("current period value")
    if prev is None:
        r.missing.append("previous period value")
    if r.missing:
        return r
    if any(i.validation_status in BLOCKING for i in used):
        r.status = "invalid_input"
        r.warnings.append("an input failed validation, was rejected or needs review; growth not computed")
        return r
    if (pending := _untrusted(used)):
        r.status = "needs_verification"
        r.warnings.append("not computed: unverified inputs: " + "; ".join(pending))
        return r
    if prev.value == 0:
        r.status = "zero_denominator"
        return r
    r.result = _q((cur.value - prev.value) / abs(prev.value) * 100)
    r.status = "ok"
    if prev.value < 0:
        r.warnings.append("previous value is negative; growth computed against its absolute value")
    return r

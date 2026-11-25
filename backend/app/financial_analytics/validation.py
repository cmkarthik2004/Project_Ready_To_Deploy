"""Automated validation of extracted metrics.

Statuses (automation can only assign the first four; humans assign the last two):
    unvalidated        no applicable check
    validated          took part in at least one passing check and none failed
    failed_validation  took part in a failing check, or failed a sanity check
    needs_review       conflicting duplicate values / suspicious sign / OCR
    verified           confirmed by a user (API: POST /metrics/{id}/verify)
    rejected           rejected by a user

Checks are accounting identities evaluated per (statement basis, column).
A check is only run when *all* of its inputs were extracted; nothing is
filled in. Tolerance allows for rounding of printed figures: 1 printed unit
per addend, or 0.05 % of the larger side, whichever is greater.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from app.financial_analytics.metric_extractor import METRICS, ExtractedMetric

FLOW_STATEMENT = {m.key: m.statement for m in METRICS}


@dataclass(frozen=True)
class IdentityCheck:
    name: str
    lhs: str
    rhs: tuple[str, ...]
    hard: bool = True  # hard: mismatch => failed_validation; soft: mismatch => needs_review
    description: str = ""


CHECKS: list[IdentityCheck] = [
    IdentityCheck("assets_eq_equity_liabilities", "total_assets", ("total_equity_and_liabilities",), True, "Total assets = Total equity and liabilities"),
    IdentityCheck("assets_eq_equity_plus_liabilities", "total_assets", ("total_equity", "total_liabilities"), True, "Total assets = Total equity + Total liabilities"),
    IdentityCheck("assets_eq_current_plus_noncurrent", "total_assets", ("total_current_assets", "total_non_current_assets"), True, "Total assets = Current + Non-current assets"),
    IdentityCheck("liabilities_eq_current_plus_noncurrent", "total_liabilities", ("total_current_liabilities", "total_non_current_liabilities"), True, "Total liabilities = Current + Non-current liabilities"),
    IdentityCheck("equity_components", "total_equity", ("equity_share_capital", "other_equity", "non_controlling_interest"), False, "Total equity = Share capital + Other equity + NCI"),
    IdentityCheck("equity_components_no_nci", "total_equity", ("equity_share_capital", "other_equity"), False, "Total equity = Share capital + Other equity"),
    IdentityCheck("income_eq_revenue_plus_other", "total_income", ("revenue_from_operations", "other_income"), True, "Total income = Revenue from operations + Other income"),
    IdentityCheck("profit_attribution", "net_profit", ("net_profit_attributable_owners", "net_profit_attributable_nci"), True, "Net profit = attributable to owners + to NCI"),
    IdentityCheck("pbt_eq_income_minus_expenses", "profit_before_tax", ("total_income", "-total_expenses"), False, "Profit before tax = Total income - Total expenses (differs if exceptional items exist)"),
    IdentityCheck("pat_eq_pbt_minus_taxes", "profit_after_tax", ("profit_before_tax", "-current_tax", "-deferred_tax"), False, "Profit after tax = PBT - Current tax - Deferred tax"),
    # Soft: the statement may show exceptional items, share of associates or discontinued operations in between.
    IdentityCheck("pbt_eq_pat_plus_tax", "profit_before_tax", ("profit_after_tax", "total_tax_expense"), False, "Profit before tax = Profit after tax + Tax expense"),
    IdentityCheck("pbt_eq_net_profit_plus_tax", "profit_before_tax", ("net_profit", "total_tax_expense"), False, "Profit before tax = Net profit + Tax expense (differs with exceptional items, associates or discontinued operations)"),
    # Soft: only when "cost of revenue/goods sold" is the statement's own definition of the cost line.
    IdentityCheck("gross_profit_eq_revenue_minus_cogs", "gross_profit", ("revenue_from_operations", "-cost_of_revenue"), False, "Gross profit = Revenue from operations - Cost of revenue / goods sold"),
    IdentityCheck("gross_profit_eq_total_revenue_minus_cogs", "gross_profit", ("total_revenue", "-cost_of_revenue"), False, "Gross profit = Total revenue - Cost of revenue / goods sold"),
    # Cash roll-forward: hard (it is how the statement is built).
    IdentityCheck("closing_cash_roll_forward", "closing_cash", ("opening_cash", "net_change_in_cash"), True, "Closing cash = Opening cash + Net change in cash"),
    # Soft: exchange-rate effects and other reconciling items are often shown separately.
    IdentityCheck("net_change_eq_three_activities", "net_change_in_cash", ("net_cash_operating", "net_cash_investing", "net_cash_financing"), False, "Net change in cash = Operating + Investing + Financing cash flows (differs by FX effects)"),
    # Soft: some reports include lease liabilities or current maturities in a printed "total borrowings".
    IdentityCheck("total_borrowings_eq_components", "total_debt", ("borrowings_current", "borrowings_non_current"), False, "Total borrowings = Current borrowings + Non-current borrowings"),
]

NON_NEGATIVE = {"total_assets", "total_current_assets", "total_non_current_assets", "total_equity_and_liabilities",
                "cash_and_cash_equivalents", "inventories", "trade_receivables", "trade_payables", "total_liabilities"}


def _norm_period(label: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (label or "").lower())


def _tolerance(lhs: Decimal, n_terms: int) -> Decimal:
    return max(Decimal(n_terms), abs(lhs) * Decimal("0.0005"))


def validate_metrics(metrics: list[ExtractedMetric]) -> tuple[list[str], list[list[dict]], list[bool], list[dict]]:
    """Return (statuses, notes, is_duplicate, check_results) aligned with `metrics`."""
    n = len(metrics)
    status = ["unvalidated"] * n
    notes: list[list[dict]] = [[] for _ in range(n)]
    dup = [False] * n
    results: list[dict] = []
    passed: set[int] = set()
    failed: set[int] = set()
    review: set[int] = set()

    # --- duplicates / conflicts -------------------------------------------
    seen: dict[tuple, int] = {}
    for i, m in enumerate(metrics):
        if getattr(m, "linked_from", None):  # a cell that only references another cell is a copy of that figure
            dup[i] = True
            notes[i].append({"check": "duplicate", "result": "linked", "detail": f"value is a link to {m.linked_from}; the original figure is used"})
            continue
        if m.metric_key == "line_item":
            continue
        loc = m.location
        # conflicts are only meaningful inside the same table / page region / sheet
        place = (loc.page, loc.half, loc.sheet, loc.table_index if loc.file_format != "pdf" else None)
        k = (m.metric_key, m.basis, _norm_period(m.period_label), m.statement_type, place)
        if k in seen:
            j = seen[k]
            if metrics[j].value == m.value:
                dup[i] = True
                notes[i].append({"check": "duplicate", "result": "duplicate", "detail": f"same value also extracted at {metrics[j].location.describe()}"})
            else:
                review.update({i, j})
                for a, b in ((i, j), (j, i)):
                    notes[a].append({"check": "conflict", "result": "needs_review",
                                     "detail": f"another value {metrics[b].raw_value} for the same metric/period/basis at {metrics[b].location.describe()}"})
        else:
            seen[k] = i

    # --- sanity -------------------------------------------------------------
    for i, m in enumerate(metrics):
        if m.metric_key in NON_NEGATIVE and m.value < 0:
            failed.add(i)
            notes[i].append({"check": "sign", "result": "failed", "detail": f"{m.metric_name} should not be negative"})
        if m.metric_key in ("revenue_from_operations", "total_revenue", "net_sales") and m.value < 0:
            review.add(i)
            notes[i].append({"check": "sign", "result": "needs_review", "detail": "negative revenue"})
        if m.location.ocr:
            review.add(i)
        # A flow item (P&L / cash-flow line) printed under a point-in-time column ("As at 31 March 2025") is a
        # movement inside a balance-sheet note or reconciliation, not the period's reported result.
        if (FLOW_STATEMENT.get(m.metric_key) in ("profit_and_loss", "cash_flow") and m.unit != "per_share"
                and re.search(r"\bas\s+(at|of|on)\b", m.period_label or "", re.I)):
            review.add(i)
            notes[i].append({"check": "period_type", "result": "needs_review",
                             "detail": "income-statement/cash-flow item under a point-in-time column: likely a movement in a note or reconciliation"})

    # --- identities, per (basis, statement column) ---------------------------
    groups: dict[tuple, dict[str, int]] = defaultdict(dict)
    for i, m in enumerate(metrics):
        if dup[i] or m.metric_key == "line_item":
            continue
        groups[(m.basis, _norm_period(m.period_label), m.unit)].setdefault(m.metric_key, i)
    for (basis, period, unit), idx in groups.items():
        for chk in CHECKS:
            keys = [chk.lhs] + [r.lstrip("-") for r in chk.rhs]
            if not all(k in idx for k in keys):
                continue
            if chk.name == "equity_components_no_nci" and "non_controlling_interest" in idx:
                continue
            lhs = metrics[idx[chk.lhs]].value
            rhs = sum((-metrics[idx[r[1:]]].value if r.startswith("-") else metrics[idx[r]].value) for r in chk.rhs)
            diff = lhs - rhs
            ok = abs(diff) <= _tolerance(lhs, len(chk.rhs))
            members = [idx[k] for k in keys]
            res = {"check": chk.name, "description": chk.description, "basis": basis,
                   "period": metrics[idx[chk.lhs]].period_label, "lhs": str(lhs), "rhs": str(rhs), "difference": str(diff),
                   "result": "passed" if ok else ("failed" if chk.hard else "mismatch")}
            results.append(res)
            for mi in members:
                notes[mi].append({"check": chk.name, "result": res["result"], "detail": f"{chk.description}: {lhs} vs {rhs} (diff {diff})"})
                if ok:
                    passed.add(mi)
                elif chk.hard:
                    failed.add(mi)
                else:
                    review.add(mi)

    # --- generic "Total" rows in spreadsheets / Word tables -------------------
    results += _check_line_item_totals(metrics, passed, failed, notes)

    for i in range(n):
        if i in failed:
            status[i] = "failed_validation"
        elif i in review:
            status[i] = "needs_review"
        elif i in passed:
            status[i] = "validated"
    return status, notes, dup, results


def _check_line_item_totals(metrics, passed, failed, notes) -> list[dict]:
    """For tables from spreadsheets / Word: a row labelled 'Total ...' should equal
    the sum of the rows above it in the same column (since the previous total)."""
    results = []
    by_col: dict[tuple, list[int]] = defaultdict(list)
    for i, m in enumerate(metrics):
        loc = m.location
        if loc.file_format in ("xlsx", "xls", "csv", "docx"):
            by_col[(loc.file_format, loc.sheet, loc.table_index, m.period_label)].append(i)
    for key, idxs in by_col.items():
        idxs.sort(key=lambda i: metrics[i].location.row or 0)
        block: list[int] = []
        for i in idxs:
            label = metrics[i].raw_label.strip().lower()
            if re.match(r"^(grand )?total\b", label) and block:
                # The components of a printed total are the rows directly above it; find the shortest contiguous run
                # (≥ 2 rows) ending just above the total that adds up to it. Statement layouts often place unrelated
                # rows (e.g. revenue above "Total expenses") before the components, so no match is not a failure.
                tol = lambda n, s_: max(Decimal("0.01") * n, abs(s_) * Decimal("0.0005"))  # noqa: E731
                match = None
                for k in range(2, len(block) + 1):
                    run = block[-k:]
                    s = sum((metrics[j].value for j in run), Decimal(0))
                    if abs(metrics[i].value - s) <= tol(len(run), s):
                        match = run
                        break
                if match:
                    s = sum((metrics[j].value for j in match), Decimal(0))
                    res = {"check": "column_total", "description": f"'{metrics[i].raw_label}' = sum of the {len(match)} rows above it",
                           "period": metrics[i].period_label, "lhs": str(metrics[i].value), "rhs": str(s), "difference": "0", "result": "passed"}
                    for mi in match + [i]:
                        notes[mi].append({"check": "column_total", "result": "passed", "detail": res["description"]})
                        passed.add(mi)
                else:
                    res = {"check": "column_total", "description": f"'{metrics[i].raw_label}': its components could not be identified among "
                           "the rows above (no contiguous rows add up to it)", "period": metrics[i].period_label, "lhs": str(metrics[i].value),
                           "rhs": None, "difference": None, "result": "not_identified"}
                    notes[i].append({"check": "column_total", "result": "not_identified", "detail": res["description"]})
                results.append(res)
                block = []
            else:
                block.append(i)
    return results

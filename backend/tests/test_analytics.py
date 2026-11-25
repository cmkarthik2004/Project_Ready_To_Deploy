"""Metric mapping, validation and ratio engine. Inputs are SYNTHETIC."""
from decimal import Decimal

from app.document_processing.elements import Cell, Element, Location
from app.financial_analytics.metric_extractor import match_metric, normalise_label, period_sort_key
from app.financial_analytics.ratios import Input, compute_point_ratios, growth, worst
from app.financial_analytics.validation import validate_metrics
from app.financial_analytics.metric_extractor import extract_metrics


def test_label_normalisation_and_group_rules():
    assert normalise_label("a) Owners of the Company") == "owners of the company"
    assert normalise_label("Basic (in C) 31") == "basic"
    assert match_metric("Borrowings", ["Liabilities", "Non-Current Liabilities", "Financial Liabilities"]).key == "borrowings_non_current"
    assert match_metric("Borrowings", ["Non-Current Liabilities", "Current Liabilities", "Financial Liabilities"]).key == "borrowings_current"
    assert match_metric("Non-Controlling Interest", ["Equity"]).key == "non_controlling_interest"
    assert match_metric("b) Non-Controlling Interest", ["Net Profit Attributable to:"]).key == "net_profit_attributable_nci"
    assert match_metric("a) Owners of the Company", ["Other Comprehensive Income Attributable to:"]) is None
    assert match_metric("Some unrelated line", []) is None
    # similarly named items are kept distinct
    assert match_metric("Revenue from Operations", []).key != match_metric("Total Income", []).key
    assert match_metric("Profit After Tax", []).key != match_metric("Profit for the year", []).key


def test_period_sort_key():
    assert period_sort_key("2024-25", None) == 2025
    assert period_sort_key("FY2023", None) == 2023
    assert period_sort_key("Budget", None) is None


def _row(label, values, headers=("2030", "2029"), ctx=("Balance Sheet", "(in millions)")):
    return Element("table_row", label, Location("docx", table_index=0, row=1), label=label,
                   cells=[Cell(v, h, Location("docx", table_index=0, row=1)) for v, h in zip(values, headers)], context=list(ctx))


def test_validation_pass_fail_and_never_verified():
    els = [_row("Total assets", ["100", "90"]), _row("Total equity", ["60", "50"]), _row("Total liabilities", ["40", "45"])]
    ms = extract_metrics(els, "docx", None, None)
    statuses, notes, dup, checks = validate_metrics(ms)
    by = {(c["period"], c["result"]) for c in checks if c["check"] == "assets_eq_equity_plus_liabilities"}
    assert ("2030", "passed") in by and ("2029", "failed") in by  # 50+45 != 90
    assert "verified" not in statuses
    assert statuses[0] == "validated" and statuses[1] == "failed_validation"


def test_negative_assets_fail_sign_check():
    ms = extract_metrics([_row("Total assets", ["(5)", "3"])], "docx", None, None)
    statuses, *_ = validate_metrics(ms)
    assert statuses[0] == "failed_validation"


def _lk(d):
    return lambda k: Input(k, Decimal(d[k]), None, "2030", "test", d.get("_status", "validated")) if k in d else None


def test_ratios_compute_only_with_inputs():
    res = {r.calc_key: r for r in compute_point_ratios(_lk({"revenue_from_operations": "200", "net_profit": "20", "total_equity": "100",
                                                             "borrowings_non_current": "30", "borrowings_current": "20", "total_assets": "400"}), "2030")}
    assert res["net_profit_margin"].status == "ok" and res["net_profit_margin"].result == Decimal("10.0000")
    assert res["debt_to_equity"].result == Decimal("0.5000") and any("lease" in w for w in res["debt_to_equity"].warnings)
    assert res["return_on_assets"].result == Decimal("5.0000")
    assert res["current_ratio"].status == "insufficient_data" and res["current_ratio"].result is None
    assert set(res["current_ratio"].missing) == {"current assets", "current liabilities"}


def test_ratio_zero_denominator_and_invalid_input():
    r = {x.calc_key: x for x in compute_point_ratios(_lk({"net_profit": "5", "revenue_from_operations": "0"}), "p")}
    assert r["net_profit_margin"].status == "zero_denominator"
    r = {x.calc_key: x for x in compute_point_ratios(_lk({"net_profit": "5", "revenue_from_operations": "10", "_status": "failed_validation"}), "p")}
    assert r["net_profit_margin"].status == "invalid_input"


def test_growth_and_worst_status():
    g = growth("net_profit", "Net profit", Input("net_profit", Decimal("110"), None, "2030", None, "validated"),
               Input("net_profit", Decimal("100"), None, "2029", None, "validated"), "2030")
    assert g.result == Decimal("10.0000")
    g = growth("net_profit", "Net profit", Input("net_profit", Decimal("10"), None, "2030", None, "validated"),
               Input("net_profit", Decimal("-20"), None, "2029", None, "validated"), "2030")
    assert g.result == Decimal("150.0000") and g.warnings
    assert worst("validated", "needs_review", "verified") == "needs_review"


def test_needs_review_inputs_block_ratios_and_growth():
    r = {x.calc_key: x for x in compute_point_ratios(_lk({"net_profit": "5", "revenue_from_operations": "10", "_status": "needs_review"}), "p")}
    assert r["net_profit_margin"].status == "invalid_input" and r["net_profit_margin"].result is None
    g = growth("net_profit", "Net profit", Input("net_profit", Decimal("4.1"), None, "2025", None, "needs_review"),
               Input("net_profit", Decimal("10"), None, "2024", None, "validated"), "2025")
    assert g.status == "invalid_input" and g.result is None


def test_flow_item_under_point_in_time_column_needs_review():
    els = [_row("Profit for the year", ["50", "40"], headers=("As at 31 March 2030", "As at 31 March 2029"), ctx=("Notes to accounts",))]
    statuses, notes, *_ = validate_metrics(extract_metrics(els, "docx", None, None))
    assert statuses == ["needs_review", "needs_review"] and any(n["check"] == "period_type" for n in notes[0])

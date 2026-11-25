"""Phase 1–3 tests: workbook structure, CSV profiling, multi-page PDF tables, metric definitions, reconciliation checks.

All inputs here are SYNTHETIC files built inside the tests (clearly artificial numbers) to exercise code paths; accuracy on
genuine reports is covered by test_parsers.py with real documents.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import openpyxl
import pymupdf
from openpyxl.styles import Font

from app.document_processing.elements import Element, Location
from app.document_processing.parsers.csv_parser import CsvParser
from app.document_processing.parsers.excel_parser import XlsxParser, sheet_links
from app.document_processing.parsers.pdf_parser import PdfParser
from app.financial_analytics.metric_extractor import ExtractedMetric, extract_metrics, fiscal_year_of, match_metric
from app.financial_analytics.validation import validate_metrics


def _workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L"
    ws["A1"] = "Statement of profit and loss (SYNTHETIC)"
    ws["B2"] = "Consolidated"
    ws.merge_cells("B2:C2")                       # group header spanning two year columns
    ws.append(["Particulars", "2025", "2024"])   # row 3
    ws.append(["Revenue from operations", 1000, 800])
    ws.append(["Cost of revenue", 600, 500])
    ws.append(["Gross profit", 400, 300])
    ws.append(["Gross margin", 0.4, 0.375])
    ws["B7"].number_format = "0.0%"
    ws["C7"].number_format = "0.0%"
    for c in ("B4", "C4"):
        ws[c].number_format = '"$"#,##0'
    ws.append([])
    ws.append([])
    ws.append(["Segment revenue (SYNTHETIC)"])    # row 10: title of a second table on the same sheet
    ws.append(["Segment", "2025", "2024"])        # row 11
    ws.append(["North", 600, 500])
    ws.append(["South", 400, 300])
    ws.append(["Total", 1000, 800])
    ws["A14"].font = Font(bold=True)
    summary = wb.create_sheet("Summary")
    summary.append(["Metric", "2025"])
    summary.append(["Revenue", 1000])
    summary["C2"] = "='P&L'!B4"                    # cross-sheet reference
    wb.save(path)


def test_xlsx_tables_merged_headers_formats_totals_and_links(tmp_path):
    p = tmp_path / "book.xlsx"
    _workbook(p)
    parsed = XlsxParser().parse(str(p))
    pl = [t for t in parsed.tables if t.location.sheet == "P&L"]
    assert len(pl) == 2, [t.header for t in pl]                        # two tables stacked on one sheet
    assert pl[0].header[1:] == ["Consolidated 2025", "Consolidated 2024"]  # merged group header combined
    rows = {e.label: e for e in parsed.elements if e.kind == "table_row" and e.location.sheet == "P&L"}
    assert [c.text for c in rows["Gross margin"].cells] == ["40%", "37.5%"]  # percent format shown as printed
    assert rows["Total"].is_total and not rows["North"].is_total
    assert rows["North"].location.row == 12                                 # sheet-absolute row in the second table
    assert rows["North"].cells[0].location.cell == "B12"
    st = parsed.file_metadata["sheets"]["P&L"]
    assert st["tables"] == 2 and "B2:C2" in st["merged_ranges"] and st["currency_formats"] == {"USD": 2}
    assert any("formats 2 amount cell(s) as USD" in e.text for e in parsed.elements)
    links = parsed.file_metadata["sheet_links"]
    assert links and links[0]["from_sheet"] == "Summary" and links[0]["to_sheet"] == "P&L"
    assert any("takes values from sheet 'P&L'" in e.text for e in parsed.elements)


def test_sheet_links_handles_quotes_and_ignores_self_refs():
    links = sheet_links({"A": [("B1", "=B2+'It''s'!C3+Other!D4+A!E5")]})
    assert {(x["from_sheet"], x["to_sheet"]) for x in links} == {("A", "It's"), ("A", "Other")}


def test_csv_profile_duplicates_and_missing(tmp_path):
    p = tmp_path / "tx.csv"
    p.write_text("Date;Category;Amount\n2030-01-05;Rent;100\n2030-01-06;Travel;\n2030-01-05;Rent;100\n2030-01-07;Office;50\n",
                 encoding="utf-8")                                         # SYNTHETIC; semicolon-delimited
    parsed = CsvParser().parse(str(p))
    prof = parsed.file_metadata["profile"]
    types = {c["name"]: c["type"] for c in prof["columns"]}
    assert types == {"Date": "date", "Category": "text", "Amount": "number"}
    assert prof["duplicate_rows"] == [{"row": 4, "duplicate_of_row": 2}]
    assert next(c for c in prof["columns"] if c["name"] == "Amount")["missing"] == 1
    assert parsed.file_metadata["delimiter"] == ";"
    assert any("duplicate" in w for w in parsed.warnings) and any("Missing values" in w for w in parsed.warnings)
    assert any(e.text.startswith("[Column profile computed by FinRAG]") for e in parsed.elements)


def _pdf_two_pages(path):
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 60), "Consolidated Balance Sheet (SYNTHETIC)", fontsize=11)
    p1.insert_text((300, 100), "2025", fontsize=10)
    p1.insert_text((400, 100), "2024", fontsize=10)
    for i, (lab, a, b) in enumerate([("Inventories", "120", "110"), ("Trade receivables", "80", "70"), ("Other assets", "40", "30")]):
        y = 130 + i * 20
        p1.insert_text((72, y), lab, fontsize=10)
        p1.insert_text((300, y), a, fontsize=10)
        p1.insert_text((400, y), b, fontsize=10)
    p2 = doc.new_page()                            # continuation: no repeated header
    for i, (lab, a, b) in enumerate([("Total current assets", "240", "210"), ("Total assets", "900", "850")]):
        y = 80 + i * 20
        p2.insert_text((72, y), lab, fontsize=10)
        p2.insert_text((300, y), a, fontsize=10)
        p2.insert_text((400, y), b, fontsize=10)
    doc.save(path)


def test_pdf_table_header_carried_to_continuation_page(tmp_path):
    p = tmp_path / "bs.pdf"
    _pdf_two_pages(p)
    parsed = PdfParser().parse(str(p))
    row = next(e for e in parsed.elements if e.kind == "table_row" and e.label == "Total assets")
    assert row.location.page == 2
    assert [(c.text, c.column_header) for c in row.cells] == [("900", "2025"), ("850", "2024")]
    assert parsed.file_metadata["multi_page_tables"][0] == {"page": 2, "header_from_page": 1, "columns": ["2025", "2024"]}
    m = [x for x in extract_metrics(parsed.elements, "pdf", None, None) if x.metric_key == "total_assets"]
    assert {(x.period_label, str(x.value)) for x in m} == {("2025", "900"), ("2024", "850")}


def test_pdf_no_carry_when_columns_do_not_align(tmp_path):
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((300, 100), "2025", fontsize=10)
    p1.insert_text((400, 100), "2024", fontsize=10)
    for i in range(3):
        p1.insert_text((72, 130 + i * 20), f"Item {i}", fontsize=10)
        p1.insert_text((300, 130 + i * 20), "10", fontsize=10)
        p1.insert_text((400, 130 + i * 20), "9", fontsize=10)
    p2 = doc.new_page()
    p2.insert_text((72, 80), "Unrelated count", fontsize=10)
    p2.insert_text((200, 80), "7", fontsize=10)                    # different x position: must not inherit a period
    doc.save(tmp_path / "x.pdf")
    parsed = PdfParser().parse(str(tmp_path / "x.pdf"))
    row = next(e for e in parsed.elements if e.label == "Unrelated count")
    assert row.cells[0].column_header is None and "multi_page_tables" not in parsed.file_metadata


def test_distinct_metric_definitions():
    assert match_metric("EBIT", []).key == "ebit"
    assert match_metric("Operating profit", []).key == "operating_profit"
    assert match_metric("Cash generated from operations", []).key == "cash_generated_from_operations"
    assert match_metric("Net cash from operating activities", []).key == "net_cash_operating"
    assert match_metric("Cash and cash equivalents at the end of the year", []).key == "closing_cash"
    assert match_metric("Cash and cash equivalents at the beginning of the year", []).key == "opening_cash"
    assert match_metric("Cash and cash equivalents", []).key == "cash_and_cash_equivalents"
    assert match_metric("Net increase/(decrease) in cash and cash equivalents", []).key == "net_change_in_cash"
    assert match_metric("Gross profit", []).key == "gross_profit"


def _m(key, value, period="2030", basis=None):
    return ExtractedMetric(key, key, key, str(value), Decimal(str(value)), "million", 1_000_000, None, period, None,
                           "cash_flow", basis, Location(file_format="xlsx", sheet="S", cell="B1"), "", "test", 0.9)


def test_cash_roll_forward_and_soft_checks():
    ok = [_m("opening_cash", 100), _m("net_change_in_cash", 20), _m("closing_cash", 120)]
    st, _, _, res = validate_metrics(ok)
    assert st == ["validated"] * 3 and res[0]["check"] == "closing_cash_roll_forward"
    bad = [_m("opening_cash", 100), _m("net_change_in_cash", 20), _m("closing_cash", 125)]   # SYNTHETIC inconsistency
    st, notes, _, res = validate_metrics(bad)
    assert st == ["failed_validation"] * 3 and res[0]["result"] == "failed"
    soft = [_m("net_change_in_cash", 200), _m("net_cash_operating", 500), _m("net_cash_investing", -400), _m("net_cash_financing", 70)]
    st, _, _, res = validate_metrics(soft)                          # differs by 30 (e.g. FX effects): review, not failure
    assert st == ["needs_review"] * 4 and res[0]["result"] == "mismatch"
    gp = [_m("revenue_from_operations", 1000), _m("cost_of_revenue", 600), _m("gross_profit", 400)]
    assert validate_metrics(gp)[0] == ["validated"] * 3
    tax = [_m("profit_after_tax", 75), _m("total_tax_expense", 25), _m("profit_before_tax", 100)]
    assert validate_metrics(tax)[0] == ["validated"] * 3


def test_inferred_mapping_and_fiscal_year():
    loc = Location(file_format="pdf", page=1)
    from app.document_processing.elements import Cell
    el = Element("table_row", "Borrowings | 2025: 50", loc, label="Borrowings",
                 cells=[Cell("50", "As at 31 March 2025", loc)], context=["Balance sheet", "group: Current liabilities"])
    m = extract_metrics([el], "pdf", None, None)[0]
    assert m.metric_key == "borrowings_current" and m.value_origin == "inferred_mapping"
    assert any("inferred mapping" in n for n in m.notes)
    assert fiscal_year_of("2024-25", None) == 2025
    assert fiscal_year_of("As at 31 March 2025", dt.date(2025, 3, 31)) == 2025
    assert fiscal_year_of("FY2024", None) == 2024
    assert fiscal_year_of("Particulars", None) is None


def test_csv_with_title_line_keeps_all_rows(tmp_path):
    """Regression: a title/unit line with fewer fields used to make pandas skip every following row (data loss)."""
    p = tmp_path / "titled.csv"
    p.write_text("Amounts in million\nParticulars,2030\nRevenue from operations,500\nTotal assets,900\n", encoding="utf-8")  # SYNTHETIC
    parsed = CsvParser().parse(str(p))
    ms = {m.metric_key: m for m in extract_metrics(parsed.elements, "csv", None, None)}
    assert str(ms["revenue_from_operations"].value) == "500" and ms["revenue_from_operations"].location.row == 3
    assert ms["total_assets"].unit == "million" and ms["total_assets"].period_label == "2030"


def test_basis_inherited_only_when_document_is_unambiguous():
    from app.financial_analytics.metric_extractor import inherit_basis
    a, b = _m("total_assets", 10, basis="consolidated"), _m("borrowings_current", 2)
    assert inherit_basis([a, b], "") == "consolidated" and b.basis == "consolidated" and "inherited" in b.notes[-1]
    c, d, e = _m("total_assets", 10, basis="consolidated"), _m("total_assets", 8, basis="standalone"), _m("borrowings_current", 2)
    assert inherit_basis([c, d, e], "") is None and e.basis is None                    # both bases present: no guess
    f = _m("borrowings_current", 2)
    assert inherit_basis([f], "Notes to the consolidated financial statements") == "consolidated"
    g = _m("borrowings_current", 2)
    assert inherit_basis([g], "Consolidated and standalone statements") is None and g.basis is None
    h = _m("borrowings_current", 2)
    assert inherit_basis([h], "no basis words") is None and h.basis is None

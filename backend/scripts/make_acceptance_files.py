"""Generate the SYNTHETIC acceptance-test files (see docs/ACCEPTANCE_TESTS.md).

Every file states inside it that it is synthetic test data for an invented company; the numbers are artificial but
internally consistent (or deliberately inconsistent where a test needs a reconciliation failure), so extraction can be
checked against a known ground truth. Genuine documents are used separately for real-world accuracy.

    python scripts/make_acceptance_files.py OUT_DIR
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import docx
import openpyxl
import pymupdf

NOTE = "SYNTHETIC TEST DATA — invented company 'Example Manufacturing Ltd'; not real financial information."
# Ground truth (USD million) for Example Manufacturing Ltd, consolidated
PL = {"FY2029": dict(rev=1000, cogs=600, emp=120, dep=40, fin=20, ebitda=280, pbt=220, tax=55, pat=165),
      "FY2030": dict(rev=1150, cogs=680, emp=130, dep=45, fin=22, ebitda=340, pbt=273, tax=68, pat=205),
      "FY2031": dict(rev=1265, cogs=760, emp=150, dep=50, fin=25, ebitda=355, pbt=280, tax=70, pat=210)}
BS = {"FY2030": dict(ca=700, nca=1300, cl=450, ncl=650, eq=900, bc=120, bnc=380, cash=150),
      "FY2031": dict(ca=820, nca=1430, cl=500, ncl=700, eq=1050, bc=100, bnc=420, cash=190)}
CF = {"FY2030": dict(open=110, op=260, inv=-150, fin=-70, close=150),
      "FY2031": dict(open=150, op=300, inv=-180, fin=-80, close=190)}


def multisheet_xlsx(out: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "P&L"
    ws.append(["Example Manufacturing Ltd — Consolidated Statement of Profit and Loss"])
    ws.append([NOTE])
    ws.append(["Amounts in USD million"])
    ws.append(["Particulars"] + list(PL))
    rows = [("Revenue from operations", "rev"), ("Cost of goods sold", "cogs")]
    for label, k in rows:
        ws.append([label] + [PL[y][k] for y in PL])
    r = ws.max_row + 1
    ws.append(["Gross profit"] + [f"={c}5-{c}6" for c in "BCD"])                 # formula, cached by LibreOffice
    ws.append(["Employee benefits expense"] + [PL[y]["emp"] for y in PL])
    ws.append(["EBITDA"] + [PL[y]["ebitda"] for y in PL])
    ws.append(["Depreciation and amortisation"] + [PL[y]["dep"] for y in PL])
    ws.append(["Finance costs"] + [PL[y]["fin"] for y in PL])
    ws.append(["Profit before tax"] + [PL[y]["pbt"] for y in PL])
    ws.append(["Tax expense"] + [PL[y]["tax"] for y in PL])
    ws.append(["Profit for the year"] + [f"={c}{r + 5}-{c}{r + 6}" for c in "BCD"])
    for row in ws.iter_rows(min_row=5, max_row=ws.max_row, min_col=2, max_col=4):
        for cell in row:
            cell.number_format = '"$"#,##0'
    b = wb.create_sheet("Balance Sheet")
    b.append(["Example Manufacturing Ltd — Consolidated Balance Sheet"])
    b.append([NOTE])
    b.append(["Amounts in USD million"])
    b.append(["Particulars"] + [f"As at 31 March {y[2:]}" for y in BS])
    for label, k in (("Total current assets", "ca"), ("Total non-current assets", "nca")):
        b.append([label] + [BS[y][k] for y in BS])
    b.append(["Total assets", "=B5+B6", "=C5+C6"])
    b.append(["Total current liabilities"] + [BS[y]["cl"] for y in BS])
    b.append(["Total non-current liabilities"] + [BS[y]["ncl"] for y in BS])
    b.append(["Total liabilities", "=B8+B9", "=C8+C9"])
    b.append(["Total equity"] + [BS[y]["eq"] for y in BS])
    b.append([])
    b.append(["Borrowings"])
    b.append(["Particulars"] + [f"As at 31 March {y[2:]}" for y in BS])
    b.append(["Short-term borrowings"] + [BS[y]["bc"] for y in BS])
    b.append(["Long-term borrowings"] + [BS[y]["bnc"] for y in BS])
    b.append(["Cash and cash equivalents"] + [BS[y]["cash"] for y in BS])
    c = wb.create_sheet("Cash Flow")
    c.append(["Example Manufacturing Ltd — Consolidated Cash Flow Statement"])
    c.append([NOTE])
    c.append(["Amounts in USD million"])
    c.append(["Particulars"] + list(CF))
    for label, k in (("Cash and cash equivalents at the beginning of the year", "open"), ("Net cash from operating activities", "op"),
                     ("Net cash used in investing activities", "inv"), ("Net cash used in financing activities", "fin")):
        c.append([label] + [CF[y][k] for y in CF])
    c.append(["Net increase in cash and cash equivalents", "=SUM(B6:B8)", "=SUM(C6:C8)"])
    c.append(["Cash and cash equivalents at the end of the year", "=B5+B9", "=C5+C9"])
    s = wb.create_sheet("Summary")
    s.append(["Summary (links to other sheets)"])
    s.append(["Metric", "FY2031"])
    s.append(["Revenue", "='P&L'!D5"])
    s.append(["Total assets", "='Balance Sheet'!C7"])
    tmp = Path(tempfile.mkdtemp())
    raw = tmp / out.name
    wb.save(raw)
    # Recalculate with LibreOffice so formula cells carry cached values, as a file saved by Excel would.
    subprocess.run(["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(tmp / "calc"), str(raw)],
                   check=True, capture_output=True, timeout=180)
    shutil.copy(tmp / "calc" / out.name, out)


def transactions_csv(out: Path) -> None:
    lines = [["Date", "Category", "Description", "Amount (EUR)"],
             ["2031-01-05", "Rent", "Office rent January", "1.200,00"], ["2031-01-09", "Travel", "Client visit", "350,50"],
             ["2031-01-05", "Rent", "Office rent January", "1.200,00"],                        # exact duplicate row
             ["2031-01-15", "Software", "Licences", ""],                                         # missing amount
             ["2031-02-05", "Rent", "Office rent February", "1.200,00"], ["2031-02-11", "Travel", "Conference", "780,00"],
             ["2031-02-20", "Software", "Cloud hosting", "410,25"]]
    text = f"# {NOTE}\n" + "\n".join(";".join(r) for r in lines) + "\n"
    out.write_bytes(text.encode("cp1252"))                                                   # Windows-1252, ';' delimited


def notes_docx(out: Path) -> None:
    d = docx.Document()
    d.add_heading("Example Manufacturing Ltd — Notes to the consolidated financial statements FY2031", 1)
    d.add_paragraph(NOTE)
    d.add_heading("Note 12: Revenue", 2)
    d.add_paragraph("Revenue from operations increased in FY2031 mainly because of two new long-term supply contracts signed in "
                    "the industrial segment; prices were broadly unchanged.")
    d.add_heading("Note 18: Borrowings", 2)
    d.add_paragraph("Amounts in USD million. Long-term borrowings were refinanced in FY2031 at a lower fixed rate.")
    t = d.add_table(rows=1, cols=3)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text, t.rows[0].cells[2].text = "Particulars", "FY2031", "FY2030"
    for label, a, b in (("Short-term borrowings", "100", "120"), ("Long-term borrowings", "420", "380"), ("Total borrowings", "520", "500")):
        cells = t.add_row().cells
        cells[0].text, cells[1].text, cells[2].text = label, a, b
    d.add_heading("Note 25: Risks", 2)
    d.add_paragraph("The company depends on two customers for about 40 percent of revenue; the loss of either would materially "
                    "reduce revenue.")
    d.save(out)


def multiyear_csv(out: Path) -> None:
    rows = ["Particulars,FY2027,FY2028,FY2029,FY2030,FY2031", "Revenue from operations,4200,4650,5100,5480,6010",
            "Total expenses,3700,4050,4420,4800,5200", "Profit for the year,380,450,510,520,610", "Total assets,8000,8600,9300,9900,10800"]
    out.write_text(f"Synthetic Retail Co — five-year summary ({NOTE.replace('Example Manufacturing Ltd', 'Synthetic Retail Co')})\n"
                   "Amounts in INR crore\n" + "\n".join(rows) + "\n", encoding="utf-8")


def inconsistent_xlsx(out: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Balance Sheet"
    ws.append(["Inconsistent Holdings — Balance Sheet (SYNTHETIC: deliberately inconsistent figures for testing)"])
    ws.append(["Amounts in USD thousand"])
    ws.append(["Particulars", "As at 31 March 2031"])
    ws.append(["Total assets", 5000])
    ws.append(["Total liabilities", 2100])
    ws.append(["Total equity", 2600])                      # 2100 + 2600 = 4700 ≠ 5000 → reconciliation failure
    cf = wb.create_sheet("Cash Flow")
    cf.append(["Cash flow (SYNTHETIC)"])
    cf.append(["Amounts in USD thousand"])
    cf.append(["Particulars", "FY2031"])
    cf.append(["Cash and cash equivalents at the beginning of the year", 400])
    cf.append(["Net increase in cash and cash equivalents", 150])
    cf.append(["Cash and cash equivalents at the end of the year", 600])   # 400 + 150 ≠ 600 → failure
    wb.save(out)


def scanned_pdf(out: Path) -> None:
    """Image-only PDF of a small statement: no text layer, so OCR is required."""
    src = pymupdf.open()
    p = src.new_page()
    p.insert_text((60, 60), "Scanned Example Ltd - Statement of Profit and Loss (SYNTHETIC)", fontsize=12)
    p.insert_text((60, 80), "Amounts in USD million", fontsize=11)
    p.insert_text((330, 110), "FY2031", fontsize=11)
    p.insert_text((430, 110), "FY2030", fontsize=11)
    for i, (lab, a, b) in enumerate((("Revenue from operations", "880", "800"), ("Total expenses", "700", "650"),
                                     ("Profit before tax", "180", "150"), ("Profit for the year", "135", "112"))):
        y = 140 + i * 24
        p.insert_text((60, y), lab, fontsize=11)
        p.insert_text((330, y), a, fontsize=11)
        p.insert_text((430, y), b, fontsize=11)
    pix = p.get_pixmap(dpi=200)
    img = pymupdf.open()
    page = img.new_page(width=p.rect.width, height=p.rect.height)
    page.insert_image(page.rect, pixmap=pix)
    img.save(out)


TRUTH = {"pl": PL, "bs": BS, "cf": CF}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "acceptance_files")
    out.mkdir(parents=True, exist_ok=True)
    multisheet_xlsx(out / "synthetic_multisheet_usd_million.xlsx")
    transactions_csv(out / "synthetic_transactions_cp1252.csv")
    notes_docx(out / "synthetic_notes_borrowings.docx")
    multiyear_csv(out / "synthetic_five_year_inr_crore.csv")
    inconsistent_xlsx(out / "synthetic_inconsistent_usd_thousand.xlsx")
    scanned_pdf(out / "synthetic_scanned_statement.pdf")
    (out / "ground_truth.json").write_text(json.dumps(TRUTH, indent=1))
    print("\n".join(sorted(p.name for p in out.iterdir())))

"""Build DOCX / XLSX / XLS / CSV test inputs by TRANSCRIBING rows of a real,
publicly available financial-statement PDF that the tester supplies.

No numbers are invented: every row is copied verbatim (label + printed values
+ column headers) from the PDF page(s) given on the command line, using
FinRAG's own PDF parser. Each output file carries a provenance note with the
source filename, its SHA-256 and the PDF page number.

Usage:
    python tests/fixtures/build_derived_fixtures.py <source.pdf> <page> [<page> ...] --out <dir>

These files are test inputs only. They are never loaded into a production
database by FinRAG; the test-suite uploads them into an isolated test database.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import docx
import openpyxl
import pymupdf
import xlwt

from app.document_processing.parsers.pdf_parser import PdfParser


def extract_rows(pdf: str, page: int) -> tuple[list[str], list[list[str]], str | None, list[str]]:
    src = pymupdf.open(pdf)
    one = pymupdf.open()
    one.insert_pdf(src, from_page=page - 1, to_page=page - 1)
    tmp = Path(pdf).with_suffix(f".p{page}.tmp.pdf")
    one.save(tmp)
    parsed = PdfParser().parse(str(tmp))
    tmp.unlink()
    rows, headers, title, context = [], [], None, []
    for t in parsed.tables:
        if not headers:
            headers = t.header[1:]
            title = t.title
        if t.header[1:] == headers:
            rows += [r for r in t.rows if len(r) == len(headers) + 1]
    for e in parsed.elements:
        if e.kind == "heading" and len(context) < 3:
            context.append(e.text)
    return headers, rows, title, context


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("pages", nargs="+", type=int)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(Path(a.pdf).read_bytes()).hexdigest()
    for page in a.pages:
        headers, rows, title, context = extract_rows(a.pdf, page)
        if not rows:
            print(f"page {page}: no table rows found, skipped")
            continue
        prov = f"Transcribed from {Path(a.pdf).name} (sha256 {sha[:16]}…), PDF page {page}, by FinRAG test fixture builder."
        stem = out / f"derived_p{page}"
        heading = " ".join(context[:2]) or (title or "Statement")
        # XLSX: title lines, header row, data rows (values kept as printed text -> parsed by FinRAG)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Statement"
        for c in context[:3]:
            ws.append([c])
        ws.append(["Particulars"] + headers)
        for r in rows:
            ws.append(r)
        ws2 = wb.create_sheet("Provenance")
        ws2.append([prov])
        wb.save(f"{stem}.xlsx")
        # XLS
        x = xlwt.Workbook()
        sh = x.add_sheet("Statement")
        ri = 0
        for c in context[:3]:
            sh.write(ri, 0, c)
            ri += 1
        for ci, h in enumerate(["Particulars"] + headers):
            sh.write(ri, ci, h)
        for r in rows:
            ri += 1
            for ci, v in enumerate(r):
                sh.write(ri, ci, v)
        x.add_sheet("Provenance").write(0, 0, prov)
        x.save(f"{stem}.xls")
        # CSV
        with open(f"{stem}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Particulars"] + headers)
            w.writerows(rows)
        # DOCX
        d = docx.Document()
        d.add_heading(heading, level=1)
        d.add_paragraph(prov)
        for c in context[1:3]:
            d.add_paragraph(c)
        t = d.add_table(rows=1, cols=len(headers) + 1)
        for ci, h in enumerate(["Particulars"] + headers):
            t.rows[0].cells[ci].text = h
        for r in rows:
            cells = t.add_row().cells
            for ci, v in enumerate(r):
                cells[ci].text = v
        d.save(f"{stem}.docx")
        (out / f"derived_p{page}.PROVENANCE.txt").write_text(prov + "\n")
        print(f"page {page}: {len(rows)} rows -> {stem}.{{xlsx,xls,csv,docx}}")


if __name__ == "__main__":
    main()

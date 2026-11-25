"""Excel parsers: .xlsx (openpyxl, formulas + cached values) and legacy .xls (pandas + xlrd).

Every value keeps its sheet name and A1 cell reference; formula text is kept next to the value. Formula cells without
a cached value (file never recalculated in Excel) are reported and left empty — FinRAG never evaluates or guesses them.

Workbook structure that is preserved (xlsx):
* every worksheet, hidden ones included (reported);
* several tables stacked on one sheet (split at blank rows followed by a new header — `tabular.split_blocks`);
* merged header cells: the text of a merged range is repeated across the columns it spans (group headers such as
  "Consolidated" over two year columns), and two-row headers are combined;
* cell number formats: percentages are shown as printed (0.125 formatted as % → "12.5%"); currency symbols in number
  formats are reported per sheet; dates stay dates;
* totals/subtotals (label "Total …" or a SUM formula) are flagged;
* formulas that reference other sheets are recorded as workbook relationships (sheet A takes values from sheet B).
"""
from __future__ import annotations

import os
import re
from collections import Counter
from decimal import Decimal

import openpyxl
import pandas as pd

from app.core.config import get_settings
from app.document_processing.elements import Element, Location, ParsedDocument
from app.document_processing.parsers.tabular import GridCell, col_letter, make_cell, sheet_to_elements

FULL_MODE_MAX_BYTES = 15 * 1024 * 1024  # above this, read-only streaming (merges/formats unavailable, reported)
SHEET_REF_RE = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_][\w.]*))!\$?[A-Z]{1,3}\$?\d+")
CURRENCY_FMT = [("USD", re.compile(r'\[\$\$|"\$"|^\$|\$#')), ("EUR", re.compile(r"€")), ("GBP", re.compile(r"£")),
                ("INR", re.compile(r"₹|\[\$INR")), ("JPY", re.compile(r"¥")), ("CHF", re.compile(r"\[\$CHF"))]


def _fmt_decimal(d: Decimal) -> str:
    t = format(d.normalize(), "f")
    return t.rstrip("0").rstrip(".") if "." in t else t


def sheet_links(formulas: dict[str, list[tuple[str, str]]]) -> list[dict]:
    """{sheet: [(cell, formula)]} -> [{from_sheet, to_sheet, references, example}] (self-references ignored)."""
    out: Counter = Counter()
    example: dict = {}
    for sheet, items in formulas.items():
        for cell, f in items:
            for q, plain in SHEET_REF_RE.findall(f):
                target = (q.replace("''", "'") if q else plain)
                if target and target != sheet:
                    out[(sheet, target)] += 1
                    example.setdefault((sheet, target), f"{cell}: {f}")
    return [{"from_sheet": a, "to_sheet": b, "references": n, "example": example[(a, b)]} for (a, b), n in out.most_common()]


class XlsxParser:
    def parse(self, path: str) -> ParsedDocument:
        s = get_settings()
        full = os.path.getsize(path) <= FULL_MODE_MAX_BYTES
        # Two passes: formulas (data_only=False) and cached values (data_only=True).
        wb_f = openpyxl.load_workbook(path, read_only=not full, data_only=False)
        wb_v = openpyxl.load_workbook(path, read_only=not full, data_only=True)
        props = wb_f.properties
        meta = {k: str(v) for k, v in {"title": props.title, "creator": props.creator, "created": props.created,
                                         "modified": props.modified, "company": getattr(props, "company", None)}.items() if v}
        parsed = ParsedDocument(file_format="xlsx", elements=[], sheet_names=list(wb_v.sheetnames), file_metadata=meta)
        if not full:
            parsed.warnings.append("Large workbook: read in streaming mode; merged cells and number formats were not read.")
        total_cells = 0
        table_id = 0
        formulas: dict[str, list[tuple[str, str]]] = {}
        structure: dict[str, dict] = {}
        for name in wb_v.sheetnames:
            ws_v, ws_f = wb_v[name], wb_f[name]
            if getattr(ws_v, "sheet_state", "visible") != "visible":
                parsed.warnings.append(f"Sheet '{name}' is hidden; it was still read.")
            grid: list[list[GridCell]] = []
            uncached = 0
            currencies: Counter = Counter()
            pct = 0
            formulas[name] = []
            for row_v, row_f in zip(ws_v.iter_rows(), ws_f.iter_rows()):
                out = []
                for cv, cf in zip(row_v, row_f):
                    coord = getattr(cv, "coordinate", None)
                    formula = cf.value if isinstance(cf.value, str) and cf.value.startswith("=") else None
                    if formula:
                        formulas[name].append((coord, formula))
                        if cv.value is None:
                            uncached += 1
                    cell = make_cell(cv.value, coord, formula)
                    fmt = getattr(cv, "number_format", None) or ""
                    if cell.value is not None and isinstance(cv.value, (int, float)) and "%" in fmt:
                        # displayed as a percentage: keep what the reader sees (0.125 → "12.5%")
                        shown = cell.value * 100
                        cell = GridCell(_fmt_decimal(shown) + "%", shown, coord, formula)
                        pct += 1
                    elif cell.value is not None and fmt:
                        for code, rx in CURRENCY_FMT:
                            if rx.search(fmt):
                                currencies[code] += 1
                                break
                    out.append(cell)
                grid.append(out)
                total_cells += len(out)
                if total_cells > s.max_sheet_cells:
                    raise ValueError(f"Workbook exceeds {s.max_sheet_cells} cells.")
            merged = []
            if full:
                for mr in ws_v.merged_cells.ranges:
                    merged.append(str(mr))
                    r0, c0 = mr.min_row - 1, mr.min_col - 1
                    if mr.min_col > 1 and r0 < len(grid) and c0 < len(grid[r0]) and grid[r0][c0].text and grid[r0][c0].value is None:
                        # repeat a merged group header (not a title spanning from column A) across its columns
                        for cc in range(c0 + 1, min(mr.max_col, len(grid[r0]))):
                            if not grid[r0][cc].text:
                                grid[r0][cc] = GridCell(grid[r0][c0].text, None, grid[r0][cc].coord)
            if uncached:
                parsed.warnings.append(
                    f"Sheet '{name}': {uncached} formula cell(s) have no cached value (file not recalculated in Excel); "
                    "those cells were not evaluated and are treated as empty."
                )
            title_hint = None
            if currencies:
                code, n = currencies.most_common(1)[0]
                title_hint = f"Currency (from cell number formats): {code}"
                parsed.elements.append(Element("text", f"Sheet '{name}' formats {n} amount cell(s) as {code}.",
                                               Location(file_format="xlsx", sheet=name), context=[title_hint]))
            els, tables, notes, table_id = sheet_to_elements(grid, file_format="xlsx", sheet=name, first_table_id=table_id,
                                                             title_hint=title_hint)
            parsed.elements += els
            parsed.tables += tables
            parsed.warnings += [f"Sheet '{name}': {n}" for n in notes]
            structure[name] = {"rows": len(grid), "tables": len(tables), "merged_ranges": merged[:50],
                               "formula_cells": len(formulas[name]), "percent_cells": pct,
                               "currency_formats": dict(currencies), "total_rows": sum(1 for e in els if e.is_total)}
        links = sheet_links(formulas)
        parsed.file_metadata["sheets"] = structure
        parsed.file_metadata["sheet_links"] = links
        for ln in links:
            parsed.elements.append(Element(
                "text", f"Workbook structure: sheet '{ln['from_sheet']}' takes values from sheet '{ln['to_sheet']}' "
                        f"({ln['references']} formula reference(s), e.g. {ln['example']}).",
                Location(file_format="xlsx", sheet=ln["from_sheet"]), context=["workbook structure"]))
        wb_f.close()
        wb_v.close()
        return parsed


class XlsParser:
    """Legacy .xls (BIFF). Formulas are not available through xlrd; values are."""

    def parse(self, path: str) -> ParsedDocument:
        sheets = pd.read_excel(path, sheet_name=None, header=None, engine="xlrd", dtype=object)
        parsed = ParsedDocument(file_format="xls", elements=[], sheet_names=list(sheets.keys()))
        parsed.warnings.append("Legacy .xls format: formulas cannot be read, only stored values.")
        table_id = 0
        for name, df in sheets.items():
            grid = [[make_cell(None if pd.isna(v) else v, f"{col_letter(ci)}{ri + 1}") for ci, v in enumerate(row)]
                    for ri, row in enumerate(df.itertuples(index=False, name=None))]
            els, tables, notes, table_id = sheet_to_elements(grid, file_format="xls", sheet=str(name), first_table_id=table_id)
            parsed.elements += els
            parsed.tables += tables
            parsed.warnings += [f"Sheet '{name}': {n}" for n in notes]
        return parsed

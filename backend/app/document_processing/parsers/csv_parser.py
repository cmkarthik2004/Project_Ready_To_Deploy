"""CSV parser (pandas). Encoding and delimiter are detected; every cell is read as a
string so the printed value is preserved; rows are cited by row number (header = row 1).

A column profile is produced (inferred type: number / date / text / empty, missing values, distinct values) together
with exact duplicate data rows; both are stored in the document metadata, reported as warnings when relevant, and added
as a searchable summary so questions about data quality can be answered with row references."""
from __future__ import annotations

import csv
import io
import re

import pandas as pd

from app.document_processing.elements import Element, Location, ParsedDocument
from app.document_processing.parsers.tabular import GridCell, _find_header, make_cell, sheet_to_elements


DELIMS = [",", ";", "\t", "|"]
EU_NUM = re.compile(r"^-?\(?\d{1,3}(?:\.\d{3})*,\d{1,4}\)?$|^-?\(?\d+,\d{1,4}\)?$")
DOT_DEC = re.compile(r"^-?\(?\d{1,3}(?:,\d{3})*\.\d{1,4}\)?$|^-?\(?\d+\.\d{1,2}\)?$")


def detect_delimiter(text: str) -> str:
    """Pick the delimiter used most consistently across data lines (comment lines starting with '#' and blank lines are
    ignored). Falls back to csv.Sniffer, then ','."""
    lines = [ln for ln in text.splitlines()[:300] if ln.strip() and not ln.lstrip().startswith("#")]
    best, best_score = None, 0.0
    for d in DELIMS:
        counts = [next(csv.reader([ln], delimiter=d)).__len__() - 1 for ln in lines]
        multi = [c for c in counts if c > 0]
        if not multi:
            continue
        mode = max(set(multi), key=multi.count)
        score = multi.count(mode) / len(lines) * (1 + mode / 100)
        if score > best_score:
            best, best_score = d, score
    if best:
        return best
    try:
        return csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def uses_decimal_comma(rows: list[list[str]]) -> bool:
    """True when amounts are written with a decimal comma (1.200,50) and none with a decimal point."""
    cells = [c.strip() for r in rows for c in r if c.strip()]
    eu = sum(1 for c in cells if EU_NUM.match(c) and "," in c)
    dot = sum(1 for c in cells if DOT_DEC.match(c) and "." in c and "," not in c)
    return eu >= 2 and dot == 0


def _cell(v: str, comma_decimal: bool) -> GridCell:
    if not v:
        return make_cell(None, None)
    if comma_decimal and EU_NUM.match(v):
        c = make_cell(v.replace(".", "").replace(",", "."), None)
        return GridCell(v, c.value, None)  # keep the printed text, parse the value correctly
    return make_cell(v, None)


def _is_date(text: str) -> bool:
    if not text or len(text) < 6 or not any(ch.isdigit() for ch in text):
        return False
    t = text.strip()
    if t.replace(",", "").replace(".", "").isdigit():
        return len(t) == 8 and t.isdigit()  # plain numbers are amounts; only YYYYMMDD counts as a date
    try:
        pd.to_datetime(t, dayfirst=False)
        return True
    except (ValueError, OverflowError):
        return False


def profile(grid: list[list[GridCell]]) -> tuple[dict, list[str]]:
    """Column profile + duplicate rows. Row numbers are 1-based file rows."""
    h = _find_header(grid)
    start = (h + 1) if h is not None else 0
    width = max((len(r) for r in grid), default=0)
    names = [(grid[h][i].text if h is not None and i < len(grid[h]) else "") or f"column {i + 1}" for i in range(width)]
    rows = grid[start:]
    cols = []
    for i in range(width):
        vals = [r[i].text for r in rows if i < len(r)]
        filled = [v for v in vals if v]
        nums = sum(1 for r in rows if i < len(r) and r[i].value is not None)
        dates = sum(1 for v in filled[:500] if _is_date(v))
        if not filled:
            kind = "empty"
        elif nums >= 0.8 * len(filled):
            kind = "number"
        elif dates >= 0.8 * min(len(filled), 500):
            kind = "date"
        else:
            kind = "text"
        cols.append({"name": names[i], "type": kind, "missing": len(vals) - len(filled), "distinct": len(set(filled))})
    seen: dict[tuple, int] = {}
    dups: list[dict] = []
    for k, r in enumerate(rows):
        key = tuple(c.text for c in r)
        if not any(key):
            continue
        rownum = start + k + 1
        if key in seen:
            dups.append({"row": rownum, "duplicate_of_row": seen[key]})
        else:
            seen[key] = rownum
    warnings = []
    if dups:
        warnings.append(f"{len(dups)} exact duplicate data row(s), e.g. row {dups[0]['row']} repeats row {dups[0]['duplicate_of_row']}; "
                        "duplicates are kept as printed and included in computed totals.")
    gaps = [c for c in cols if c["type"] != "empty" and c["missing"]]
    if gaps:
        warnings.append("Missing values: " + ", ".join(f"'{c['name']}' {c['missing']}" for c in gaps[:8]) + " (left empty, not treated as zero).")
    return {"header_row": (h + 1) if h is not None else None, "data_rows": len(rows), "columns": cols,
            "duplicate_rows": dups[:200], "duplicate_row_count": len(dups)}, warnings


class CsvParser:
    def parse(self, path: str) -> ParsedDocument:
        raw = open(path, "rb").read()
        text = None
        used = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                used = enc
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("CSV file could not be decoded as text.")
        sep = detect_delimiter(text)
        # Read every row as strings with the csv module: rows may have different lengths (title or unit lines above
        # the table are common). pandas fixes the column count from the first line and would silently drop the rest.
        raw_rows = list(csv.reader(io.StringIO(text), delimiter=sep))
        raw_rows = [[sep.join(r)] if r and r[0].lstrip().startswith("#") else r for r in raw_rows]  # comment lines stay one cell
        width = max((len(r) for r in raw_rows), default=0)
        rows = [r + [""] * (width - len(r)) for r in raw_rows]
        comma_decimal = uses_decimal_comma(rows) if sep != "," else False
        grid = [[_cell(v.strip(), comma_decimal) for v in row] for row in rows]
        parsed = ParsedDocument(file_format="csv", elements=[], row_count=len(grid),
                                file_metadata={"encoding": used, "delimiter": sep, "decimal_separator": "," if comma_decimal else "."})
        if comma_decimal:
            parsed.warnings.append("Numbers use a decimal comma (e.g. 1.200,50); values were read accordingly and printed text is kept as is.")
        els, tables, notes, _ = sheet_to_elements(grid, file_format="csv", sheet=None, first_table_id=0)
        parsed.elements, parsed.tables = els, tables
        parsed.warnings += notes if els else ["CSV file contains no data."]
        if els:
            prof, warn = profile(grid)
            parsed.file_metadata["profile"] = prof
            parsed.warnings += warn
            desc = "; ".join(f"'{c['name']}': {c['type']}" + (f", {c['missing']} missing" if c["missing"] else "") for c in prof["columns"])
            parsed.elements.append(Element(
                "text", f"[Column profile computed by FinRAG] {prof['data_rows']} data rows; columns: {desc}; "
                        f"exact duplicate rows: {prof['duplicate_row_count']}"
                        + (" (rows " + ", ".join(str(d["row"]) for d in prof["duplicate_rows"][:10]) + ")" if prof["duplicate_rows"] else "") + ".",
                Location(file_format="csv", row=1, row_end=len(grid)), context=["computed_summary", "column profile"]))
        return parsed

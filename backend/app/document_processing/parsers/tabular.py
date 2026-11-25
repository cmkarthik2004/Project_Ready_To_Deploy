"""Shared logic that turns a 2-D grid (Excel sheet or CSV) into Elements.

A grid is a list of rows; each cell is a `GridCell` with its raw text, parsed
numeric value (Decimal or None), coordinate and optional formula.

Two layouts are recognised automatically:
* "wide"  – rows are line items, columns are periods/categories
            (e.g. a P&L with columns FY2023, FY2024). Label = left text cells.
* "long"  – rows are records (e.g. transactions: Date, Category, Amount).
            Each row is kept as a record; Python computes column totals and
            per-category sums (clearly labelled as computed) so questions like
            "which expense category is highest?" can be answered exactly.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from app.document_processing.elements import Cell, Element, Location, ParsedTable
from app.financial_analytics.numbers import parse_number


@dataclass
class GridCell:
    text: str
    value: Decimal | None
    coord: str | None  # "B7" for Excel, None for CSV
    formula: str | None = None
    is_date: bool = False


def col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def make_cell(raw, coord: str | None, formula: str | None = None) -> GridCell:
    if raw is None:
        return GridCell("", None, coord, formula)
    if isinstance(raw, bool):
        return GridCell(str(raw), None, coord, formula)
    if isinstance(raw, (int, float, Decimal)):
        if isinstance(raw, float) and raw != raw:  # NaN
            return GridCell("", None, coord, formula)
        d = Decimal(str(raw))
        txt = format(d.normalize(), "f") if isinstance(raw, float) else str(raw)
        return GridCell(txt, d, coord, formula)
    if isinstance(raw, (dt.datetime, dt.date)):
        return GridCell(raw.date().isoformat() if isinstance(raw, dt.datetime) else raw.isoformat(), None, coord, formula, True)
    txt = str(raw).strip()
    return GridCell(txt, parse_number(txt), coord, formula)


def _is_text(c: GridCell) -> bool:
    return bool(c.text) and c.value is None


def _find_header(grid: list[list[GridCell]]) -> int | None:
    """Header = first row (within the first 20) with >=2 non-empty cells that is
    followed by a row containing at least one number."""
    for i, row in enumerate(grid[:20]):
        filled = [c for c in row if c.text]
        if len(filled) >= 2 and sum(1 for c in filled if _is_text(c) or c.is_date or _looks_period(c.text)) >= max(2, len(filled) - 1):
            nxt = grid[i + 1: i + 4]
            if any(any(c.value is not None for c in r) for r in nxt):
                # a group-header row ("Consolidated" over two columns) directly above the period row:
                # the deeper row is the header; the group row is combined into it later.
                while i + 1 < len(grid) and _is_header_like(grid[i + 1]) and any(c.value is not None for r in grid[i + 2:i + 5] for c in r):
                    i += 1
                return i
    return None


def _is_header_like(row: list[GridCell]) -> bool:
    filled = [c for c in row if c.text]
    return len(filled) >= 2 and not any(c.value is not None and not _looks_period(c.text) for c in filled) and \
        sum(1 for c in filled if _is_text(c) or c.is_date or _looks_period(c.text)) >= max(2, len(filled) - 1)


def split_blocks(grid: list[list[GridCell]]) -> list[tuple[int, int]]:
    """Table boundaries inside one sheet: a new table starts where, after one or more blank rows, a new
    header row appears (several text/period cells, no amounts) followed by rows with numbers. Title lines
    between the blank rows and that header belong to the new table. Returns [(start, end_exclusive)]."""
    blank = [not any(c.text for c in r) for r in grid]
    starts = [0]
    first_h = _find_header(grid)
    if first_h is None:
        return [(0, len(grid))]
    r = first_h + 2
    while r < len(grid):
        if not blank[r] and blank[r - 1] and r - 1 > starts[-1]:
            # look for a header within the next 3 non-blank rows (titles may come first)
            k, seen = r, 0
            while k < len(grid) and seen < 3:
                if not blank[k]:
                    if _is_header_like(grid[k]) and any(any(c.value is not None for c in rr) for rr in grid[k + 1:k + 4]):
                        starts.append(r)
                        r = k + 2
                        break
                    if any(c.value is not None for c in grid[k]):
                        break  # data row first: same table continues
                    seen += 1
                k += 1
        r += 1
    ends = starts[1:] + [len(grid)]
    return list(zip(starts, ends))


TOTAL_RE = __import__("re").compile(r"^(total|sub[- ]?total|grand total)\b", __import__("re").I)


def _looks_period(text: str) -> bool:
    import re

    return bool(re.fullmatch(r"(?:FY\s?)?(?:19|20)\d{2}(?:\s?[-–/]\s?\d{2,4})?|Q[1-4].*|H[12].*", text.strip(), re.I))


def grid_to_elements(
    grid: list[list[GridCell]],
    *,
    file_format: str,
    sheet: str | None,
    table_id: int,
    title_hint: str | None = None,
    row_offset: int = 0,
) -> tuple[list[Element], list[ParsedTable], list[str]]:
    """Return (elements, tables, notes) for one table block of a sheet / CSV file.
    `row_offset` = index of the block's first row in the sheet (so row numbers stay sheet-absolute)."""
    elements: list[Element] = []
    notes: list[str] = []
    # drop fully-empty trailing columns
    width = max((max((i for i, c in enumerate(r) if c.text), default=-1) for r in grid), default=-1) + 1
    grid = [r[:width] + [GridCell("", None, None)] * (width - len(r)) for r in grid]
    if not grid or width == 0:
        return [], [], ["empty sheet"]

    def loc(r: int, c: int | None = None, r_end: int | None = None) -> Location:
        if file_format == "csv":
            return Location(file_format="csv", row=r + 1 + row_offset, row_end=(r_end + 1 + row_offset) if r_end is not None else None)
        cell = grid[r][c].coord if c is not None else None
        rng = None
        if c is None:
            first = grid[r][0].coord or f"A{r + 1 + row_offset}"
            last_row = r_end if r_end is not None else r
            rng = f"{first}:{col_letter(width - 1)}{last_row + 1 + row_offset}" if file_format != "csv" else None
        return Location(file_format=file_format, sheet=sheet, cell=cell, cell_range=rng, row=r + 1 + row_offset)

    h = _find_header(grid)
    context: list[str] = [title_hint] if title_hint else []
    # rows before the header that hold a single text cell are titles / unit lines
    for r in range(0, h if h is not None else 0):
        texts = [c.text for c in grid[r] if c.text]
        if texts:
            context.append(" ".join(texts))
            elements.append(Element("heading", " ".join(texts), loc(r), context=list(context)))
    header = [c.text for c in grid[h]] if h is not None else [f"Column {col_letter(i)}" for i in range(width)]
    # Two-row header: a row directly above with group labels over the value columns (e.g. "Consolidated" over
    # two year columns, filled across a merged range) is combined: "Consolidated 2024", "Consolidated 2025".
    if h is not None and h > 0:
        above = grid[h - 1]
        if not above[0].text and not any(c.value is not None and not _looks_period(c.text) for c in above) and any(above[ci].text for ci in range(1, width)):
            header = [(f"{above[ci].text} {header[ci]}".strip() if ci >= 1 and above[ci].text and above[ci].text != header[ci] else header[ci])
                      for ci in range(width)]
            notes.append("two-row column header combined")
    start = (h + 1) if h is not None else 0

    numeric_cols = [ci for ci in range(width) if sum(1 for r in grid[start:] if r[ci].value is not None) >= max(1, (len(grid) - start) * 0.5)]
    text_cols = [ci for ci in range(width) if ci not in numeric_cols and any(_is_text(r[ci]) for r in grid[start:])]
    # Long (record) layout: many rows, and a numeric column header is not a period.
    # A table with a date column (transactions, ledgers) is a record table at any length.
    date_rx = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
    data = [r for r in grid[start:] if any(c.text for c in r)]
    has_date_col = any(sum(1 for r in data if r[ci].is_date or date_rx.match(r[ci].text)) >= max(2, 0.8 * len(data)) for ci in range(width))
    is_long = ((len(grid) - start) > 30 or (has_date_col and len(data) >= 3)) and numeric_cols and \
        not any(_looks_period(header[ci]) for ci in numeric_cols)

    table_rows: list[list[str]] = []
    for r in range(start, len(grid)):
        row = grid[r]
        if not any(c.text for c in row):
            continue
        table_rows.append([c.text for c in row])
        first_num = next((ci for ci, c in enumerate(row) if c.value is not None and not (h is not None and ci == 0)), None)
        label_cells = [c.text for ci, c in enumerate(row) if _is_text(c) and (first_num is None or ci < first_num or is_long)]
        label = " ".join(label_cells[:3]).strip() if not is_long else " | ".join(f"{header[ci]}: {row[ci].text}" for ci in text_cols if row[ci].text)
        cells = []
        for ci, c in enumerate(row):
            if c.value is None:
                continue
            cl = loc(r, ci)
            cells.append(Cell(c.text, header[ci] if ci < len(header) else None, cl))
            if c.formula:
                cl.columns = [f"formula: {c.formula}"]
        shown = " | ".join(f"{cc.column_header}: {cc.text}" if cc.column_header else cc.text for cc in cells)
        if not cells and label_cells:
            # a label-only row: section header inside the sheet
            context.append(" ".join(label_cells))
            elements.append(Element("heading", " ".join(label_cells), loc(r), context=list(context[-3:])))
            continue
        text = " | ".join(f"{header[ci]}: {row[ci].text}" for ci in range(width) if row[ci].text) if is_long else f"{label} | {shown}"
        is_total = bool(TOTAL_RE.match(label or "")) or any(c.formula and "SUM(" in c.formula.upper() for c in row)
        elements.append(Element("table_row", text, loc(r), label=label or None, cells=cells, context=list(context[-3:]), table_id=table_id,
                                is_total=is_total))

    tbl_loc = loc(start, None, len(grid) - 1) if file_format != "csv" else Location(file_format="csv", row=start + 1 + row_offset, row_end=len(grid) + row_offset)
    tables = [ParsedTable(table_id, context[-1] if context else sheet, tbl_loc, header, table_rows)] if table_rows else []

    if is_long:
        elements.extend(_record_summaries(grid, start, header, numeric_cols, text_cols, file_format, sheet, table_id, context, row_offset))
        notes.append("record layout detected: computed column totals and category sums")
    return elements, tables, notes


def _record_summaries(grid, start, header, numeric_cols, text_cols, file_format, sheet, table_id, context, row_offset=0) -> list[Element]:
    """Python-computed aggregates over a record-style table (never LLM arithmetic)."""
    out: list[Element] = []
    n_rows = len(grid) - start
    loc = Location(file_format=file_format, sheet=sheet, row=start + 1 + row_offset, row_end=len(grid) + row_offset)
    for nc in numeric_cols:
        vals = [r[nc].value for r in grid[start:] if r[nc].value is not None]
        if not vals:
            continue
        total = sum(vals, Decimal(0))
        out.append(Element(
            "text",
            f"[Computed by FinRAG from {len(vals)} rows] Column '{header[nc]}': total {total}, "
            f"minimum {min(vals)}, maximum {max(vals)}, rows with values {len(vals)} of {n_rows}.",
            loc, context=list(context[-2:]) + ["computed_summary"], table_id=table_id,
        ))
        for tc in text_cols:
            groups: dict[str, Decimal] = defaultdict(Decimal)
            counts: dict[str, int] = defaultdict(int)
            for r in grid[start:]:
                if r[nc].value is not None and r[tc].text:
                    groups[r[tc].text] += r[nc].value
                    counts[r[tc].text] += 1
            if 1 < len(groups) <= 60 and len(groups) < n_rows * 0.8:
                ranked = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)
                body = "; ".join(f"{k}: {v} ({counts[k]} rows)" for k, v in ranked)
                out.append(Element(
                    "text",
                    f"[Computed by FinRAG] Sum of '{header[nc]}' grouped by '{header[tc]}' (highest first): {body}.",
                    loc, context=list(context[-2:]) + ["computed_summary"], table_id=table_id,
                ))
    return out


def sheet_to_elements(grid: list[list[GridCell]], *, file_format: str, sheet: str | None, first_table_id: int,
                      title_hint: str | None = None) -> tuple[list[Element], list[ParsedTable], list[str], int]:
    """Split a sheet into table blocks and convert each. Returns (elements, tables, notes, next_table_id)."""
    els: list[Element] = []
    tbls: list[ParsedTable] = []
    notes: list[str] = []
    blocks = split_blocks(grid)
    tid = first_table_id
    for start, end in blocks:
        e, t, n = grid_to_elements(grid[start:end], file_format=file_format, sheet=sheet, table_id=tid,
                                   title_hint=title_hint, row_offset=start)
        els += e
        tbls += t
        notes += [x for x in n if x != "empty sheet"]
        tid += 1
    if len(blocks) > 1:
        notes.append(f"{len(blocks)} separate tables detected (rows " + ", ".join(f"{a + 1}-{b}" for a, b in blocks) + ")")
    return els, tbls, notes, tid

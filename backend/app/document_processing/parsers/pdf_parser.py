"""PDF parser built on PyMuPDF (optionally Docling for tables).

How it works
------------
1. Each PDF page is split into "regions". Landscape pages whose two halves carry
   separate printed page numbers (two-page spreads, common in annual reports)
   become two regions so text from facing pages never gets interleaved.
2. Pages with (almost) no text layer but with images are OCR'd with Tesseract
   through PyMuPDF (`get_textpage_ocr`) and flagged `ocr=True`.
3. Ruled tables are detected with `page.find_tables()`; their cells become
   table-row elements (first text cell = label).
4. All remaining words are grouped into visual lines. A line that ends in
   numbers is a *table row*; a line with two or more period tokens (years,
   "2024-25", "31 March 2025") is a *column header*. Numbers are assigned to the
   header column with the nearest x-centre, so each value knows its period.
5. Other lines are merged into paragraphs.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

import pymupdf

from app.core.config import get_settings
from app.document_processing import ocr_service
from app.document_processing.elements import Cell, Element, Location, ParsedDocument, ParsedTable
from app.financial_analytics.numbers import is_number_token, looks_like_year

PERIOD_TOKEN_RE = re.compile(
    r"^(?:FY\s?|F\.Y\.\s?)?(?:19|20)\d{2}(?:\s?[-–/]\s?(?:19|20)?\d{2})?,?$|^(?:FY|Q[1-4])['’]?\d{2,4}$",
    re.I,
)
NOTE_REF_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})?[a-z]?$|^[A-Z](?:-[A-Z])?$")


@dataclass
class _Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class _Column:
    xc: float
    label: str


def _group_lines(words: list[_Word]) -> list[list[_Word]]:
    if not words:
        return []
    heights = [w.y1 - w.y0 for w in words if w.y1 > w.y0]
    tol = max(2.0, (statistics.median(heights) if heights else 8.0) * 0.45)
    words = sorted(words, key=lambda w: (w.yc, w.x0))
    lines: list[list[_Word]] = []
    cur: list[_Word] = [words[0]]
    cur_y = words[0].yc
    for w in words[1:]:
        if abs(w.yc - cur_y) <= tol:
            cur.append(w)
            cur_y = (cur_y * (len(cur) - 1) + w.yc) / len(cur)
        else:
            lines.append(sorted(cur, key=lambda x: x.x0))
            cur, cur_y = [w], w.yc
    lines.append(sorted(cur, key=lambda x: x.x0))
    return lines


def _segments(line: list[_Word], gap: float) -> list[list[_Word]]:
    """Split a line where horizontal whitespace is large (column boundaries)."""
    segs: list[list[_Word]] = [[line[0]]]
    for prev, w in zip(line, line[1:]):
        if w.x0 - prev.x1 > gap:
            segs.append([w])
        else:
            segs[-1].append(w)
    return segs


def _page_label(words: list[_Word], rect: pymupdf.Rect) -> str | None:
    """Printed page number: a lone integer in the top or bottom 7% band."""
    band = rect.height * 0.07
    cands = [
        w for w in words
        if re.fullmatch(r"\d{1,4}", w.text) and (w.y1 > rect.y1 - band or w.y0 < rect.y0 + band)
    ]
    if not cands:
        return None
    # prefer the one closest to an outer horizontal edge
    cands.sort(key=lambda w: min(abs(w.x0 - rect.x0), abs(rect.x1 - w.x1)))
    return cands[0].text


def _is_spread(page: pymupdf.Page, words: list[_Word]) -> bool:
    r = page.rect
    if r.width < r.height * 1.2:
        return False
    mid = r.x0 + r.width / 2
    left = _page_label([w for w in words if w.x1 <= mid], pymupdf.Rect(r.x0, r.y0, mid, r.y1))
    right = _page_label([w for w in words if w.x0 >= mid], pymupdf.Rect(mid, r.y0, r.x1, r.y1))
    return bool(left and right and left != right)


def _header_columns(lines: list[list[_Word]], idx: int) -> list[_Column] | None:
    """If line `idx` is a column-header line, return its period columns."""
    line = lines[idx]
    anchors = [w for w in line if PERIOD_TOKEN_RE.match(w.text)]
    if len(anchors) < 2 or len(anchors) > 8:
        return None
    # Column headers are short and their period tokens sit in separate columns;
    # a sentence such as "in 2024-25 compared with 2023-24" is not a header.
    if len(line) > len(anchors) * 4 + 4:
        return None
    xs = sorted(a.xc for a in anchors)
    if min(b - a for a, b in zip(xs, xs[1:])) < 30:
        return None
    # A header line is mostly words, not amounts
    amounts = [w for w in line if is_number_token(w.text) and not looks_like_year(w.text) and w not in anchors]
    if len(amounts) > len(anchors):
        return None
    def nearest(w: _Word) -> _Word:
        return min(anchors, key=lambda a: abs(a.xc - w.xc))

    cols: list[_Column] = []
    for a in anchors:
        # words on this line close to (and nearest to) the anchor, e.g. "31st March, 2025"
        # the whitespace-delimited segment of the header line that contains the anchor
        seg = next(sg for sg in _segments(line, gap=8.0) if a in sg)
        if sum(1 for w in seg if w in anchors) > 1:  # segment spans several columns: fall back to proximity
            seg = [w for w in seg if abs(w.xc - a.xc) < 45 and nearest(w) is a]
        near = [w for w in seg if not is_number_token(w.text) or w is a or re.fullmatch(r"\d{1,2}(st|nd|rd|th)?", w.text)]
        # words on up to two lines above that sit over the anchor ("As at", "Year ended")
        above: list[str] = []
        for j in (idx - 2, idx - 1):
            if j >= 0:
                lj = " ".join(w.text for w in lines[j])
                if _is_title_line(lj) or len(lines[j]) > 10 or lj.rstrip().endswith((":", ".")):
                    continue  # unit/title lines and sentences are not column headers
                above += [w.text for w in sorted(lines[j], key=lambda x: x.x0)
                          if abs(w.xc - a.xc) < 40 and nearest(w) is a and not is_number_token(w.text)]
        label = " ".join(above + [w.text for w in sorted(near, key=lambda x: x.x0)]).strip(" ,")
        cols.append(_Column(xc=a.xc, label=label or a.text))
    return cols


def _assign(values: list[_Word], cols: list[_Column] | None) -> list[tuple[_Word, str | None]]:
    if not cols:
        return [(v, None) for v in values]
    out: list[tuple[_Word, str | None]] = []
    # Values right of the first column, aligned to nearest column centre.
    for v in values:
        best = min(cols, key=lambda c: abs(c.xc - v.xc))
        if abs(best.xc - v.xc) <= 70:
            out.append((v, best.label))
    if not out and len(values) >= len(cols):
        out = list(zip(values[-len(cols):], [c.label for c in cols]))
    return out


def _worth_table_detection(page: pymupdf.Page, words: list[_Word]) -> bool:
    """Run the (slow) ruled-table finder only on pages that have both enough
    numbers and enough long horizontal/vertical ruling lines."""
    if sum(1 for w in words if is_number_token(w.text)) < 10:
        return False
    rulings = 0
    for d in page.get_cdrawings():
        for it in d.get("items", []):
            if it[0] == "l":
                (x0, y0), (x1, y1) = it[1], it[2]
                if (abs(y0 - y1) < 1 and abs(x1 - x0) > 40) or (abs(x0 - x1) < 1 and abs(y1 - y0) > 15):
                    rulings += 1
            elif it[0] == "re":
                x0, y0, x1, y1 = tuple(it[1])[:4]
                w, h = abs(x1 - x0), abs(y1 - y0)
                if (h < 2 and w > 40) or (w < 2 and h > 15):
                    rulings += 1
        if rulings >= 12:
            return True
    return False


def _table_quality_ok(rows: list[list[str]]) -> bool:
    """Reject table-finder output whose cells merged several visual lines or
    split numbers into fragments; the line-based parser handles those better."""
    cells = [c for rw in rows for c in rw if c]
    if not cells:
        return False
    multiline = sum(1 for c in cells if "\n" in c) / len(cells)
    fragments = sum(1 for c in cells if re.fullmatch(r"[,.\s]+", c) or re.search(r"\d\s*\n\s*[,.]", c)) / len(cells)
    return multiline <= 0.15 and fragments == 0


def _ctx(context: list[str]) -> list[str]:
    """Context for an element: the page's first heading (usually the running header such as
    'STANDALONE FINANCIAL STATEMENTS') plus the three most recent distinct headings."""
    if not context:
        return []
    recent = context[-3:]
    return recent if context[0] in recent else [context[0]] + recent


def _is_title_line(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 140:
        return False
    low = t.lower()
    keys = ("balance sheet", "statement of", "profit and loss", "cash flow", "income statement", "financial statements", "in crore",
            "in lakh", "in million", "in thousand", "in billion", "'000", "budget", "notes to", "schedule")
    return any(k in low for k in keys)


class PdfParser:
    def __init__(self) -> None:
        self.s = get_settings()

    def parse(self, path: str) -> ParsedDocument:
        doc = pymupdf.open(path)
        if doc.needs_pass:
            raise ValueError("PDF is password-protected; FinRAG cannot read encrypted PDFs.")
        if doc.page_count > self.s.max_pdf_pages:
            raise ValueError(f"PDF has {doc.page_count} pages; the limit is {self.s.max_pdf_pages}.")
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        parsed = ParsedDocument(file_format="pdf", elements=[], page_count=doc.page_count, file_metadata=meta)
        table_id = 0
        ocr_ok = ocr_service.available()
        # Multi-page tables: the period columns (and statement title) of the last table on a page are carried to the
        # next page, and used there only if that page's first amount rows line up with those columns before any new
        # header appears. Pages that used a carried header are recorded.
        carry: tuple[list[_Column], int, list[str]] | None = None
        continued: list[dict] = []
        for pno in range(doc.page_count):
            page = doc[pno]
            ocr = False
            raw_words = page.get_text("words")
            if ocr_service.needs_ocr(page, raw_words):
                if ocr_ok:
                    try:
                        raw_words = ocr_service.ocr_words(page)
                        ocr = True
                        parsed.ocr_pages.append(pno + 1)
                    except Exception as exc:  # OCR failure is reported, never hidden
                        parsed.warnings.append(f"OCR failed on page {pno + 1}: {exc}")
                else:
                    parsed.warnings.append(f"Page {pno + 1} appears to be scanned but OCR (Tesseract) is not available.")
            words = [_Word(w[0], w[1], w[2], w[3], w[4]) for w in raw_words if w[4].strip()]
            if not words:
                continue
            r = page.rect
            if _is_spread(page, words):
                mid = r.x0 + r.width / 2
                regions = [("left", pymupdf.Rect(r.x0, r.y0, mid, r.y1)), ("right", pymupdf.Rect(mid, r.y0, r.x1, r.y1))]
            else:
                regions = [(None, r)]

            # Ruled tables (PyMuPDF table finder). Skipped for OCR pages.
            tables_on_page = []
            if not ocr and _worth_table_detection(page, words):
                try:
                    tables_on_page = list(page.find_tables().tables)
                except Exception as exc:
                    parsed.warnings.append(f"Table detection failed on page {pno + 1}: {exc}")

            context: list[str] = []  # shared by both halves of a spread
            for half, rect in regions:
                rwords = [w for w in words if rect.x0 - 1 <= w.xc <= rect.x1 + 1]
                label = _page_label(rwords, rect)
                base_loc = dict(file_format="pdf", page=pno + 1, page_label=label, half=half, ocr=ocr)
                consumed: set[int] = set()
                for t in tables_on_page:
                    tb = pymupdf.Rect(t.bbox)
                    if not rect.contains(pymupdf.Point((tb.x0 + tb.x1) / 2, (tb.y0 + tb.y1) / 2)):
                        continue
                    rows = [[(c or "").strip() for c in row] for row in t.extract()]
                    rows = [rw for rw in rows if any(rw)]
                    if len(rows) < 2 or max(len(rw) for rw in rows) < 2 or not _table_quality_ok(rows):
                        continue
                    for i, w in enumerate(rwords):
                        if tb.contains(pymupdf.Point(w.xc, w.yc)):
                            consumed.add(i)
                    header, body = rows[0], rows[1:]
                    tloc = Location(**base_loc, bbox=[round(v, 1) for v in t.bbox], table_index=table_id)
                    parsed.tables.append(ParsedTable(table_id, None, tloc, header, body))
                    for ri, rw in enumerate(body):
                        lab = next((c for c in rw if c and not is_number_token(c)), "")
                        cells = [Cell(c, header[ci] if ci < len(header) else None, Location(**base_loc, table_index=table_id, row=ri + 2))
                                 for ci, c in enumerate(rw) if c and is_number_token(c)]
                        txt = " | ".join(c for c in rw if c)
                        parsed.elements.append(Element("table_row", txt, Location(**base_loc, table_index=table_id, row=ri + 2),
                                                       label=lab, cells=cells, table_id=table_id))
                    table_id += 1

                lines = _group_lines([w for i, w in enumerate(rwords) if i not in consumed])
                carried_from: int | None = None
                char_w = statistics.median([(w.x1 - w.x0) / max(len(w.text), 1) for w in rwords]) if rwords else 5
                cols: list[_Column] | None = None
                groups: list[str] = []  # recent label-only lines, e.g. "Current Liabilities"
                para: list[str] = []
                para_bbox: list[float] | None = None
                vt_rows: list[list[str]] = []  # virtual (text-aligned) table being built
                vt_header: list[str] = []
                vt_start: int | None = None

                def flush_para() -> None:
                    nonlocal para, para_bbox
                    if para:
                        txt = " ".join(para).strip()
                        if txt:
                            parsed.elements.append(Element("paragraph", txt, Location(**base_loc, bbox=para_bbox), context=_ctx(context)))
                    para, para_bbox = [], None

                def flush_vtable() -> None:
                    nonlocal vt_rows, vt_header, vt_start, table_id
                    if len(vt_rows) >= 3:
                        title = context[-1] if context else None
                        parsed.tables.append(ParsedTable(table_id, title, Location(**base_loc, table_index=table_id), ["Particulars"] + vt_header, vt_rows))
                        for el in parsed.elements[vt_start:]:
                            if el.kind == "table_row" and el.table_id is None and el.location.page == pno + 1 and el.location.half == half:
                                el.table_id = table_id
                                el.location.table_index = table_id
                        table_id += 1
                    vt_rows, vt_header, vt_start = [], [], None

                for li, line in enumerate(lines):
                    text = " ".join(w.text for w in line)
                    if label and text.strip() == label:
                        continue  # bare page number
                    hdr = _header_columns(lines, li)
                    if hdr:
                        flush_para()
                        flush_vtable()
                        cols = hdr
                        vt_header = [c.label for c in cols]
                        continue
                    # split label vs. trailing numbers
                    nums_from = len(line)
                    for k in range(len(line) - 1, -1, -1):
                        if is_number_token(line[k].text) and not (cols is None and looks_like_year(line[k].text)):
                            nums_from = k
                        else:
                            break
                    label_words, value_words = line[:nums_from], line[nums_from:]
                    # drop note references that sit between label and amounts
                    if cols and len(value_words) > len(cols):
                        extra = len(value_words) - len(cols)
                        if all(NOTE_REF_RE.match(w.text) for w in value_words[:extra]):
                            value_words = value_words[extra:]
                    row_label = " ".join(w.text for w in label_words).strip(" :")
                    if (value_words and row_label and cols is None and carried_from is None and carry and carry[1] == pno
                            and len(value_words) <= len(carry[0])
                            and all(min(abs(c.xc - v.xc) for c in carry[0]) <= 25 for v in value_words)):
                        cols = carry[0]
                        carried_from = carry[1]
                        vt_header = [c.label for c in cols]
                        for c in carry[2]:
                            if c not in context:
                                context.insert(0, c)
                        continued.append({"page": pno + 1, "header_from_page": carry[1], "columns": vt_header})
                    if value_words and row_label and re.search(r"[A-Za-z]", row_label):
                        flush_para()
                        assigned = _assign(value_words, cols)
                        bbox = [round(min(w.x0 for w in line), 1), round(min(w.y0 for w in line), 1),
                                round(max(w.x1 for w in line), 1), round(max(w.y1 for w in line), 1)]
                        loc = Location(**base_loc, bbox=bbox)
                        cells = [Cell(w.text, colname, Location(**base_loc, bbox=[round(w.x0, 1), round(w.y0, 1), round(w.x1, 1), round(w.y1, 1)]))
                                 for w, colname in assigned]
                        if cells:
                            shown = " | ".join(f"{c.column_header}: {c.text}" if c.column_header else c.text for c in cells)
                            if vt_start is None:
                                vt_start = len(parsed.elements)
                            ctx = _ctx(context) + [f"group: {g}" for g in groups[-3:]]
                            shown_label = f"{groups[-1].rstrip(':')} > {row_label}" if groups and re.match(r"^\(?[a-z0-9ivx]{1,4}[).]\s", row_label) else row_label
                            parsed.elements.append(Element("table_row", f"{shown_label} | {shown}", loc, label=row_label, cells=cells, context=ctx))
                            vt_rows.append([row_label] + [c.text for c in cells])
                            continue
                    # plain text
                    if _is_title_line(text):
                        flush_para()
                        if text.strip() in context:  # keep context diverse: repeated unit lines must not
                            context.remove(text.strip())  # push the section header out of the window
                        context.append(text.strip())
                        parsed.elements.append(Element("heading", text.strip(), Location(**base_loc), context=_ctx(context)))
                        continue
                    if cols and len(text) <= 70 and not re.search(r"\d{2,}", text):
                        groups.append(text.strip())  # row-group label inside a statement
                    if para and len(" ".join(para)) > 1200:
                        flush_para()
                    para.append(text)
                    lb = [min(w.x0 for w in line), min(w.y0 for w in line), max(w.x1 for w in line), max(w.y1 for w in line)]
                    para_bbox = lb if para_bbox is None else [min(para_bbox[0], lb[0]), min(para_bbox[1], lb[1]), max(para_bbox[2], lb[2]), max(para_bbox[3], lb[3])]
                    para_bbox = [round(v, 1) for v in para_bbox]
                    _ = char_w
                flush_para()
                flush_vtable()
                carry = (cols, pno + 1, _ctx(context)[-2:]) if cols else None
        doc.close()
        if continued:
            parsed.file_metadata["multi_page_tables"] = continued
            parsed.warnings.append("Table continued across pages without a repeated header: columns carried over on page(s) "
                                   + ", ".join(str(c["page"]) for c in continued) + " (alignment checked).")
        if self.s.pdf_table_engine == "docling":
            from app.document_processing.parsers.docling_tables import add_docling_tables

            add_docling_tables(path, parsed)
        return parsed

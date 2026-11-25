"""Word (.docx) parser using python-docx.

Walks the document body in order (paragraphs and tables interleaved), keeps a
heading path (Heading 1 > Heading 2 > ...) so every paragraph and table row is
cited by its section, and turns tables into table-row elements whose value
cells carry their column header (used for period detection).
"""
from __future__ import annotations

import re

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.document_processing.elements import Cell, Element, Location, ParsedDocument, ParsedTable
from app.financial_analytics.numbers import parse_number


def _heading_level(p: Paragraph) -> int | None:
    name = (p.style.name if p.style is not None else "") or ""
    if name == "Title":
        return 0
    m = re.match(r"Heading\s*(\d)", name)
    if m:
        return int(m.group(1))
    return None


def _unique_cells(row) -> list[str]:
    """python-docx repeats merged cells; collapse consecutive duplicates."""
    out: list[str] = []
    prev_tc = None
    for c in row.cells:
        if c._tc is prev_tc:
            continue
        prev_tc = c._tc
        out.append(" ".join(c.text.split()))
    return out


class DocxParser:
    def parse(self, path: str) -> ParsedDocument:
        d = docx.Document(path)
        cp = d.core_properties
        meta = {k: str(v) for k, v in {"title": cp.title, "author": cp.author, "created": cp.created,
                                         "modified": cp.modified, "subject": cp.subject}.items() if v}
        parsed = ParsedDocument(file_format="docx", elements=[], file_metadata=meta)
        path_stack: list[str] = []
        p_idx = 0
        t_idx = 0
        for child in d.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = Paragraph(child, d)
                text = " ".join(p.text.split())
                if not text:
                    continue
                lvl = _heading_level(p)
                if lvl is not None:
                    path_stack = path_stack[: max(lvl - 1, 0)] + [text] if lvl > 0 else [text]
                    parsed.elements.append(Element("heading", text, Location("docx", heading_path=list(path_stack), paragraph_index=p_idx), context=list(path_stack)))
                else:
                    parsed.elements.append(Element("paragraph", text, Location("docx", heading_path=list(path_stack) or None, paragraph_index=p_idx), context=list(path_stack[-2:])))
                p_idx += 1
            elif tag == "tbl":
                t = Table(child, d)
                rows = [_unique_cells(r) for r in t.rows]
                rows = [r for r in rows if any(r)]
                if not rows:
                    continue
                header, body = rows[0], rows[1:]
                tloc = Location("docx", heading_path=list(path_stack) or None, table_index=t_idx)
                title = path_stack[-1] if path_stack else None
                parsed.tables.append(ParsedTable(t_idx, title, tloc, header, body))
                for ri, r in enumerate(body):
                    rloc = Location("docx", heading_path=list(path_stack) or None, table_index=t_idx, row=ri + 2)
                    label = " ".join(c for c in r if c and parse_number(c) is None)[:300]
                    cells = [Cell(c, header[ci] if ci < len(header) else None, Location("docx", heading_path=list(path_stack) or None, table_index=t_idx, row=ri + 2, columns=[header[ci]] if ci < len(header) else None))
                             for ci, c in enumerate(r) if c and parse_number(c) is not None]
                    shown = " | ".join(f"{cc.column_header}: {cc.text}" if cc.column_header else cc.text for cc in cells)
                    txt = f"{label} | {shown}" if cells else " | ".join(c for c in r if c)
                    parsed.elements.append(Element("table_row", txt, rloc, label=label or None, cells=cells,
                                                   context=list(path_stack[-2:]) + ([" ".join(header)] if header else []), table_id=t_idx))
                t_idx += 1
        if not parsed.elements:
            parsed.warnings.append("The Word document contains no readable text.")
        return parsed

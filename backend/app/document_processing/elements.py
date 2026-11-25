"""Format-independent representation of parsed document content.

Every parser (PDF, DOCX, XLSX/XLS, CSV) converts its input into a list of
`Element`s. Each element carries a `Location` that says *exactly* where in the
original file the content came from, so that every chunk, citation and
financial value can be traced back:

* PDF   -> page (1-based PDF page), page_label (printed page number, if found),
           half ("left"/"right" for two-page spreads), bbox
* DOCX  -> heading_path (section headings), paragraph index, table index/row
* Excel -> sheet name, cell / cell range (A1 notation), row number
* CSV   -> row number (1-based, header = row 1), column names
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ElementKind = Literal["heading", "paragraph", "table_row", "table", "text"]


@dataclass
class Location:
    file_format: str
    page: int | None = None
    page_label: str | None = None
    half: str | None = None
    bbox: list[float] | None = None
    heading_path: list[str] | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    sheet: str | None = None
    cell: str | None = None
    cell_range: str | None = None
    row: int | None = None
    row_end: int | None = None
    columns: list[str] | None = None
    ocr: bool = False

    def to_dict(self) -> dict[str, Any]:
        # identity checks: `0 in (None, [], False)` is True in Python, which would drop table_index 0 / paragraph 0
        return {k: v for k, v in asdict(self).items() if k == "file_format" or not (v is None or v is False or v == [])}

    def describe(self) -> str:
        return describe_location(self.to_dict())


def describe_location(loc: dict[str, Any]) -> str:
    """Human-readable citation location, e.g. 'page 99 (printed 194)'."""
    fmt = loc.get("file_format")
    parts: list[str] = []
    if fmt == "pdf":
        p, pe = loc.get("page"), loc.get("page_end")
        parts.append(f"page {p}" if not pe or pe == p else f"pages {p}-{pe}")
        if loc.get("page_label"):
            parts.append(f"(printed p. {loc['page_label']})")
        if loc.get("ocr"):
            parts.append("[OCR]")
    elif fmt == "docx":
        if loc.get("heading_path"):
            parts.append("section: " + " > ".join(loc["heading_path"]))
        if loc.get("table_index") is not None:
            parts.append(f"table {loc['table_index'] + 1}")
            if loc.get("row"):
                parts.append(f"row {loc['row']}")
        elif loc.get("paragraph_index") is not None:
            parts.append(f"paragraph {loc['paragraph_index'] + 1}")
    elif fmt in ("xlsx", "xls"):
        parts.append(f"sheet '{loc.get('sheet')}'")
        if loc.get("cell"):
            parts.append(f"cell {loc['cell']}")
        elif loc.get("cell_range"):
            parts.append(f"cells {loc['cell_range']}")
    elif fmt == "csv":
        r, re_ = loc.get("row"), loc.get("row_end")
        parts.append(f"row {r}" if not re_ or re_ == r else f"rows {r}-{re_}")
    return " ".join(parts) if parts else "location not available"


@dataclass
class Cell:
    """One value cell of a table row, with its own precise location."""

    text: str
    column_header: str | None
    location: Location


@dataclass
class Element:
    kind: ElementKind
    text: str
    location: Location
    # For table rows: label + value cells (keeps column headers for period detection)
    label: str | None = None
    cells: list[Cell] = field(default_factory=list)
    # Context the row belongs to (nearest heading / table title / unit line)
    context: list[str] = field(default_factory=list)
    table_id: int | None = None
    is_total: bool = False  # printed total/subtotal row (label "Total …" or a SUM formula)


@dataclass
class ParsedTable:
    table_id: int
    title: str | None
    location: Location
    header: list[str]
    rows: list[list[str]]


@dataclass
class ParsedDocument:
    file_format: str
    elements: list[Element]
    tables: list[ParsedTable] = field(default_factory=list)
    page_count: int | None = None
    sheet_names: list[str] | None = None
    row_count: int | None = None
    ocr_pages: list[int] = field(default_factory=list)
    file_metadata: dict[str, Any] = field(default_factory=dict)  # e.g. PDF title/author, DOCX core props
    warnings: list[str] = field(default_factory=list)

    def full_text(self, limit: int | None = None) -> str:
        out, n = [], 0
        for e in self.elements:
            out.append(e.text)
            n += len(e.text)
            if limit and n > limit:
                break
        return "\n".join(out)

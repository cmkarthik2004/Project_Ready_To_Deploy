"""Chunking: group consecutive elements from the same locality into chunks.

Locality = same PDF page region, same DOCX section, same Excel sheet, or a
window of CSV rows. Table-row chunks are prefixed with their context (statement
title, unit line) so each chunk is self-contained for retrieval and the LLM can
see which period and unit each number belongs to.

Text that looks like a prompt-injection attempt is flagged (and neutralised in
the prompt, see rag/prompts.py) — the document is never allowed to give
instructions to the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.document_processing.elements import Element

TARGET_CHARS = 1400
MAX_CHARS = 2200

INJECTION_RE = re.compile(
    r"ignore (all |any |the )?(previous|prior|above) (instructions|prompts?)|disregard (the |all )?(previous|above|system)|"
    r"you are now|new instructions:|system prompt|<\|im_start\|>|<\|system\|>|\bassistant:\s|act as (an? )?(ai|assistant|system)|"
    r"reveal (your|the) (prompt|instructions)|do not (tell|inform) the user",
    re.I,
)


@dataclass
class Chunk:
    index: int
    text: str
    element_types: list[str]
    location: dict
    injection_flag: bool = False
    metadata: dict = field(default_factory=dict)


def _locality(el: Element) -> tuple:
    loc = el.location
    if loc.file_format == "pdf":
        return ("pdf", loc.page, loc.half)
    if loc.file_format == "docx":
        return ("docx", tuple(loc.heading_path or ()), loc.table_index)
    if loc.file_format in ("xlsx", "xls"):
        return (loc.file_format, loc.sheet, el.table_id)
    return ("csv", el.table_id)


def _merge_location(els: list[Element]) -> dict:
    first = els[0].location.to_dict()
    fmt = first["file_format"]
    if fmt == "pdf":
        pages = [e.location.page for e in els if e.location.page]
        labels = [e.location.page_label for e in els if e.location.page_label]
        first["page"], first["page_end"] = min(pages), max(pages)
        if labels:
            first["page_label"] = labels[0] if labels[0] == labels[-1] else f"{labels[0]}-{labels[-1]}"
        first.pop("bbox", None)
        first["ocr"] = any(e.location.ocr for e in els)
    elif fmt in ("xlsx", "xls"):
        rows = [e.location.row for e in els if e.location.row]
        if rows:
            first["row"], first["row_end"] = min(rows), max(rows)
            first["cell_range"] = f"rows {min(rows)}-{max(rows)}"
        first.pop("cell", None)
    elif fmt == "csv":
        rows = [r for e in els for r in (e.location.row, e.location.row_end) if r]
        if rows:
            first["row"], first["row_end"] = min(rows), max(rows)
    elif fmt == "docx":
        rows = [e.location.row for e in els if e.location.row]
        if rows:
            first["row"], first["row_end"] = min(rows), max(rows)
    return first


def _header(els: list[Element]) -> str:
    ctx: list[str] = []
    for e in els:
        for c in e.context:
            if c.startswith("group: ") or c == "computed_summary":
                continue
            if c not in ctx:
                ctx.append(c)
    return ("[Context: " + " | ".join(ctx[-3:]) + "]\n") if ctx else ""


def chunk_elements(elements: list[Element]) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[Element] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        if not buf:
            return
        has_rows = any(e.kind == "table_row" for e in buf)
        body = "\n".join(e.text for e in buf)
        text = (_header(buf) + body) if has_rows else body
        chunks.append(Chunk(
            index=len(chunks), text=text.strip(),
            element_types=sorted({e.kind for e in buf}),
            location=_merge_location(buf),
            injection_flag=bool(INJECTION_RE.search(text)),
        ))
        buf, size = [], 0

    prev_loc = None
    for el in elements:
        if not el.text.strip():
            continue
        loc = _locality(el)
        if buf and (loc != prev_loc or size + len(el.text) > MAX_CHARS or (size >= TARGET_CHARS and el.kind in ("heading", "paragraph"))):
            flush()
        if len(el.text) > MAX_CHARS:  # split very long paragraphs on sentence boundaries
            parts = re.split(r"(?<=[.!?])\s+", el.text)
            cur = ""
            for p in parts:
                if len(cur) + len(p) > TARGET_CHARS and cur:
                    buf.append(Element(el.kind, cur, el.location, context=el.context))
                    flush()
                    cur = ""
                cur += (" " if cur else "") + p
            if cur:
                buf.append(Element(el.kind, cur, el.location, context=el.context))
                size += len(cur)
        else:
            buf.append(el)
            size += len(el.text)
        prev_loc = loc
    flush()
    return chunks

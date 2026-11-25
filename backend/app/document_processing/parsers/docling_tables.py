"""Optional Docling table extraction for PDFs (PDF_TABLE_ENGINE=docling).

Runs docling_runner.py with the interpreter in DOCLING_PYTHON (a separate
virtualenv). Docling tables are added to the document's table list; their rows
become table-row elements only on pages where the PyMuPDF parser found no
table rows, so values are not double-counted. Failures are reported as
warnings and never hide the PyMuPDF result.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from app.document_processing.elements import Cell, Element, Location, ParsedDocument, ParsedTable
from app.financial_analytics.numbers import is_number_token

RUNNER = Path(__file__).with_name("docling_runner.py")


def add_docling_tables(path: str, parsed: ParsedDocument, timeout_s: int = 3600) -> None:
    py = os.environ.get("DOCLING_PYTHON", "/opt/docling-venv/bin/python")
    if not Path(py).exists():
        parsed.warnings.append(f"Docling table engine requested but DOCLING_PYTHON ({py}) does not exist; PyMuPDF tables used.")
        return
    try:
        r = subprocess.run([py, "-I", str(RUNNER), path], capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        parsed.warnings.append("Docling table extraction timed out; PyMuPDF tables used.")
        return
    if r.returncode != 0:
        parsed.warnings.append(f"Docling table extraction failed: {r.stderr.strip()[-400:]}")
        return
    data = json.loads(r.stdout.strip().splitlines()[-1])
    pages_with_rows = {e.location.page for e in parsed.elements if e.kind == "table_row"}
    next_id = max((t.table_id for t in parsed.tables), default=-1) + 1
    for t in data.get("tables", []):
        page = t.get("page")
        loc = Location("pdf", page=page, bbox=t.get("bbox"), table_index=next_id)
        parsed.tables.append(ParsedTable(next_id, f"Docling table (page {page})", loc, t["header"], t["rows"]))
        if page not in pages_with_rows:
            for ri, row in enumerate(t["rows"]):
                label = next((c for c in row if c and not is_number_token(c)), "")
                cells = [Cell(c, t["header"][ci] if ci < len(t["header"]) else None, Location("pdf", page=page, table_index=next_id, row=ri + 2))
                         for ci, c in enumerate(row) if c and is_number_token(c)]
                parsed.elements.append(Element("table_row", " | ".join(c for c in row if c), Location("pdf", page=page, table_index=next_id, row=ri + 2),
                                               label=label, cells=cells, table_id=next_id, context=[f"docling {data.get('docling_version')}"]))
        next_id += 1
    parsed.file_metadata["docling_version"] = data.get("docling_version")

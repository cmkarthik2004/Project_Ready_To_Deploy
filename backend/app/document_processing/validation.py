"""Upload validation: identify the real file format and reject unsafe files.

Checks performed (all before the file is accepted):
* extension is one of .pdf .docx .xlsx .xls .csv
* size within MAX_UPLOAD_MB and non-empty
* content signature (magic bytes) matches the extension
* PDF:  opens with PyMuPDF, not encrypted, page limit; `/Launch` actions are
        rejected; JavaScript / embedded files produce warnings (FinRAG never
        executes PDF content — it only extracts text).
* DOCX/XLSX (ZIP containers): required parts present, no VBA macro project,
        zip-bomb guard on total uncompressed size and compression ratio, no
        absolute or parent-directory member paths.
* XLS:  OLE2 signature.
* CSV:  decodable text, no NUL bytes.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from app.core.config import get_settings

ALLOWED = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
}
OLE2_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


class FileValidationError(ValueError):
    pass


@dataclass
class ValidationResult:
    file_format: str
    mime_type: str
    warnings: list[str] = field(default_factory=list)


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip(" .")
    return name[:255] or "upload"


def _check_zip(data: bytes, required: str, kind: str) -> list[str]:
    s = get_settings()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileValidationError(f"The {kind} file is corrupted (not a valid Office ZIP container).") from exc
    names = zf.namelist()
    if required not in names:
        raise FileValidationError(f"The file is not a valid {kind} document (missing {required}).")
    total = 0
    for info in zf.infolist():
        if info.filename.startswith("/") or ".." in info.filename.split("/"):
            raise FileValidationError("The file contains unsafe internal paths.")
        total += info.file_size
        if info.compress_size and info.file_size / max(info.compress_size, 1) > 200 and info.file_size > 10_000_000:
            raise FileValidationError("The file has a suspicious compression ratio (possible zip bomb).")
    if total > s.max_zip_uncompressed_mb * 1024 * 1024:
        raise FileValidationError(f"The file expands to more than {s.max_zip_uncompressed_mb} MB.")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise FileValidationError("Macro-enabled content (VBA) is not accepted.")
    warnings = []
    if any(n.startswith(("word/embeddings/", "xl/embeddings/")) for n in names):
        warnings.append("The document contains embedded objects; they were not opened.")
    if any("externalLink" in n for n in names):
        warnings.append("The workbook references external files; external links were not followed.")
    return warnings


def validate_upload(filename: str, data: bytes) -> ValidationResult:
    s = get_settings()
    ext = extension_of(filename)
    if ext not in ALLOWED:
        raise FileValidationError(f"Unsupported file type '.{ext}'. Allowed: PDF, DOCX, XLSX, XLS, CSV.")
    if not data:
        raise FileValidationError("The file is empty.")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise FileValidationError(f"The file exceeds the {s.max_upload_mb} MB limit.")

    warnings: list[str] = []
    if ext == "pdf":
        if b"%PDF-" not in data[:1024]:
            raise FileValidationError("The file has a .pdf extension but is not a PDF.")
        head_tail = data
        if re.search(rb"/Launch\b", head_tail):
            raise FileValidationError("The PDF contains a /Launch action and was rejected for safety.")
        if re.search(rb"/JavaScript\b|/JS\b", head_tail):
            warnings.append("The PDF contains JavaScript; it was ignored (FinRAG only extracts text).")
        if re.search(rb"/EmbeddedFile\b", head_tail):
            warnings.append("The PDF contains embedded files; they were not extracted.")
        import pymupdf

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise FileValidationError(f"The PDF is corrupted or unreadable: {exc}") from exc
        try:
            if doc.needs_pass:
                raise FileValidationError("The PDF is password-protected.")
            if doc.page_count == 0:
                raise FileValidationError("The PDF has no pages.")
            if doc.page_count > s.max_pdf_pages:
                raise FileValidationError(f"The PDF has {doc.page_count} pages (limit {s.max_pdf_pages}).")
        finally:
            doc.close()
    elif ext == "docx":
        if data[:4] != b"PK\x03\x04":
            raise FileValidationError("The file has a .docx extension but is not a Word document.")
        warnings += _check_zip(data, "word/document.xml", "Word")
    elif ext == "xlsx":
        if data[:4] != b"PK\x03\x04":
            raise FileValidationError("The file has a .xlsx extension but is not an Excel workbook.")
        warnings += _check_zip(data, "xl/workbook.xml", "Excel")
    elif ext == "xls":
        if data[:8] != OLE2_MAGIC:
            raise FileValidationError("The file has a .xls extension but is not a legacy Excel workbook.")
    elif ext == "csv":
        if b"\x00" in data[:100_000]:
            raise FileValidationError("The CSV file contains binary data.")
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                data[:200_000].decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if data[:4] in (b"PK\x03\x04", OLE2_MAGIC[:4]) or data[:5] == b"%PDF-":
            raise FileValidationError("The file has a .csv extension but is a binary document.")
    return ValidationResult(ext, ALLOWED[ext], warnings)

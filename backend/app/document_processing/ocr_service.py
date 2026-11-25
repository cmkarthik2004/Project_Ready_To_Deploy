"""OCR service (Tesseract via PyMuPDF).

A PDF page has a *text layer* when it was produced digitally; a scanned page is
just an image. FinRAG decides per page:

    needs_ocr(page)  -> fewer than OCR_MIN_CHARS extractable characters AND the page has images
    ocr_words(page)  -> word boxes recognised by Tesseract (same format as page.get_text("words"))

OCR output is always flagged (`Location.ocr=True`) and OCR'd financial values get
lower confidence and `needs_review`, because OCR confuses characters such as
"1"/"l", "0"/"O" and drops commas or parentheses.
"""
from __future__ import annotations

import os

import pymupdf

from app.core.config import get_settings

TESSDATA_CANDIDATES = ("/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata", "/usr/share/tessdata")


class OcrUnavailable(RuntimeError):
    pass


def tessdata_dir() -> str | None:
    """Directory holding Tesseract language data, or None if Tesseract is not installed."""
    for p in (os.environ.get("TESSDATA_PREFIX"), *TESSDATA_CANDIDATES):
        if p and os.path.isdir(p):
            return p
    return None


def available() -> bool:
    """PyMuPDF uses MuPDF's built-in Tesseract engine; only the language data must be installed."""
    return get_settings().ocr_enabled and tessdata_dir() is not None


def needs_ocr(page: pymupdf.Page, words: list | None = None) -> bool:
    words = page.get_text("words") if words is None else words
    return sum(len(w[4]) for w in words) < get_settings().ocr_min_chars and bool(page.get_images())


def ocr_words(page: pymupdf.Page, dpi: int = 200, language: str | None = None) -> list:
    """Run Tesseract on a page; returns PyMuPDF word tuples (x0, y0, x1, y1, word, block, line, word_no)."""
    td = tessdata_dir()
    if not get_settings().ocr_enabled or td is None:
        raise OcrUnavailable("OCR is disabled or Tesseract language data was not found")
    tp = page.get_textpage_ocr(language=language or get_settings().ocr_language, dpi=dpi, full=True, tessdata=td)
    return page.get_text("words", textpage=tp)

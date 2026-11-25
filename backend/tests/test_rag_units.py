"""Unit tests for the RAG building blocks split out of the pipeline.
Inputs are SYNTHETIC strings that exercise the logic; no database or LLM needed."""
import pymupdf

from app.document_processing import ocr_service
from app.rag.retriever import in_scope, passage_basis_is, question_scope
from app.rag.verification import check_numbers, verify_answer

SOURCES = [
    {"sid": "S1", "kind": "passage", "filename": "a.pdf", "location_text": "page 3", "text": "Revenue | 2030: 1,200 | 2029: 1,000"},
    {"sid": "M1", "kind": "extracted_metric", "filename": "a.pdf", "location_text": "page 3", "text": "\"Total assets\" = 5,000 (million)"},
]


def test_question_scope_and_in_scope():
    assert question_scope("Consolidated revenue for 2024-25?") == ("consolidated", ["2024-25"])
    assert question_scope("standalone profit") == ("standalone", [])
    assert in_scope("consolidated", ["2024-25"], "consolidated", "2024-25")
    assert not in_scope("consolidated", [], "standalone", "2024-25")
    assert not in_scope(None, ["2025"], None, "2023-24")
    assert in_scope(None, ["2025"], None, "As at 31st March, 2025")


def test_basis_guard_reads_passage_headers():
    assert passage_basis_is("[Context: STANDALONE FINANCIAL STATEMENTS | (in crore)]\nCash 82", "standalone")
    assert not passage_basis_is("[Context: Consolidated Balance Sheet]\nCash 106", "standalone")
    assert not passage_basis_is("standalone and consolidated results", "standalone")  # ambiguous -> not excluded


def test_verification_answered_and_digit_matching():
    v = verify_answer("Revenue was 1,200 in 2030 [S1].", SOURCES)
    assert v.status == "answered" and v.citations[0]["filename"] == "a.pdf"
    assert v.verification["unsupported_numbers"] == []  # "2030" is treated as a year


def test_verification_flags_arithmetic_and_uncited_numbers():
    v = verify_answer("Revenue grew by 200 [S1]; assets were 5,000.", SOURCES)
    assert v.status == "answered_with_warnings"
    assert v.verification["unsupported_numbers"] == ["200"]
    assert v.verification["numbers_in_uncited_sources"] == ["5,000"]


def test_verification_withholds_uncited_and_handles_insufficient():
    assert verify_answer("Revenue was 1,200.", SOURCES).status == "insufficient_evidence"
    v = verify_answer("INSUFFICIENT_EVIDENCE: no cash flow statement.", SOURCES)
    assert v.status == "insufficient_evidence" and "no cash flow statement" in v.answer
    assert verify_answer("See [S9].", SOURCES).verification["invalid_citations"] == ["S9"]
    v = verify_answer("Revenue was 1,200 [S1]; total 9,999 [C1].", SOURCES)   # one valid + one fabricated citation
    assert v.status == "insufficient_evidence" and "9,999" not in v.answer and v.verification["invalid_citations"] == ["C1"]
    unsupported, _ = check_numbers("margin 8.20%", [{"text": "8.2"}], [])
    assert unsupported == []  # trailing zero formatting


def test_ocr_detection_on_text_and_image_pages(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "A page with a real text layer, long enough to skip OCR.")
    assert not ocr_service.needs_ocr(doc[0])
    blank = doc.new_page()
    blank.insert_image(blank.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), 0))
    assert ocr_service.needs_ocr(blank)


def test_total_debt_question_detection():
    from app.rag.facts import TOTAL_DEBT_RE
    assert TOTAL_DEBT_RE.search("What were the consolidated total borrowings as at 31st March 2025?")
    assert TOTAL_DEBT_RE.search("total debt in 2030")
    assert not TOTAL_DEBT_RE.search("What were current borrowings?")


def test_question_year_must_appear_in_cited_sources():
    srcs = [{"sid": "S1", "kind": "passage", "filename": "a.pdf", "location_text": "p1", "text": "Share price | 2024-25: 2,883"}]
    v = verify_answer("The expected share price in 2030 is 2,883 [S1].", srcs, "What is the expected share price in 2030?")
    assert v.status == "insufficient_evidence" and "2030" in v.verification["reason"]
    ok = verify_answer("It was 2,883 [S1].", srcs, "What was the share price in 2025?")  # 2024-25 covers 2025
    assert ok.status == "answered"



def test_integer_matches_source_decimal_with_zero_fraction_only():
    src = [{"sid": "D1", "kind": "dashboard", "text": "Revenue growth = 10.0000 %. Previous FY2030: 15.0000. Assets 1,265.00. Margin 16.6008"}]
    assert check_numbers("Growth was 10% after 15% [D1]; assets 1265 [D1].", src, src)[0] == []
    assert check_numbers("Margin 16 [D1].", src, src)[0] == ["16"]          # 16.6008 is not 16
    assert check_numbers("It was 200 [D1].", [{"text": "FY2030 2,00,500"}], [])[0] == ["200"]   # no substring matches

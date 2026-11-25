"""Number parsing and upload validation. Inputs are synthetic tokens/bytes."""
import io
import zipfile
from decimal import Decimal

import pytest

from app.document_processing.validation import FileValidationError, sanitize_filename, validate_upload
from app.financial_analytics.numbers import digits_signature, is_number_token, parse_number


@pytest.mark.parametrize("tok,expected", [
    ("1,234", Decimal("1234")), ("12,34,567", Decimal("1234567")), ("(15,124)", Decimal("-15124")), ("-3.5", Decimal("-3.5")),
    ("51.47", Decimal("51.47")), ("12.5%", Decimal("12.5")), ("₹1,000", Decimal("1000")), ("−7", Decimal("-7")),
])
def test_parse_number(tok, expected):
    assert parse_number(tok) == expected


@pytest.mark.parametrize("tok", ["-", "—", "nil", "abc", "1,2,3x", "(12", "", None])
def test_not_numbers(tok):
    assert parse_number(tok) is None


def test_nil_is_not_zero():
    # a dash means "no amount"; it must never silently become 0
    assert parse_number("-") is None


def test_digits_signature():
    assert digits_signature(Decimal("980136.000000")) == "980136"
    assert digits_signature(Decimal("51.470")) == "5147"
    assert is_number_token("9,80,136") and not is_number_token("Revenue")


def _zip(members: dict[str, bytes]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in members.items():
            z.writestr(k, v)
    return b.getvalue()


def test_rejects_unknown_extension():
    with pytest.raises(FileValidationError, match="Unsupported"):
        validate_upload("x.exe", b"MZ....")


def test_rejects_empty_and_mismatch():
    with pytest.raises(FileValidationError, match="empty"):
        validate_upload("a.pdf", b"")
    with pytest.raises(FileValidationError, match="not a PDF"):
        validate_upload("a.pdf", b"hello world")
    with pytest.raises(FileValidationError, match="not a Word"):
        validate_upload("a.docx", b"%PDF-1.4 ...")
    with pytest.raises(FileValidationError, match="legacy Excel"):
        validate_upload("a.xls", b"PK\x03\x04....")
    with pytest.raises(FileValidationError, match="binary"):
        validate_upload("a.csv", b"a,b\x00,c")


def test_rejects_corrupt_pdf_and_launch_action():
    with pytest.raises(FileValidationError, match="corrupted|unreadable"):
        validate_upload("a.pdf", b"%PDF-1.4\n garbage without objects")
    with pytest.raises(FileValidationError, match="Launch"):
        validate_upload("a.pdf", b"%PDF-1.4\n1 0 obj << /Type /Action /S /Launch /F (calc.exe) >> endobj")


def test_rejects_macro_and_missing_parts():
    with pytest.raises(FileValidationError, match="Macro"):
        validate_upload("a.xlsx", _zip({"[Content_Types].xml": b"x", "xl/workbook.xml": b"x", "xl/vbaProject.bin": b"x"}))
    with pytest.raises(FileValidationError, match="missing"):
        validate_upload("a.docx", _zip({"[Content_Types].xml": b"x"}))
    with pytest.raises(FileValidationError, match="unsafe"):
        validate_upload("a.docx", _zip({"word/document.xml": b"x", "../evil.txt": b"x"}))


def test_size_limit(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    with pytest.raises(FileValidationError, match="limit"):
        validate_upload("a.csv", b"a,b\n1,2\n")


def test_accepts_valid_csv_and_sanitizes_names():
    r = validate_upload("ok.csv", b"Item,Amount\nA,1\n")
    assert r.file_format == "csv"
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert "<" not in sanitize_filename("a<b>.pdf")

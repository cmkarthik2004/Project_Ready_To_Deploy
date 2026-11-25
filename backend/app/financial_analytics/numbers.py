"""Parsing of numbers as printed in financial documents.

Handles: thousands separators in Western (1,234,567) and Indian lakh/crore
(12,34,567) grouping, parentheses for negatives "(1,234)", leading minus or
unicode minus, trailing percent, currency symbols, and nil markers ("-", "—").
Returns Decimal (never float) so no binary rounding enters calculations.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_CURRENCY_CHARS = "₹$€£¥"
NUM_RE = re.compile(
    r"^\(?[-−–]?[" + _CURRENCY_CHARS + r"]?\s?"
    r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?\)?%?$"
)
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
NIL_TOKENS = {"-", "—", "–", "nil", "Nil", "NIL"}


def is_number_token(tok: str) -> bool:
    t = tok.strip().rstrip(",;")
    return bool(t) and bool(NUM_RE.match(t))


def looks_like_year(tok: str) -> bool:
    return bool(YEAR_RE.match(tok.strip().rstrip(",")))


def parse_number(tok: str) -> Decimal | None:
    """Parse a printed number. Returns None for anything that is not a number.

    Nil markers ("-", "—") return None as well: a dash means "no amount" in the
    report and is NOT converted to zero automatically.
    """
    if tok is None:
        return None
    t = str(tok).strip().rstrip(",;")
    if not t or t in NIL_TOKENS:
        return None
    if not NUM_RE.match(t):
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    elif t.startswith("(") or t.endswith(")"):
        return None  # unbalanced parenthesis -> not a clean number
    t = t.rstrip("%")
    if t[:1] in "-−–":
        neg, t = not neg, t[1:]
    t = t.lstrip(_CURRENCY_CHARS).strip().replace(",", "")
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None
    return -v if neg else v


def is_percent(tok: str) -> bool:
    return str(tok).strip().endswith("%")


def digits_signature(value: Decimal) -> str:
    """Digits-only form used to check that a number in an LLM answer appears in evidence."""
    s = format(abs(value).normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", "")

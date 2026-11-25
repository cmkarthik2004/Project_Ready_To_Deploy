"""Automatic metadata detection for any uploaded financial document.

Every detector returns a `MetaField` dict:
    {"value": ..., "status": "detected" | "not_detected",
     "method": "<how>", "confidence": 0..1, "evidence": {"location": {...}, "snippet": "..."}}
Nothing is guessed: if no explicit textual evidence is found the field is
`not_detected` (value None). Users can later correct any field
(status becomes "user_corrected").
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict
from typing import Any

from app.document_processing.elements import Element, ParsedDocument

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

ORG_SUFFIX = (
    r"(?:Limited|Ltd\.?|Inc\.?|Incorporated|L\.?L\.?C\.?|PLC|plc|Corporation|Corp\.?|GmbH|AG|S\.A\.|N\.V\.|"
    r"Private\s+Limited|Pvt\.?\s+Ltd\.?|LLP|Co\.,?\s+Ltd\.?|Company|Holdings|Bank)"
)
ORG_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&'.\-]*|&)(?:\s+(?:[A-Z][A-Za-z0-9&'.\-]*|of|and|&|the)){0,6}\s+" + ORG_SUFFIX + r")(?![A-Za-z])"
)
ORG_STOP_START = {"The", "This", "Our", "For", "As", "In", "Of", "To", "And", "Notes", "Note", "Statement", "Consolidated",
                  "Standalone", "Total", "Board", "Annual", "Report", "Each", "All", "Such", "Its", "Any"}
AUDITOR_HINT = re.compile(r"chartered accountants|auditors?|firm registration|registration no", re.I)

DATE_DMY = r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+((?:19|20)\d{2})"
DATE_MDY = r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+((?:19|20)\d{2})"
PERIOD_RE = re.compile(
    r"(?P<kind>year|period|quarter|half[- ]year|six months|nine months|three months)\s+ended\s+(?:on\s+)?(?:(?P<dmy>" + DATE_DMY +
    r")|(?P<mdy>" + DATE_MDY + r"))",
    re.I,
)
ASAT_RE = re.compile(r"as\s+(?:at|of|on)\s+(?:(?P<dmy>" + DATE_DMY + r")|(?P<mdy>" + DATE_MDY + r"))", re.I)
FY_RE = re.compile(r"\b(?:FY|F\.Y\.|Financial Year|Fiscal Year|Fiscal)\s?['’]?((?:19|20)\d{2}\s?[-–/]\s?(?:(?:19|20)\d{2}|\d{2})|(?:19|20)?\d{2})\b", re.I)
YEAR_RANGE_RE = re.compile(r"\b((?:19|20)\d{2})\s?[-–]\s?(\d{2})\b")

CURRENCY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("INR", re.compile(r"₹|\bINR\b|\bRs\.?\s?\d|\bRupees?\b|\bRs\.? in\b", re.I)),
    ("USD", re.compile(r"\bUSD\b|US\$|\bU\.S\. dollars?\b|\bUS dollars?\b", re.I)),
    ("EUR", re.compile(r"€|\bEUR\b|\beuros?\b", re.I)),
    ("GBP", re.compile(r"£|\bGBP\b|\bpounds? sterling\b", re.I)),
    ("JPY", re.compile(r"\bJPY\b|\byen\b", re.I)),
    ("CNY", re.compile(r"\bCNY\b|\bRMB\b|\brenminbi\b", re.I)),
    ("AUD", re.compile(r"\bAUD\b|A\$", re.I)),
    ("CAD", re.compile(r"\bCAD\b|C\$", re.I)),
    ("SGD", re.compile(r"\bSGD\b|S\$", re.I)),
    ("AED", re.compile(r"\bAED\b|\bdirhams?\b", re.I)),
]
DOLLAR_RE = re.compile(r"\$\s?\d")

_CUR = r"(?:usd|us\$|eur|gbp|inr|jpy|chf|aud|cad|sgd|cny|aed|rs\.?|₹|\$|€|£)"
_U = lambda word: rf"\bin\s+(?:{_CUR}\s*)?{word}\b|\b{_CUR}\s*{word}\b"  # noqa: E731  "in USD million", "(EUR thousand)"
UNIT_PATTERNS: list[tuple[str, int, re.Pattern]] = [
    ("crore", 10_000_000, re.compile(_U(r"crores?") + r"|\bin\s+crores?\b|\bcrores?\)|\(\s*(?:₹|rs\.?|inr|c)\s*(?:in\s+)?crores?", re.I)),
    ("lakh", 100_000, re.compile(_U(r"lakhs?") + r"|\bin\s+lakhs?\b|\blakhs?\)|\bin\s+lacs?\b", re.I)),
    ("billion", 1_000_000_000, re.compile(_U(r"billions?") + r"|\bin\s+billions?\b|\bbillions?\)|\(\s*(?:\$|usd|eur|€|£)?\s*bn\)", re.I)),
    ("million", 1_000_000, re.compile(_U(r"millions?") + r"|\bin\s+millions?\b|\bmillions?\)|\(\s*(?:\$|usd|eur|€|£|inr|₹)?\s*(?:mn|mm|m)\)", re.I)),
    ("thousand", 1_000, re.compile(_U(r"thousands?") + r"|\bin\s+thousands?\b|\bthousands?\)|\(\s*['’]?000s?\s*\)|\bin\s+['’]000s?\b", re.I)),
]
UNIT_MULTIPLIER = {u: m for u, m, _ in UNIT_PATTERNS}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "annual_report": ["annual report", "integrated report", "directors' report", "board's report", "management discussion and analysis", "corporate governance report"],
    "audit_report": ["independent auditor's report", "independent auditors' report", "report on the audit", "basis for opinion", "key audit matters"],
    "balance_sheet": ["balance sheet", "statement of financial position"],
    "profit_and_loss": ["statement of profit and loss", "profit and loss account", "income statement", "statement of operations", "statement of comprehensive income"],
    "cash_flow_statement": ["cash flow statement", "statement of cash flows"],
    "budget_report": ["budget", "budgeted", "variance to budget", "budget vs actual", "forecast"],
    "expense_statement": ["expense report", "expense statement", "expenditure", "reimbursement", "expense category"],
    "revenue_report": ["revenue report", "sales report", "revenue by", "sales by"],
    "financial_analysis": ["ratio analysis", "financial analysis", "key financial ratios", "valuation"],
}


def field(value: Any, method: str, confidence: float, evidence: dict | None = None) -> dict:
    return {"value": value, "status": "detected", "method": method, "confidence": round(confidence, 3), "evidence": evidence}


def not_detected(reason: str) -> dict:
    return {"value": None, "status": "not_detected", "method": reason, "confidence": 0.0, "evidence": None}


def _date(day: str, month: str, year: str) -> dt.date | None:
    m = MONTHS.get(month.lower().rstrip("."))
    if not m:
        return None
    try:
        return dt.date(int(year), m, int(day))
    except ValueError:
        return None


def _match_date(m: re.Match) -> dt.date | None:
    g = m.groupdict()
    if g.get("dmy"):
        parts = re.match(DATE_DMY, g["dmy"])
        return _date(parts.group(1), parts.group(2), parts.group(3)) if parts else None
    if g.get("mdy"):
        parts = re.match(DATE_MDY, g["mdy"])
        return _date(parts.group(2), parts.group(1), parts.group(3)) if parts else None
    return None


def fiscal_year_label(end: dt.date) -> str:
    """Deterministic label from a fiscal year-end date (e.g. 31 Mar 2025 -> FY2024-25)."""
    if end.month == 12:
        return f"FY{end.year}"
    return f"FY{end.year - 1}-{str(end.year)[2:]}"


def _evidence(el: Element, start: int, end: int) -> dict:
    s = max(0, start - 60)
    return {"location": el.location.to_dict(), "snippet": el.text[s:end + 60]}


def _scan_elements(parsed: ParsedDocument, max_chars: int = 400_000):
    n = 0
    for el in parsed.elements:
        yield el
        n += len(el.text)
        if n > max_chars:
            break


def detect_organisation(parsed: ParsedDocument, filename: str) -> dict:
    counts: Counter[str] = Counter()
    first: dict[str, tuple[Element, int, int]] = {}
    penalty: dict[str, float] = defaultdict(float)
    for el in _scan_elements(parsed):
        for m in ORG_RE.finditer(el.text):
            name = " ".join(m.group(1).split()).strip(" ,.")
            words = name.split()
            if words[0] in ORG_STOP_START or len(words) < 2 or len(name) > 120:
                continue
            counts[name] += 1
            first.setdefault(name, (el, m.start(), m.end()))
            ctx = el.text[max(0, m.start() - 80): m.end() + 120]
            if AUDITOR_HINT.search(ctx) or name.endswith("LLP"):
                penalty[name] += 1
    for key in ("company", "author", "creator", "title"):
        v = parsed.file_metadata.get(key)
        if v:
            for m in ORG_RE.finditer(v):
                counts[" ".join(m.group(1).split())] += 3
    if not counts:
        return not_detected("no organisation name with a legal-entity suffix found")
    scored = {n: c - 2 * penalty[n] for n, c in counts.items()}
    best, score = max(scored.items(), key=lambda kv: kv[1])
    if score < 2:
        return not_detected("no organisation name occurred often enough to be identified reliably")
    total = sum(max(v, 0) for v in scored.values()) or 1
    ev = _evidence(*first[best]) if best in first else {"location": {"file_format": parsed.file_format}, "snippet": "document properties"}
    return field(best, f"legal-entity name pattern, {counts[best]} occurrence(s)", min(0.95, score / total + 0.2), ev)


def detect_period(parsed: ParsedDocument) -> tuple[dict, dict]:
    ends: Counter[tuple[str, dt.date]] = Counter()
    ev: dict[tuple[str, dt.date], dict] = {}
    fy_tokens: Counter[str] = Counter()
    fy_ev: dict[str, dict] = {}
    for el in _scan_elements(parsed):
        txt = el.text
        for m in PERIOD_RE.finditer(txt):
            d = _match_date(m)
            if d:
                k = (m.group("kind").lower(), d)
                ends[k] += 1
                ev.setdefault(k, _evidence(el, m.start(), m.end()))
        for m in FY_RE.finditer(txt):
            tok = re.sub(r"\s", "", m.group(1))
            fy_tokens[tok] += 1
            fy_ev.setdefault(tok, _evidence(el, m.start(), m.end()))
        for c in el.cells:
            if c.column_header:
                for m in YEAR_RANGE_RE.finditer(c.column_header):
                    tok = f"{m.group(1)}-{m.group(2)}"
                    fy_tokens[tok] += 1
                    fy_ev.setdefault(tok, {"location": c.location.to_dict(), "snippet": c.column_header})
    period = not_detected("no 'year/period/quarter ended <date>' statement found")
    fiscal = not_detected("no fiscal-year expression found")
    if ends:
        # The reporting period is the most frequently stated period; ties -> latest date.
        (kind, d), c = max(ends.items(), key=lambda kv: (kv[1], kv[0][1]))
        label = f"{kind.capitalize()} ended {d.day} {d.strftime('%B')} {d.year}"
        total = sum(ends.values())
        period = field({"label": label, "end_date": d.isoformat(), "kind": kind}, f"'{kind} ended <date>' phrase, {c} of {total} mentions", min(0.95, c / total + 0.3), ev[(kind, d)])
        if kind == "year":
            fiscal = field(fiscal_year_label(d), "derived from fiscal year-end date", 0.9, ev[(kind, d)])
    if fiscal["status"] == "not_detected" and fy_tokens:
        tok, c = fy_tokens.most_common(1)[0]
        fiscal = field(f"FY{tok}" if not tok.upper().startswith("FY") else tok, f"fiscal-year token, {c} occurrence(s)", min(0.8, 0.3 + c / max(sum(fy_tokens.values()), 1)), fy_ev[tok])
    return period, fiscal


def detect_currency(parsed: ParsedDocument) -> dict:
    """Reporting currency is taken from table unit statements / column headers
    (e.g. "(US$ in million)", "Amount (EUR)"). Currencies that only appear in
    narrative text (bond issues, FX rates, ...) do not decide the reporting
    currency: if that is all we have, the field is marked `uncertain`."""
    header: Counter[str] = Counter()
    prose: Counter[str] = Counter()
    ev: dict[str, dict] = {}
    unit_lines = 0
    for el in _scan_elements(parsed):
        txt = el.text
        is_unit_line = len(txt) < 160 and any(rx.search(txt) for _, _, rx in UNIT_PATTERNS)
        unit_lines += is_unit_line
        for code, rx in CURRENCY_PATTERNS:
            hits = rx.findall(txt)
            if hits:
                (header if is_unit_line else prose)[code] += len(hits)
                if is_unit_line or code not in ev:
                    m = rx.search(txt)
                    ev[code] = _evidence(el, m.start(), m.end())
        if is_unit_line and re.search(r"\$", txt) and not any(rx.search(txt) for c, rx in CURRENCY_PATTERNS if c in ("USD", "AUD", "CAD", "SGD")):
            header["$"] += 1
            ev.setdefault("$", _evidence(el, txt.index("$"), txt.index("$") + 1))
        for c in el.cells:
            for code, rx in CURRENCY_PATTERNS:
                if c.column_header and rx.search(c.column_header):
                    header[code] += 1
                    ev.setdefault(code, {"location": c.location.to_dict(), "snippet": c.column_header})
    if header and header.most_common(1)[0][1] < max(1, unit_lines) * 0.5 and unit_lines >= 4:
        code, c = header.most_common(1)[0]
        return {"value": None, "status": "uncertain",
                "method": f"{code} is stated in only {c} of {unit_lines} table unit statements; the other unit statements name no "
                          f"recognisable currency (the symbol may be font-encoded). Please confirm the currency.",
                "confidence": 0.0, "evidence": ev.get(code), "candidates": [k for k, _ in header.most_common(4)]}
    if header:
        code, c = header.most_common(1)[0]
        share = c / sum(header.values())
        conf = min(0.95, 0.5 + share * 0.45)
        method = f"currency stated in table unit lines/headers, {c} occurrence(s)"
        if code == "$":
            method += " (dollar sign without country: which dollar is not specified)"
            conf = 0.5
        if len(header) > 1:
            method += "; other currencies in headers: " + ", ".join(f"{k}×{v}" for k, v in header.most_common()[1:4])
        return field(code, method, conf, ev[code])
    if prose:
        cands = ", ".join(f"{k}×{v}" for k, v in prose.most_common(4))
        return {"value": None, "status": "uncertain", "method": f"no currency stated in table headers; currencies mentioned in text: {cands}",
                "confidence": 0.0, "evidence": ev.get(prose.most_common(1)[0][0]), "candidates": [k for k, _ in prose.most_common(4)]}
    return not_detected("no explicit currency symbol or code found")


def unit_from_text(text: str) -> str | None:
    for unit, _, rx in UNIT_PATTERNS:
        if rx.search(text):
            return unit
    return None


def detect_unit(parsed: ParsedDocument) -> dict:
    counts: Counter[str] = Counter()
    ev: dict[str, dict] = {}
    for el in _scan_elements(parsed):
        for unit, _, rx in UNIT_PATTERNS:
            m = rx.search(el.text)
            if m and el.kind in ("heading", "paragraph", "text"):
                counts[unit] += 1
                ev.setdefault(unit, _evidence(el, m.start(), m.end()))
    if not counts:
        return not_detected("no unit statement such as '(in millions)' found")
    unit, c = counts.most_common(1)[0]
    return field(unit, f"unit statement, {c} occurrence(s); per-table units are detected separately", min(0.9, 0.3 + c / sum(counts.values()) * 0.6), ev[unit])


def detect_category(parsed: ParsedDocument, filename: str) -> dict:
    text = (filename + "\n" + parsed.full_text(limit=150_000)).lower()
    scores = {cat: sum(text.count(k) for k in kws) for cat, kws in CATEGORY_KEYWORDS.items()}
    scores = {k: v for k, v in scores.items() if v}
    if not scores:
        return not_detected("no category keywords found")
    statements = sum(scores.get(k, 0) > 0 for k in ("balance_sheet", "profit_and_loss", "cash_flow_statement"))
    if scores.get("annual_report", 0) >= 2 and statements >= 2:
        best = "annual_report"
    elif statements >= 2 and scores.get("annual_report", 0) < 2:
        best = "financial_statements"
    else:
        best = max(scores.items(), key=lambda kv: kv[1])[0]
    total = sum(scores.values())
    return field(best, "keyword scoring: " + ", ".join(f"{k}={v}" for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:4]),
                 min(0.9, 0.3 + scores.get(best, total / 2) / total * 0.6))


def detect_all(parsed: ParsedDocument, filename: str) -> dict[str, dict]:
    period, fiscal = detect_period(parsed)
    return {
        "organisation": detect_organisation(parsed, filename),
        "reporting_period": period,
        "fiscal_year": fiscal,
        "category": detect_category(parsed, filename),
        "currency": detect_currency(parsed),
        "unit": detect_unit(parsed),
    }

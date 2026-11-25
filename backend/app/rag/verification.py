"""Answer verification and citation generation.

The LLM must cite sources inline as [S#] (passages), [M#] (extracted values),
[C#] (Python calculations), [D#] (dashboard data) or [H#] (hypothetical scenarios). After generation FinRAG checks:

* every cited id exists among the sources that were actually provided;
* every multi-digit number in the answer occurs (digits only, so "9,80,136" ==
  "980136") in one of the CITED sources. Numbers found only in uncited sources,
  or nowhere, are reported.

Outcome:
* `insufficient_evidence` — the model said INSUFFICIENT_EVIDENCE, or cited nothing
  valid, or the question names a year that none of the cited sources mentions (the
  answer is withheld; the raw output is kept for audit);
* withheld as `insufficient_evidence` as well when a cited source id was never provided (fabricated citation);
* `answered_with_warnings` — numbers not found in the cited sources;
* `answered` — all checks passed.

This catches invented numbers and LLM arithmetic, but NOT a correct number taken
from the wrong line item / basis (see docs/EVALUATION.md): that is why retrieval
also scopes by basis and period.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
NUM_IN_ANSWER = re.compile(r"(?<![\w\[])[-−(]?\d[\d,]*(?:\.\d+)?%?")
CITE_RE = re.compile(r"\[([SMCDH]\d{1,3})\]")
NUM_IN_SOURCE = re.compile(r"[\d][\d,]*(?:\.\d+)?")
CITATION_FIELDS = ("kind", "document_id", "filename", "organisation", "location", "location_text", "chunk_id", "metric_id")


def digits(s: str) -> str:
    return re.sub(r"[^\d]", "", s)


@dataclass
class Verified:
    status: str
    answer: str
    citations: list[dict] = field(default_factory=list)
    verification: dict = field(default_factory=dict)


def check_numbers(answer: str, cited_sources: list[dict], all_sources: list[dict]) -> tuple[list[str], list[str]]:
    """Returns (unsupported numbers, numbers present only in uncited sources)."""
    def forms(w: str) -> str:
        # "15.0000" in a source also counts as the integer 15 (exact numeric equality, not a substring match)
        if "." in w and set(w.split(".")[-1]) <= {"0"}:
            return digits(w) + " " + digits(w.split(".")[0])
        return digits(w)
    cited_digits = " ".join(forms(w) for src in cited_sources for w in NUM_IN_SOURCE.findall(src["text"]))
    all_digits = " ".join(forms(w) for src in all_sources for w in NUM_IN_SOURCE.findall(src["text"]))
    unsupported, uncited = [], []
    for tok in NUM_IN_ANSWER.findall(CITE_RE.sub(" ", answer)):
        d = digits(tok)
        if len(d) < 2 or re.fullmatch(r"(19|20)\d{2}", d) or re.fullmatch(r"(19|20)\d{2}\d{2}", d):
            continue  # single digits, years and fiscal-year labels like 2024-25
        # trailing-zero tolerance only for decimals ("8.20" in the answer vs "8.2" in a source);
        # never for integers, otherwise "200" would match the "2" of "2030"
        dd = (d.rstrip("0") or d) if "." in tok else d
        if re.search(rf"(?<!\d){d}(?!\d)", cited_digits) or (dd != d and re.search(rf"(?<!\d){dd}(?!\d)", cited_digits)):
            continue
        (uncited if re.search(rf"(?<!\d){d}(?!\d)", all_digits) else unsupported).append(tok.strip())
    return unsupported, uncited


YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def missing_question_years(question: str, cited_sources: list[dict]) -> list[str]:
    """Years named in the question that no cited source mentions (e.g. a forecast for 2030
    answered from a 2025 report). Two-digit fiscal suffixes ('2024-25') count as mentions of 2025."""
    years = {m.group(0) for m in YEAR_RE.finditer(question)}
    if not years:
        return []
    text = " ".join(src["text"] for src in cited_sources)
    present = {m.group(0) for m in YEAR_RE.finditer(text)}
    present |= {f"{m.group(1)[:2]}{m.group(2)}" for m in re.finditer(r"\b((?:19|20)\d{2})\s?[-–/]\s?(\d{2})\b", text)}
    return sorted(years - present)


def verify_answer(raw: str, sources: list[dict], question: str | None = None) -> Verified:
    by_sid = {x["sid"]: x for x in sources}
    cited = list(dict.fromkeys(CITE_RE.findall(raw)))
    valid = [c for c in cited if c in by_sid]
    invalid = [c for c in cited if c not in by_sid]
    unsupported, uncited = check_numbers(raw, [by_sid[c] for c in valid], sources)
    verification = {"cited": cited, "valid_citations": valid, "invalid_citations": invalid,
                    "unsupported_numbers": unsupported, "numbers_in_uncited_sources": uncited, "raw_model_output": raw}
    if raw.strip().startswith(INSUFFICIENT):
        status = "insufficient_evidence"
        answer = "Sufficient evidence was not found in the selected documents. " + raw.split(":", 1)[-1].strip()
    elif not valid:
        status = "insufficient_evidence"
        answer = ("The model produced an answer without citing the provided sources, so it is not shown. "
                  "Sufficient evidence could not be confirmed in the selected documents.")
        verification["reason"] = "no valid citations"
    elif invalid:
        # Citing a source that was never provided is a fabricated citation: the whole answer is withheld.
        status = "insufficient_evidence"
        answer = (f"The model cited source(s) that were not provided ({', '.join(invalid)}), so its answer cannot be trusted and "
                  "is withheld. The retrieved evidence and the model's raw output are in the verification record.")
        verification["reason"] = f"fabricated citation(s) {invalid}"
    elif question and (missing := missing_question_years(question, [by_sid[c] for c in valid])):
        status = "insufficient_evidence"
        answer = (f"Sufficient evidence was not found: the question refers to {', '.join(missing)}, but none of the cited "
                  "sources mentions that period. The model's answer is withheld (see the verification record).")
        verification["reason"] = f"question period(s) {missing} not present in cited sources"
    else:
        answer = raw
        status = "answered" if not unsupported else "answered_with_warnings"
    citations = [{"sid": c, **{k: v for k, v in by_sid[c].items() if k in CITATION_FIELDS}, "snippet": by_sid[c]["text"][:700]} for c in valid]
    return Verified(status, answer, citations, verification)

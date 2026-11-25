"""Dashboard-aware sources for the AI assistant.

The dashboard is rebuilt on the server from the user's filters (chart data sent by a browser is never trusted), then
turned into numbered sources the model must cite:

* [D#] dashboard data — KPI cards and chart data points, each with origin (reported / calculated), validation status and
  the document location of the printed value;
* [H#] hypothetical scenarios — computed in Python when the question asks "what if X grows/falls by N%". The result is
  labelled as an assumption, never as a reported or forecast figure.

Document passages and extracted values ([S#]/[M#]/[C#]) are added by the normal RAG pipeline for questions about
disclosures and explanations. The total size is capped to fit the model's context window.
"""
from __future__ import annotations

import re
from decimal import Decimal

MAX_DASHBOARD_CHARS = 5200
SCENARIO_RE = re.compile(r"\b(revenue|sales|profit|pat|ebitda|expenses?|costs?)\b[^.?]{0,40}?\b(grows?|increases?|rises?|goes up|falls?|"
                         r"declines?|decreases?|drops?|goes down)\s+(?:by\s+)?(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)", re.I)
SCENARIO_RE_2 = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)\s+(increase|growth|rise|decrease|decline|fall|drop)\s+in\s+(revenue|sales|profit|ebitda|expenses?|costs?)", re.I)
KPI_FOR = {"revenue": "revenue", "sales": "revenue", "profit": "pat", "pat": "pat", "ebitda": "ebitda", "expense": "expenses", "expenses": "expenses",
           "cost": "expenses", "costs": "expenses"}


def _s(d: Decimal) -> str:
    q = d.quantize(Decimal("0.01"))
    t = format(q.normalize(), "f")
    return t.rstrip("0").rstrip(".") if "." in t else t


def _where(p: dict) -> str:
    if p.get("kind") == "calculated":
        return f"calculated in Python: {p.get('formula')}"
    return f"{p.get('filename')}, {p.get('location_text')}; {p.get('validation_status')}" + (", inferred mapping" if p.get("value_origin") == "inferred_mapping" else "")


def kpi_text(k: dict) -> str:
    unit = " ".join(x for x in (k.get("currency"), k.get("unit")) if x) or "unit not stated"
    t = f"KPI '{k['label']}' = {k['value']} {unit} for FY{k['fiscal_year']} ({k['origin']}; {_where(k['sources'][0])})."
    if k.get("previous") is not None:
        t += f" Previous FY{k['previous_fiscal_year']}: {k['previous']}."
    if k.get("change_pct") is not None:
        t += f" Change vs previous year: {k['change_pct']}% (calculated in Python from validated inputs)."
    elif k.get("change_note"):
        t += f" Change: {k['change_note']}."
    return t


def chart_text(c: dict, detailed: bool) -> str:
    rows = []
    for r in c["rows"]:
        vals = []
        for s in c["series"]:
            if r.get(s["key"]) is None:
                continue
            p = c["points"].get(f"{r['x']}|{s['key']}", {})
            shown = p.get("value") if p.get("value") is not None else r.get(s["key"])
            vals.append(f"{s['label']} {shown}" + (f" [{_where(p)}]" if detailed and p else ""))
        if vals:
            rows.append(f"{r['x']}: " + "; ".join(vals))
    origin = "calculated" if any(s["origin"] == "calculated" for s in c["series"]) else "reported"
    text = f"Chart '{c['title']}' ({c['description']}; unit: {c['unit']}; {origin} values). Data: " + " | ".join(rows)
    # Year-over-year changes for trend charts, computed here in Python (only between validated/verified values), so the
    # model never has to compute them itself.
    if detailed and origin == "reported" and all(str(r["x"]).startswith("FY") for r in c["rows"]):
        changes = []
        for s in c["series"]:
            prev = None
            for r in c["rows"]:
                p = c["points"].get(f"{r['x']}|{s['key']}")
                if p and prev and p.get("validation_status") in ("validated", "verified") and prev[1].get("validation_status") in ("validated", "verified"):
                    a, b = Decimal(prev[1]["value"]), Decimal(p["value"])
                    if a != 0:
                        changes.append(f"{s['label']} {prev[0]}→{r['x']}: {_s((b - a) / abs(a) * 100)}%")
                if p:
                    prev = (r["x"], p)
        if changes:
            text += " | Year-over-year change (calculated in Python from validated values): " + "; ".join(changes)
    return text


def _relevance(question: str, c: dict) -> int:
    q = question.lower()
    words = set(re.findall(r"[a-z]{4,}", (c["title"] + " " + " ".join(s["label"] for s in c["series"])).lower()))
    return sum(1 for w in words if w in q)


def dashboard_sources(d: dict, question: str, chart_id: str | None) -> list[dict]:
    out: list[dict] = []
    budget = MAX_DASHBOARD_CHARS

    def add(text: str, loc: str) -> None:
        nonlocal budget
        if budget - len(text) < 0 and out:
            return
        budget -= len(text)
        out.append({"sid": f"D{len(out) + 1}", "kind": "dashboard", "filename": "Dashboard", "location_text": loc, "text": text})

    focus = next((c for c in d["charts"] if c["id"] == chart_id), None) if chart_id else None
    if focus:
        add(chart_text(focus, detailed=True), f"chart: {focus['title']}")
    for k in d["kpis"]:
        add(kpi_text(k), f"KPI: {k['label']}")
    ranked = sorted((c for c in d["charts"] if c is not focus), key=lambda c: -_relevance(question, c))
    for c in ranked:
        add(chart_text(c, detailed=False), f"chart: {c['title']}")
    notes = [f"{p['label']} (FY{p['fiscal_year']}) not computed: {p['reason']}" for p in d["pending_verification"]] + d["limitations"]
    if notes:
        add("Dashboard notes (missing or not yet computed items): " + " | ".join(notes)[:1200], "dashboard notes")
    return out


def scenario_sources(d: dict, question: str, start: int = 1) -> list[dict]:
    """'What happens if revenue grows by 10%?' → Python result labelled as a hypothetical assumption."""
    m = SCENARIO_RE.search(question)
    if m:
        what, verb, pct = m.group(1).lower(), m.group(2).lower(), Decimal(m.group(3))
    else:
        m2 = SCENARIO_RE_2.search(question)
        if not m2:
            return []
        pct, verb, what = Decimal(m2.group(1)), m2.group(2).lower(), m2.group(3).lower()
    sign = -1 if re.match(r"(fall|decline|decrease|drop|goes down)", verb) else 1
    kid = KPI_FOR.get(what.rstrip("s") if what.rstrip("s") in KPI_FOR else what)
    out: list[dict] = []
    for k in d["kpis"]:
        if not k["id"].endswith(f":{kid}") or k["origin"] == "calculated":
            continue
        base = Decimal(k["value"])
        factor = Decimal(1) + sign * pct / Decimal(100)
        new = base * factor
        unit = " ".join(x for x in (k.get("currency"), k.get("unit")) if x) or "unit not stated"
        text = (f"HYPOTHETICAL SCENARIO (assumption, not a reported figure and not a forecast): if {k['label']} for FY{k['fiscal_year']} "
                f"({k['value']} {unit}, reported) changed by {'+' if sign > 0 else '-'}{_s(pct)}%, it would be {_s(new)} {unit} "
                f"(difference {_s(new - base)}). Computed in Python: {k['value']} × {_s(factor)}.")
        ent = k["id"].split(":")[0]
        margin = next((x for x in d["kpis"] if x["id"] == f"{ent}:net_margin"), None)
        if kid == "revenue" and margin:
            implied = new * Decimal(margin["value"]) / 100
            text += (f" Holding the FY{margin['fiscal_year']} net profit margin of {margin['value']}% constant (an assumption: costs "
                     f"would scale with revenue), implied net profit would be {_s(implied)} {unit}.")
        out.append({"sid": f"H{start + len(out)}", "kind": "scenario", "filename": "Scenario (hypothetical)",
                    "location_text": "computed by FinRAG (Python) from dashboard values", "text": text})
    return out


DASHBOARD_RULES = """
Additional rules for dashboard questions:
9. [D#] sources are the user's dashboard: KPI cards and chart data built from the extracted values (each states whether
   it is reported or calculated, and where it was printed). Use them to describe trends, compare years and explain charts;
   name the data points (year and value) behind each conclusion.
10. [H#] sources are hypothetical scenarios computed in Python. Present them clearly as assumptions ("if … then …"),
    never as reported figures or forecasts, and state the assumption used.
11. For "risks", "attention" or "summary" questions, base every point on the cited data (e.g. a decline, a low or
    negative value, a failed reconciliation, a value that is not yet verified). Do not invent causes: explain a change
    only if a document passage [S#] states the reason; otherwise say the documents provided do not explain it.
12. If a metric is not on the dashboard and not in any source, say it is not available; never estimate it."""

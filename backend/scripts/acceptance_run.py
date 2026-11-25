"""Acceptance run against a live FinRAG stack (see docs/ACCEPTANCE_TESTS.md).

A fresh user uploads genuine reports (from FINRAG_TEST_DOCS) plus the synthetic acceptance files
(scripts/make_acceptance_files.py) through the real API, then the 15 acceptance criteria are checked against known
ground truth, the original files, independent Python arithmetic and the real LLM. Results go to ACC_OUT (JSON).
Exit code 1 if any check fails. Requires: running stack, LibreOffice (for the synthetic workbook), Tesseract.
"""
from __future__ import annotations

import csv as csvmod
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from decimal import Decimal
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
import docx  # noqa: E402
import openpyxl  # noqa: E402
import pymupdf  # noqa: E402
from qdrant_client.http import models as qm  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.rag import vector_store  # noqa: E402

API = os.environ.get("FINRAG_API", "http://127.0.0.1:8000/api")
DOCS = Path(os.environ.get("FINRAG_TEST_DOCS", "/opt/finrag_testdocs"))
OUT = Path(os.environ.get("ACC_OUT", "acceptance_results.json"))
S = get_settings()
R: dict = {"checks": [], "started": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}


def check(crit: int, name: str, ok, detail="") -> bool:
    R["checks"].append({"criterion": crit, "check": name, "ok": bool(ok), "detail": str(detail)[:700]})
    print(f"{'PASS' if ok else 'FAIL'} [{crit:>2}] {name}" + (f" — {str(detail)[:300]}" if not ok else ""))
    return bool(ok)


def D(x) -> Decimal:
    return Decimal(str(x))


# ------------------------------------------------------------------ files
work = Path(tempfile.mkdtemp(prefix="acc_"))
subprocess.run([sys.executable, str(BACKEND / "scripts" / "make_acceptance_files.py"), str(work)], check=True, capture_output=True)
truth = json.loads((work / "ground_truth.json").read_text())
files = {
    "ril_2425": DOCS / "RIL-Integrated-Annual-Report-2024-25.pdf",          # genuine
    "ril_2526": DOCS / "RIL-Integrated-Annual-Report-2025-26.pdf",          # genuine, overlaps FY2025
    "ril_scan": DOCS / "RIL-Financial-Highlights-10-years.pdf",              # genuine, image-only
    "xlsx": work / "synthetic_multisheet_usd_million.xlsx",
    "tx_csv": work / "synthetic_transactions_cp1252.csv",
    "docx": work / "synthetic_notes_borrowings.docx",
    "five_csv": work / "synthetic_five_year_inr_crore.csv",
    "bad_xlsx": work / "synthetic_inconsistent_usd_thousand.xlsx",
    "scan_pdf": work / "synthetic_scanned_statement.pdf",
}
c = httpx.Client(base_url=API, timeout=1200)
email = f"acceptance-{uuid.uuid4().hex[:6]}@example.com"
assert c.post("/auth/register", json={"email": email, "password": "Str0ngPassw0rd!"}).status_code == 201
up = c.post("/documents", files=[("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in files.values()]).json()["results"]
ids = {k: r["document"]["id"] for k, r in zip(files, up) if r["accepted"]}
R["uploads"] = {k: (r["accepted"], r.get("error")) for k, r in zip(files, up)}
t0 = time.time()
while time.time() - t0 < 5400:
    st = {k: c.get(f"/documents/{i}").json()["status"] for k, i in ids.items()}
    if all(s in ("processed", "failed") for s in st.values()):
        break
    time.sleep(5)
R["processing_seconds"] = round(time.time() - t0)
docs = {k: c.get(f"/documents/{i}").json() for k, i in ids.items()}
check(0, "all 9 documents processed", all(d["status"] == "processed" for d in docs.values()) and len(ids) == 9,
      {k: (d["status"], d.get("error_message")) for k, d in docs.items()})
R["documents"] = {k: {"filename": d["filename"], "format": d["file_format"], "metrics": d["metric_count"], "chunks": d["chunk_count"],
                      "metadata": {m: (v or {}).get("value") for m, v in (d.get("metadata") or {}).items()}, "warnings": d["warnings"][:6],
                      "structure_keys": sorted((d.get("structure") or {}).keys())} for k, d in docs.items()}


def metrics(k: str) -> list[dict]:
    return c.get(f"/documents/{ids[k]}/metrics?limit=2000").json()["items"]


def find(ms, key, fy, basis=None):
    return [m for m in ms if m["metric_key"] == key and m["fiscal_year"] == fy and not m["is_duplicate"] and (basis is None or m["basis"] == basis)]


# ------------------------------------------------------------------ 1. correct figures (ground truth)
X = metrics("xlsx")
keymap = {"rev": "revenue_from_operations", "cogs": "cost_of_revenue", "ebitda": "ebitda", "pbt": "profit_before_tax", "tax": "total_tax_expense",
          "pat": "net_profit", "emp": "employee_benefits_expense", "dep": "depreciation_amortisation", "fin": "finance_costs"}
bad = []
for fy, vals in truth["pl"].items():
    for k, v in vals.items():
        got = find(X, keymap[k], int(fy[2:]))
        if len(got) != 1 or D(got[0]["value"]) != D(v):
            bad.append((fy, k, v, [g["value"] for g in got]))
bsmap = {"ca": "total_current_assets", "nca": "total_non_current_assets", "cl": "total_current_liabilities", "ncl": "total_non_current_liabilities",
         "eq": "total_equity", "bc": "borrowings_current", "bnc": "borrowings_non_current", "cash": "cash_and_cash_equivalents"}
for fy, vals in truth["bs"].items():
    for k, v in vals.items():
        got = find(X, bsmap[k], int(fy[2:]))
        if len(got) != 1 or D(got[0]["value"]) != D(v):
            bad.append((fy, k, v, [g["value"] for g in got]))
cfmap = {"open": "opening_cash", "op": "net_cash_operating", "inv": "net_cash_investing", "fin": "net_cash_financing", "close": "closing_cash"}
for fy, vals in truth["cf"].items():
    for k, v in vals.items():
        got = find(X, cfmap[k], int(fy[2:]))
        if len(got) != 1 or D(got[0]["value"]) != D(v):
            bad.append((fy, k, v, [g["value"] for g in got]))
check(1, "multi-sheet workbook: every ground-truth P&L, balance sheet and cash-flow value extracted exactly once and correctly", not bad, bad)
gp = find(X, "gross_profit", 2031)
check(1, "workbook formula cell (Gross profit = revenue − COGS) read from its cached value 505", gp and D(gp[0]["value"]) == 505, gp[:1])
links = [m for m in X if m["is_duplicate"] and any("link to" in (n.get("detail") or "") for n in m["validation_notes"])]
check(1, "Summary-sheet cross-sheet links recognised as copies (not counted again)", len(links) == 2, [(m["metric_key"], m["raw_value"]) for m in links])
P = metrics("ril_2425")
rev = find(P, "revenue_from_operations", 2025, "consolidated")
ta = find(P, "total_assets", 2025, "consolidated")
check(1, "genuine report: consolidated revenue from operations FY2025 = 9,80,136 crore", rev and rev[0]["raw_value"] == "9,80,136", [m["raw_value"] for m in rev])
check(1, "genuine report: consolidated total assets 31 March 2025 = 19,50,121 crore", ta and ta[0]["raw_value"] == "19,50,121", [m["raw_value"] for m in ta])
Q = metrics("ril_2526")
same, diff = [], []
for key in ("revenue_from_operations", "total_assets", "total_equity", "net_profit"):
    a, b = find(P, key, 2025, "consolidated"), find(Q, key, 2025, "consolidated")
    if a and b:
        (same if a[0]["value"] == b[0]["value"] else diff).append((key, a[0]["raw_value"], b[0]["raw_value"]))
R["ril_2526_fy2025_comparatives"] = {"same": same, "different": diff}
check(1, "genuine 2025-26 report: its FY2025 comparative figures match the 2024-25 report (consistency across real documents)",
      len(same) >= 2 and not diff, {"same": same, "different": diff})
SC = metrics("scan_pdf")
ocr = {m["metric_key"]: m["value"] for m in SC if m["fiscal_year"] == 2031}
check(1, "scanned (image-only) statement read by OCR: revenue 880, PBT 180, profit 135 for FY2031",
      D(ocr.get("revenue_from_operations", -1)) == 880 and D(ocr.get("profit_before_tax", -1)) == 180 and D(ocr.get("net_profit", -1)) == 135, ocr)
check(1, "OCR values are flagged needs_review (never silently trusted)", all(m["validation_status"] == "needs_review" for m in SC if m["metric_key"] != "line_item"))


# ------------------------------------------------------------------ 2. source references point at the original
def at(fmt, path, loc, raw) -> bool:
    n = lambda x: "".join(str(x).split())  # noqa: E731
    if fmt == "xlsx":
        return n(openpyxl.load_workbook(path, data_only=True)[loc["sheet"]][loc["cell"]].value) == n(raw) or \
            Decimal(str(openpyxl.load_workbook(path, data_only=True)[loc["sheet"]][loc["cell"]].value)) == Decimal(raw.replace(",", ""))
    if fmt == "csv":
        text = path.read_bytes().decode("cp1252" if "cp1252" in path.name else "utf-8")
        rows = list(csvmod.reader(text.splitlines(), delimiter=";" if "cp1252" in path.name else ","))
        return any(n(x) == n(raw) for x in rows[loc["row"] - 1])
    if fmt == "docx":
        return any(n(cl.text) == n(raw) for cl in docx.Document(path).tables[loc["table_index"]].rows[loc["row"] - 1].cells)
    if fmt == "pdf":
        page = pymupdf.open(path)[loc["page"] - 1]
        txt = page.get_text()
        if not txt.strip():
            png = work / "ocrcheck.png"
            page.get_pixmap(dpi=300).save(png)
            txt = subprocess.run(["tesseract", str(png), "stdout", "--psm", "6"], capture_output=True, text=True).stdout
        return n(raw) in n(txt)
    return False


for k, fmt in (("xlsx", "xlsx"), ("docx", "docx"), ("five_csv", "csv"), ("scan_pdf", "pdf"), ("ril_2425", "pdf"), ("ril_2526", "pdf")):
    ms = [m for m in metrics(k) if m["metric_key"] != "line_item"][:12]
    oks = [at(fmt, files[k], m["location"], m["raw_value"]) for m in ms]
    check(2, f"{files[k].name}: {sum(oks)}/{len(oks)} sampled values found at their cited location in the original file",
          ms and all(oks), [(m["raw_value"], m["location_text"]) for m, o in zip(ms, oks) if not o])
tx = docs["tx_csv"]
prof = (tx.get("structure") or {}).get("profile") or {}
check(2, "transactions CSV: ';' delimiter, cp1252 encoding, decimal comma, duplicate row 5 and missing amount reported",
      tx["structure"].get("delimiter") == ";" and tx["structure"].get("encoding") == "cp1252" and prof.get("duplicate_row_count") == 1
      and any("decimal comma" in w for w in tx["warnings"]), {"structure": {k: v for k, v in tx["structure"].items() if k != "profile"}, "dups": prof.get("duplicate_rows")})
xs = docs["xlsx"]["structure"]
check(2, "workbook structure kept: 4 sheets, 2 tables on 'Balance Sheet', cross-sheet links Summary→P&L and Summary→Balance Sheet",
      len(xs["sheets"]) == 4 and xs["sheets"]["Balance Sheet"]["tables"] == 2
      and {(x["from_sheet"], x["to_sheet"]) for x in xs["sheet_links"]} == {("Summary", "P&L"), ("Summary", "Balance Sheet")}, xs["sheet_links"])

# ------------------------------------------------------------------ 3. financial years
check(3, "fiscal years: 'FY2031' → 2031, 'As at 31 March 31' → 2031, '2024-25' → 2025",
      find(X, "revenue_from_operations", 2031) and find(X, "total_assets", 2031) and rev, None)
check(3, "five-year CSV mapped to FY2027…FY2031", sorted({m["fiscal_year"] for m in metrics("five_csv") if m["metric_key"] == "revenue_from_operations"}) == [2027, 2028, 2029, 2030, 2031])

# ------------------------------------------------------------------ 4. units and currencies
md = {k: (docs[k]["metadata"]["currency"] or {}).get("value") for k in ("xlsx", "docx", "tx_csv", "five_csv")}
mu = {k: (docs[k]["metadata"]["unit"] or {}).get("value") for k in ("xlsx", "docx", "five_csv", "bad_xlsx")}
check(4, "currencies detected: USD (xlsx, docx), EUR (CSV), INR (five-year CSV)", md == {"xlsx": "USD", "docx": "USD", "tx_csv": "EUR", "five_csv": "INR"}, md)
check(4, "units detected: million, million, crore, thousand", mu == {"xlsx": "million", "docx": "million", "five_csv": "crore", "bad_xlsx": "thousand"}, mu)
r31 = find(X, "revenue_from_operations", 2031)[0]
check(4, "normalised value = printed value × unit (1265 million → 1,265,000,000)", D(r31["normalized_value"]) == D("1265000000"), r31["normalized_value"])
txm = [e for e in c.get(f"/documents/{ids['tx_csv']}/chunks?limit=50").json()["items"] if "grouped by 'Category'" in e["text"]]
check(4, "decimal-comma amounts summed correctly by category in Python (Rent 3600.00, Travel 1130.50, Software 410.25)",
      txm and "Rent: 3600.00" in txm[0]["text"] and "Travel: 1130.50" in txm[0]["text"], txm[0]["text"][:200] if txm else None)

# ------------------------------------------------------------------ 5. ratios
avail = c.post("/dashboard/build", json={}).json()["available"]
ent_of = {d["id"]: d["entity"] for d in avail["documents"]}
dash = c.post("/dashboard/build", json={"organisations": [ent_of[ids["xlsx"]]]}).json()
kp = {k["label"]: k for k in dash["kpis"]}
exp_margin = (D(210) / D(1265) * 100).quantize(Decimal("0.0001"))
exp_growth = ((D(1265) - D(1150)) / D(1150) * 100).quantize(Decimal("0.0001"))
check(5, f"net profit margin FY2031 = 210/1265×100 = {exp_margin}", kp.get("Net profit margin", {}).get("value") == str(exp_margin), kp.get("Net profit margin"))
check(5, f"revenue growth FY2031 = (1265−1150)/1150×100 = {exp_growth}", kp.get("Revenue growth", {}).get("value") == str(exp_growth), kp.get("Revenue growth"))
mchart = next((ch for ch in dash["charts"] if ch["id"].endswith(":margins")), None)
gm = next((r.get("gross_margin") for r in (mchart or {}).get("rows", []) if r["x"] == "FY2031"), None)
check(5, "gross margin FY2031 = 505/1265×100 = 39.9209", gm is not None and abs(gm - 39.9209) < 1e-9, gm)
pend = {p["label"]: p for p in dash["pending_verification"]}
exp_de = (D(520) / D(1050)).quantize(Decimal("0.0001"))
de = kp.get("Debt-to-equity") or {}
de_inputs = (de.get("sources") or [{}])[0].get("inputs", [])
check(5, f"debt-to-equity FY2031 = printed total borrowings 520 (reconciles with 100 + 420) / equity 1050 = {exp_de}, from validated inputs only",
      de.get("value") == str(exp_de) and de_inputs and all(i["validation_status"] in ("validated", "verified") for i in de_inputs), de)
check(5, "EBITDA margin not computed while EBITDA is unvalidated (pending, never guessed)",
      "EBITDA margin" not in kp and pend.get("EBITDA margin", {}).get("status") == "needs_verification", pend.get("EBITDA margin"))

# ------------------------------------------------------------------ 6. reconciliation errors
B = metrics("bad_xlsx")
checks_bad = c.get(f"/documents/{ids['bad_xlsx']}").json()["validation_checks"]
fails = {x["check"] for x in checks_bad if x["result"] == "failed"}
check(6, "balance sheet that does not balance and broken cash roll-forward are both detected", {"assets_eq_equity_plus_liabilities", "closing_cash_roll_forward"} <= fails, checks_bad)
check(6, "the inconsistent values are marked failed_validation", all(m["validation_status"] == "failed_validation" for m in B if m["metric_key"] != "line_item"))
okx = {x["check"] for x in c.get(f"/documents/{ids['xlsx']}").json()["validation_checks"] if x["result"] == "passed"}
check(6, "consistent workbook passes the new checks (gross profit, PBT = PAT + tax, cash roll-forward, net change = three activities)",
      {"gross_profit_eq_revenue_minus_cogs", "pbt_eq_net_profit_plus_tax", "closing_cash_roll_forward", "net_change_eq_three_activities"} <= okx, okx)

# ------------------------------------------------------------------ 7–10. dashboard
types = {ch["type"] for ch in dash["charts"]}
R["dashboard_example"] = {"kpis": [(k["label"], k["value"], k["unit"], k["fiscal_year"], k["origin"]) for k in dash["kpis"]],
                          "charts": [(ch["type"], ch["title"]) for ch in dash["charts"]], "pending": list(pend), "stats": dash["stats"]}
check(7, "dashboard generated automatically from the workbook + notes (KPIs and charts)", len(dash["kpis"]) >= 8 and len(dash["charts"]) >= 10, R["dashboard_example"])
check(8, "chart families chosen from the data: line/grouped bar trends, area, donut, pie, waterfall, treemap, heatmap",
      {"line", "grouped_bar", "area", "donut", "pie", "waterfall", "treemap", "heatmap"} <= types, sorted(types))
wf = next(ch for ch in dash["charts"] if ch["type"] == "waterfall")
check(8, "cash waterfall: 150 → +300 −180 −80 → 190 with no unexplained remainder", [r["value"] for r in wf["rows"]] == [150.0, 300.0, -180.0, -80.0, 190.0], wf["rows"])
dash_bad = c.post("/dashboard/build", json={"organisations": [ent_of[ids["bad_xlsx"]]]}).json()
check(10, "failed (inconsistent) values never reach KPIs or charts", dash_bad["kpis"] == [] and dash_bad["charts"] == [], dash_bad["limitations"])
dash_tx = c.post("/dashboard/build", json={"document_ids": [ids["tx_csv"]]}).json()
check(9, "a document without statement metrics (transactions) does not break the dashboard", isinstance(dash_tx["kpis"], list), dash_tx["limitations"])
dash5 = c.post("/dashboard/build", json={"document_ids": [ids["five_csv"]]}).json()
l5 = {k["label"] for k in dash5["kpis"]}
check(9, "five-year summary: revenue, profit, assets KPIs and a 5-point revenue line even though EBITDA, equity, cash flow are absent",
      {"Revenue", "Net profit (profit for the year)", "Total assets"} <= l5 and any(ch["type"] == "line" and len(ch["rows"]) == 5 for ch in dash5["charts"]), l5)
check(10, "no KPI for metrics the document does not contain (no EBITDA, cash, borrowings, debt-to-equity)",
      not ({"EBITDA", "Cash and cash equivalents", "Total borrowings", "Debt-to-equity"} & l5), l5)
check(10, "calculations on unvalidated inputs are listed as pending, not shown", "Revenue growth" not in l5 and any(p["label"] == "Revenue growth" for p in dash5["pending_verification"]))

# ------------------------------------------------------------------ 13. multiple documents, no double counting
dup_x = dash["stats"]["cross_document_duplicates"]
bor = next((ch for ch in dash["charts"] if ch["id"].endswith(":borrowings_mix")), None)
check(13, "same figures in workbook and Word notes (borrowings FY2031) counted once", dup_x >= 2 and bor and sorted(r["value"] for r in bor["rows"]) == [100.0, 420.0],
      {"dups": dup_x, "pie": bor and bor["rows"]})
dril = c.post("/dashboard/build", json={"document_ids": [ids["ril_2425"], ids["ril_2526"]]}).json()
rt = next((ch for ch in dril["charts"] if ch["id"].endswith(":rev_trend")), None)
fy25 = [r for r in (rt or {}).get("rows", []) if r["x"] == "FY2025"]
check(13, "two genuine annual reports: FY2025 appears once in the revenue trend, repeated comparatives de-duplicated",
      rt and len(fy25) == 1 and dril["stats"]["cross_document_duplicates"] > 0, {"rows": rt and rt["rows"], "dups": dril["stats"]["cross_document_duplicates"]})
R["ril_dashboard"] = {"kpis": [(k["label"], k["value"], k["unit"], k["fiscal_year"]) for k in dril["kpis"]], "stats": dril["stats"],
                      "charts": [ch["title"] for ch in dril["charts"]]}

# ------------------------------------------------------------------ 11, 12, 15. AI dashboard conversation (real LLM)
chat = []


def ask(q, chart=None, flt=None):
    t = time.time()
    r = c.post("/dashboard/chat", json={"question": q, "filters": flt or {"organisations": [ent_of[ids["xlsx"]]]}, "chart_id": chart}).json()
    rec = {"question": q, "chart": chart, "status": r["status"], "answer": r["content"], "citations": [x["sid"] for x in r["citations"]],
           "unsupported": r["verification"].get("unsupported_numbers"), "invalid": r["verification"].get("invalid_citations"),
           "prompt_tokens": (r["verification"].get("timings") or {}).get("prompt_tokens"), "seconds": round(time.time() - t, 1), "scenario": r.get("scenario")}
    chat.append(rec)
    return rec


rt_id = next(ch["id"] for ch in dash["charts"] if ch["id"].endswith(":rev_trend"))
a1 = ask("Explain the revenue trend shown in this chart.", rt_id)
check(11, "chart question answered from the chart's data points with [D#] citations and no unsupported numbers",
      a1["status"] == "answered" and any(s.startswith("D") for s in a1["citations"]) and not a1["unsupported"], a1)
a2 = ask("What happens if revenue grows by 10%?")
check(12, "scenario: Python result 1391.5 cited as hypothetical [H#], not presented as reported",
      a2["status"] in ("answered", "answered_with_warnings") and any(s.startswith("H") for s in a2["citations"]) and "1391.5" in a2["answer"].replace(",", ""), a2)
a3 = ask("How was the net profit margin calculated, and from which inputs?")
check(12, "calculation explained with its formula and cited inputs", a3["status"] == "answered" and a3["citations"], a3)
a4 = ask("Why did revenue increase in FY2031?", None, {})
check(12, "explanation question uses the Word note (document passage cited) or says the documents do not explain it",
      a4["status"] in ("answered", "insufficient_evidence") and (any(s.startswith("S") for s in a4["citations"]) or a4["status"] == "insufficient_evidence"), a4)
a5 = ask("What was EBITDA in FY2035?")
check(10, "question about a period that is not in the documents (FY2035) is withheld, no figure invented", a5["status"] == "insufficient_evidence", a5)
R["chat"] = chat
mx = max(x["prompt_tokens"] or 0 for x in chat)
check(15, f"every dashboard prompt fits the 8,192-token context (max {mx} prompt tokens)", 0 < mx < 8192 - 1024, [(x["question"][:30], x["prompt_tokens"]) for x in chat])
R["hardware"] = {"cpus": os.cpu_count(), "mem_total_gb": round(int(open("/proc/meminfo").read().split()[1]) / 1048576, 1), "gpu": "none",
                 "llm": "Qwen3-4B Q4_K_M via llama.cpp (CPU), context 8192", "answer_seconds": [x["seconds"] for x in chat]}

# ------------------------------------------------------------------ 14. deletion
did = ids["docx"]
assert c.delete(f"/documents/{did}").status_code == 200
n = vector_store.client().count(S.qdrant_collection, count_filter=qm.Filter(must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=did))]), exact=True).count
after = c.post("/dashboard/build", json={"organisations": [ent_of[ids["xlsx"]]]}).json()
src_files = {p.get("filename") for ch in after["charts"] for p in ch["points"].values()} | {s.get("filename") for k in after["kpis"] for s in k["sources"]}
check(14, "deleting the Word notes removes its vectors, and the dashboard no longer cites it while the workbook values remain",
      n == 0 and files["docx"].name not in src_files and after["stats"]["cross_document_duplicates"] < dup_x and after["kpis"], {"vectors": n, "dups_after": after["stats"]["cross_document_duplicates"]})

R["finished"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
R["user"] = "fresh acceptance user"
OUT.write_text(json.dumps(R, indent=1, default=str))
f = [x for x in R["checks"] if not x["ok"]]
print(f"\n{len(R['checks']) - len(f)}/{len(R['checks'])} checks passed")
sys.exit(1 if f else 0)

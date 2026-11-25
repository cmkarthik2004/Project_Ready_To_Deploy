import json, subprocess, re
import pymupdf
PY = "/home/user/Ready_To_Deploy/backend/.venv/bin/python"
B = "/tmp/claude-0/sp/papers/"
O = B + "out/"
def conv(name):
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", O, O + name + ".docx"], capture_output=True, check=True)
for s in ("synopsis", "paper"):
    subprocess.run([PY, B + s + ".py"], check=True)
conv("FinRAG_Project_Synopsis"); conv("FinRAG_Research_Paper")
norm = lambda t: re.sub(r"\s+", " ", t).strip()
prev = None
for it in range(4):
    subprocess.run([PY, B + "report.py"], check=True)
    conv("FinRAG_Project_Report")
    heads = json.load(open(B + "report_headings.json"))
    doc = pymupdf.open(O + "FinRAG_Project_Report.pdf")
    pages = [norm(p.get_text()) for p in doc]
    toc_page = next(i for i, t in enumerate(pages) if t.startswith("Table of Contents"))
    entries, start = [], toc_page + 1
    for lv, text in heads:
        if text == "Abstract":
            entries.append([lv, text, toc_page]); continue
        pg = next((i for i in range(start, len(pages)) if norm(text) in pages[i]), None)
        if pg is None:
            pg = start
        entries.append([lv, text, pg + 1]); start = pg
    entries = [e for e in entries if e[1] != "Abstract"] if False else entries
    if entries == prev:
        break
    json.dump(entries, open(B + "report_toc.json", "w")); prev = entries
print("report pages", pymupdf.open(O + "FinRAG_Project_Report.pdf").page_count, "iterations", it + 1)
for n in ("FinRAG_Project_Synopsis", "FinRAG_Research_Paper"):
    print(n, pymupdf.open(O + n + ".pdf").page_count)

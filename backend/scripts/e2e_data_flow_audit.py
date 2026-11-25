"""Live end-to-end data-flow audit of a running FinRAG stack (see docs/END_TO_END_DATA_FLOW_AUDIT.md).

Drives the real API as two fresh users, inspects stored files / PostgreSQL / Qdrant directly, and opens the original
files to check that citations point to the right page / table row / cell / CSV row. Exit code 1 on any failed check.

DESTRUCTIVE TO THE RUNNING STACK FOR A FEW SECONDS: it stops the local Qdrant process to test failure + retry and then
restarts it (QDRANT_DIR). Run only against a development stack.

  FINRAG_TEST_DOCS=/path/to/real/documents  AUDIT_OUT=/tmp/audit_results.json  python scripts/e2e_data_flow_audit.py

The input documents are NOT in the repository (no bundled data). The script expects genuine documents under
FINRAG_TEST_DOCS with the file names used below; adapt the `files` mapping to your own documents.
"""
import csv as csvmod
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
from qdrant_client.http import models as qm  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models import (Document, DocumentChunk, DocumentTable, FinancialMetric, FinancialStatement,  # noqa: E402
                        ProcessingJob, SourceReference)
from app.rag import vector_store  # noqa: E402

API = os.environ.get("FINRAG_API", "http://127.0.0.1:8000/api")
QDRANT_DIR = os.environ.get("QDRANT_DIR", "/opt/qdrant120")
DOCS = Path(os.environ.get("FINRAG_TEST_DOCS", "/opt/finrag_testdocs"))
S = get_settings()
results = {"checks": [], "documents": {}, "started": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}


def check(name, ok, detail=""):
    results["checks"].append({"check": name, "ok": bool(ok), "detail": str(detail)[:600]})
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    return ok


def user(label):
    c = httpx.Client(base_url=API, timeout=900)
    email = f"audit-{label}-{uuid.uuid4().hex[:6]}@example.com"
    r = c.post("/auth/register", json={"email": email, "password": "Str0ngPassw0rd!"})
    assert r.status_code == 201, r.text
    return c, email


def qcount(doc_id):
    return vector_store.client().count(S.qdrant_collection, count_filter=qm.Filter(must=[
        qm.FieldCondition(key="document_id", match=qm.MatchValue(value=doc_id))]), exact=True).count


def db_counts(doc_id):
    with SessionLocal() as db:
        u = uuid.UUID(doc_id)
        return {m.__tablename__: db.query(m).filter_by(document_id=u).count()
                for m in (DocumentChunk, FinancialMetric, SourceReference, DocumentTable, FinancialStatement, ProcessingJob)} | {"qdrant_points": qcount(doc_id)}


def wait(c, doc_id, timeout=900):
    t = time.time()
    while time.time() - t < timeout:
        d = c.get(f"/documents/{doc_id}").json()
        if d["status"] in ("processed", "failed"):
            return d
        time.sleep(2)
    raise TimeoutError(doc_id)


# ---------------------------------------------------------------- input files (genuine, newly uploaded)
work = Path(tempfile.mkdtemp(prefix="audit_"))
import pymupdf  # noqa: E402

src = pymupdf.open(DOCS / "RIL-Integrated-Annual-Report-2024-25.pdf")
ex = pymupdf.open(); ex.insert_pdf(src, from_page=98, to_page=99)
pdf_path = work / "statements_excerpt.pdf"; ex.save(pdf_path)            # 2 genuine pages, copied verbatim
files = {"pdf": pdf_path, "pdf_ocr": DOCS / "RIL-Financial-Highlights-10-years.pdf",
         "docx": DOCS / "derived/derived_p58.docx", "xlsx": DOCS / "derived/derived_p58.xlsx",
         "xls": DOCS / "derived/derived_p58.xls", "csv": DOCS / "derived/derived_p58.csv"}

A, a_email = user("a")
B, b_email = user("b")
results["users"] = {"A": "fresh user A", "B": "fresh user B"}

# ---------------------------------------------------------------- stages 1-6: upload, validation, storage, DB rows, job
up = A.post("/documents", files=[("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in files.values()]).json()["results"]
check("upload: all six files accepted", all(r["accepted"] for r in up), [(r["filename"], r.get("error")) for r in up])
ids = {k: r["document"]["id"] for k, r in zip(files, up)}
bad = A.post("/documents", files=[("files", ("fake.pdf", b"not a pdf", "application/pdf")), ("files", ("x.csv", b"a\x00b", "text/csv"))]).json()["results"]
check("validation: wrong signature / binary CSV rejected with reasons", not any(r["accepted"] for r in bad), bad)
dup = A.post("/documents", files=[("files", ("again.xlsx", files["xlsx"].read_bytes(), "x"))]).json()["results"][0]
check("validation: duplicate (same SHA-256, same user) rejected", not dup["accepted"] and "already uploaded" in dup["error"], dup)
import threading  # noqa: E402
race_body = f"Particulars,2030\nTotal assets,{uuid.uuid4().int % 10**6}\n".encode()   # SYNTHETIC bytes, only for the race test
A2 = httpx.Client(base_url=API, timeout=300); A2.post("/auth/login", json={"email": a_email, "password": "Str0ngPassw0rd!"})
gate, race = threading.Barrier(2), []
def _up(cl):
    gate.wait(); race.append(cl.post("/documents", files=[("files", ("race.csv", race_body, "text/csv"))]).json()["results"][0])
ths = [threading.Thread(target=_up, args=(cl,)) for cl in (A, A2)]; [t.start() for t in ths]; [t.join() for t in ths]
check("validation: two concurrent uploads of the same file -> exactly one document", sorted(r["accepted"] for r in race) == [False, True], race)
race_id = next(r["document"]["id"] for r in race if r["accepted"]); wait(A, race_id); A.delete(f"/documents/{race_id}")
with SessionLocal() as db:
    for k, did in ids.items():
        d = db.get(Document, uuid.UUID(did))
        stored = Path(S.upload_dir) / d.stored_filename
        check(f"storage[{k}]: original stored under random name, bytes identical",
              stored.exists() and hashlib.sha256(stored.read_bytes()).hexdigest() == hashlib.sha256(files[k].read_bytes()).hexdigest() == d.sha256
              and d.original_filename == files[k].name and d.stored_filename != files[k].name, d.stored_filename)
        jobs = db.query(ProcessingJob).filter_by(document_id=d.id).all()
        check(f"db[{k}]: document row + exactly one processing job", len(jobs) == 1, len(jobs))

# ---------------------------------------------------------------- stages 7-15: worker processing
for k, did in ids.items():
    d = wait(A, did)
    stages = [s["stage"] for s in d["jobs"][0]["log"]]
    check(f"processing[{k}]: processed with all stages", d["status"] == "processed" and stages == ["parse", "detect_metadata", "extract_and_validate", "persist", "chunk", "embed", "index"], (d["status"], d["error_message"], stages))
    cnt = db_counts(did)
    results["documents"][k] = {"filename": d["filename"], "format": d["file_format"], "stages": d["jobs"][0]["log"], "counts": cnt,
                               "metadata": {m: (v or {}).get("status") for m, v in (d.get("metadata") or {}).items()},
                               "ocr_pages": d.get("ocr_pages")}
    check(f"index[{k}]: chunks in PostgreSQL == points in Qdrant == document.chunk_count",
          cnt["document_chunks"] == cnt["qdrant_points"] == d["chunk_count"] > 0, cnt)
    check(f"persist[{k}]: one source_reference per metric", cnt["financial_metrics"] == cnt["source_references"] == d["metric_count"] > 0, cnt)
    with SessionLocal() as db:
        pts, _ = vector_store.client().scroll(S.qdrant_collection, scroll_filter=qm.Filter(must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=did))]), limit=1000, with_payload=True)
        chunk_ids = {str(c.id) for c in db.query(DocumentChunk).filter_by(document_id=uuid.UUID(did)).all()}
        check(f"index[{k}]: Qdrant point ids == chunk ids, payload owner correct",
              {str(p.id) for p in pts} == chunk_ids and all(p.payload["owner_id"] == str(db.get(Document, uuid.UUID(did)).owner_id) for p in pts))
check("ocr: image-only PDF went through OCR", bool(results["documents"]["pdf_ocr"]["ocr_pages"]), results["documents"]["pdf_ocr"]["ocr_pages"])

# ---------------------------------------------------------------- citations point to the original location
import docx as docxmod  # noqa: E402
import openpyxl  # noqa: E402
import xlrd  # noqa: E402


def norm(x):
    return "".join(str(x).split())


_OCR: dict = {}


def at_location(fmt, path, loc, raw):
    if fmt == "pdf":
        page = pymupdf.open(path)[loc["page"] - 1]
        text = page.get_text()
        if not text.strip():  # image-only page: independent OCR with the tesseract CLI (not FinRAG's code)
            key = (str(path), loc["page"])
            if key not in _OCR:
                png = work / f"ocr_{loc['page']}.png"; page.get_pixmap(dpi=300).save(png)
                _OCR[key] = subprocess.run(["tesseract", str(png), "stdout", "--psm", "6"], capture_output=True, text=True).stdout
            text = _OCR[key]
        return norm(raw) in norm(text)
    if fmt == "xlsx":
        return norm(openpyxl.load_workbook(path, data_only=True)[loc["sheet"]][loc["cell"]].value) == norm(raw)
    if fmt == "xls":
        sh = xlrd.open_workbook(str(path)).sheet_by_name(loc["sheet"])
        col = ord(loc["cell"][0]) - 65; row = int(loc["cell"][1:]) - 1
        return norm(sh.cell_value(row, col)) == norm(raw)
    if fmt == "csv":
        rows = list(csvmod.reader(open(path, encoding="utf-8-sig")))
        return any(norm(c) == norm(raw) for c in rows[loc["row"] - 1])
    if fmt == "docx":
        t = docxmod.Document(path).tables[loc["table_index"]]
        return any(norm(c.text) == norm(raw) for c in t.rows[loc["row"] - 1].cells)


for k, did in ids.items():
    items = A.get(f"/documents/{did}/metrics?include_line_items=false").json()["items"]
    fmt = "pdf" if k.startswith("pdf") else k
    sample = items[:10]
    okc = [at_location(fmt, files[k], m["location"], m["raw_value"]) for m in sample]
    check(f"citations[{k}]: {sum(okc)}/{len(sample)} sampled values found at their cited location in the original file",
          sample and all(okc), [(m["raw_value"], m["location_text"]) for m, o in zip(sample, okc) if not o])

# ---------------------------------------------------------------- dashboard statistics == database
ov = A.get("/analytics/overview").json()
with SessionLocal() as db:
    owner = db.get(Document, uuid.UUID(ids["pdf"])).owner_id
    mine = db.query(Document).filter_by(owner_id=owner)
    real = {"total": mine.count(), "processed": mine.filter_by(status="processed").count(),
            "chunks": db.query(DocumentChunk).join(Document).filter(Document.owner_id == owner, DocumentChunk.embedded.is_(True)).count(),
            "metrics": db.query(FinancialMetric).join(Document).filter(Document.owner_id == owner).count()}
check("dashboard: overview numbers equal direct database counts",
      (ov["total_documents"], ov["processed_documents"], ov["indexed_chunks"], ov["extracted_metrics"]) == (real["total"], real["processed"], real["chunks"], real["metrics"]),
      (ov, real))
results["dashboard"] = {"api": {k: ov[k] for k in ("total_documents", "processed_documents", "indexed_chunks", "extracted_metrics")}, "db": real}

# ---------------------------------------------------------------- stages 16-22: question -> retrieval -> facts -> LLM -> verification
sid = A.post("/chat/sessions", json={"document_ids": [ids["pdf"]]}).json()["id"]
t = time.time()
ans = A.post(f"/chat/sessions/{sid}/messages", json={"question": "What was the consolidated revenue from operations for 2024-25?"}).json()
results["chat"] = {"status": ans["status"], "answer": ans["content"], "latency_s": round(time.time() - t, 1),
                   "citations": [(c["sid"], c.get("filename"), c.get("location_text")) for c in ans["citations"]],
                   "verification": {k: ans["verification"].get(k) for k in ("valid_citations", "invalid_citations", "unsupported_numbers")},
                   "timings": ans["verification"].get("timings")}
check("chat: answered with verified citations", ans["status"] == "answered" and ans["citations"], results["chat"])
check("chat: answer contains the printed figure 9,80,136", "980136" in ans["content"].replace(",", ""), ans["content"])
check("chat: every citation belongs to the selected document", all(c.get("document_id") == ids["pdf"] for c in ans["citations"]), ans["citations"])
with SessionLocal() as db:
    for c in ans["citations"]:
        if c["kind"] == "extracted_metric":
            m = db.get(FinancialMetric, uuid.UUID(c["metric_id"]))
            check(f"chat: citation {c['sid']} value found at its cited page in the original PDF",
                  at_location("pdf", files["pdf"], m.source.location, m.raw_value), c.get("location_text"))
        elif c["kind"] == "passage":
            ch = db.get(DocumentChunk, uuid.UUID(c["chunk_id"]))
            check(f"chat: passage {c['sid']} chunk belongs to the document and page", str(ch.document_id) == ids["pdf"] and ch.location.get("page"), c.get("location_text"))
nores = A.post(f"/chat/sessions/{sid}/messages", json={"question": "What is the company's forecast revenue for 2035?"}).json()
check("chat: unanswerable future-period question -> insufficient_evidence", nores["status"] == "insufficient_evidence", nores["content"])
results["chat_unanswerable"] = {"status": nores["status"], "answer": nores["content"]}
tb = A.post(f"/chat/sessions/{sid}/messages", json={"question": "What were the consolidated total borrowings as at 31st March 2025?"}).json()
results["chat_total_borrowings"] = {"status": tb["status"], "answer": tb["content"], "verification": {k: tb["verification"].get(k) for k in ("valid_citations", "invalid_citations", "unsupported_numbers")}}
check("chat: total of unvalidated parts — no model arithmetic and no fabricated citation shown to the user",
      not (tb["status"].startswith("answered") and (tb["verification"].get("unsupported_numbers") or tb["verification"].get("invalid_citations"))), results["chat_total_borrowings"])

# ---------------------------------------------------------------- calculations use validated inputs only
rat = A.post("/analytics/ratios", json={"document_ids": list(ids.values())}).json()["results"]
okr = [r for r in rat if r["status"] == "ok"]
check("calculations: every computed ratio uses only validated/verified inputs", okr and all(i["validation_status"] in ("validated", "verified") for r in okr for i in r["inputs"]), len(okr))
results["ratios"] = {s: sum(1 for r in rat if r["status"] == s) for s in sorted({r["status"] for r in rat})}

# ---------------------------------------------------------------- isolation: user B cannot reach user A's data
pid = ids["pdf"]
metric_id = A.get(f"/documents/{pid}/metrics").json()["items"][0]["id"]
probes = {
    "GET document": B.get(f"/documents/{pid}").status_code,
    "GET chunks": B.get(f"/documents/{pid}/chunks").status_code,
    "GET tables": B.get(f"/documents/{pid}/tables").status_code,
    "GET metrics": B.get(f"/documents/{pid}/metrics").status_code,
    "GET original file": B.get(f"/documents/{pid}/file").status_code,
    "PATCH metadata": B.patch(f"/documents/{pid}/metadata", json={"currency": "USD"}).status_code,
    "POST reprocess": B.post(f"/documents/{pid}/reprocess").status_code,
    "DELETE": B.delete(f"/documents/{pid}").status_code,
    "verify A's metric": B.post(f"/metrics/{metric_id}/verify", json={}).status_code,
    "report on A's doc": B.post("/reports", json={"document_ids": [pid]}).status_code,
}
check("isolation: every direct access by B returns 404", all(v == 404 for v in probes.values()), probes)
lst = B.get("/documents").json()["total"]
cmpb = B.post("/analytics/compare", json={"document_ids": [pid]})
ratb = B.post("/analytics/ratios", json={"document_ids": [pid]}).json()
serb = B.post("/analytics/series", json={"document_ids": [pid]}).json()
mlist = B.get("/metrics").json()["total"]
coll = B.post("/collections", json={"name": "probe", "document_ids": [pid]}).json()
check("isolation: list/analytics/collections expose nothing of A",
      lst == 0 and cmpb.status_code == 422 and ratb["results"] == [] and serb["series"] == [] and mlist == 0 and coll["documents"] == [],
      (lst, cmpb.status_code, len(ratb["results"]), len(serb["series"]), mlist, coll["documents"]))
bs = B.post("/chat/sessions", json={"document_ids": [pid]}).json()["id"]
bchat = B.post(f"/chat/sessions/{bs}/messages", json={"question": "What was revenue?"})
check("isolation: B's chat scoped to A's document -> 404", bchat.status_code == 404, bchat.status_code)
bopen = B.post(f"/chat/sessions/{bs}/messages", json={"question": "What was the consolidated revenue from operations?", "document_ids": []}).json()
check("isolation: B's unscoped chat sees no documents", bopen["status"] == "insufficient_evidence" and not bopen["citations"], bopen["content"])
ev = A.post("/evaluations", data={"kind": "extraction", "document_ids": pid}).json()["id"]
check("isolation: B cannot read A's evaluation run", B.get(f"/evaluations/{ev}").status_code == 404 and all(r["id"] != ev for r in B.get("/evaluations").json()))
from app.rag import embeddings  # noqa: E402
hits = vector_store.search(embeddings.embed_query("revenue from operations"), str(uuid.uuid4()), [pid], 5)
check("isolation: Qdrant search with another owner id and A's document id returns 0 points", len(hits) == 0, len(hits))
results["isolation"] = probes

# ---------------------------------------------------------------- reprocessing is idempotent (no duplicate rows/vectors)
k = "xlsx"
before = db_counts(ids[k])
with SessionLocal() as db:
    old_chunks = {str(c.id) for c in db.query(DocumentChunk).filter_by(document_id=uuid.UUID(ids[k])).all()}
A.post(f"/documents/{ids[k]}/reprocess")
wait(A, ids[k])
after = db_counts(ids[k])
with SessionLocal() as db:
    new_chunks = {str(c.id) for c in db.query(DocumentChunk).filter_by(document_id=uuid.UUID(ids[k])).all()}
same = {t: before[t] == after[t] for t in before if t != "processing_jobs"}
check("reprocess: identical counts (chunks, metrics, refs, tables, statements, vectors); one extra job record",
      all(same.values()) and after["processing_jobs"] == before["processing_jobs"] + 1, (before, after))
check("reprocess: old chunk ids/vectors fully replaced", not (old_chunks & new_chunks) and qcount(ids[k]) == len(new_chunks))
results["reprocess"] = {"before": before, "after": after}

# ---------------------------------------------------------------- failed job -> safe retry (Qdrant stopped)
k = "csv"
before = db_counts(ids[k])
subprocess.run(["pkill", "-x", "qdrant"]); time.sleep(2)
A.post(f"/documents/{ids[k]}/reprocess")
d = wait(A, ids[k])
with SessionLocal() as db:
    failed_counts = {m.__tablename__: db.query(m).filter_by(document_id=uuid.UUID(ids[k])).count() for m in (DocumentChunk, FinancialMetric, SourceReference)}
check("failure: job fails with the real error while Qdrant is down", d["status"] == "failed" and d["error_message"], d["error_message"])
check("failure: no stale or partial derived data left on the failed document", all(v == 0 for v in failed_counts.values()), failed_counts)
ov_fail = A.get("/analytics/overview").json()
check("failure: dashboard shows the failed document and failed job", ov_fail["failed_documents"] >= 1 and ov_fail["failed_jobs"] >= 1, (ov_fail["failed_documents"], ov_fail["failed_jobs"]))
subprocess.Popen(["env", f"QDRANT__STORAGE__STORAGE_PATH={QDRANT_DIR}/storage", "QDRANT__SERVICE__HOST=127.0.0.1", "./qdrant"],
                 cwd=QDRANT_DIR, stdout=open("/tmp/qdrant.log", "a"), stderr=subprocess.STDOUT, start_new_session=True)
for _ in range(30):
    try:
        if httpx.get("http://127.0.0.1:6333/healthz", timeout=2).status_code == 200:
            break
    except Exception:
        time.sleep(1)
A.post(f"/documents/{ids[k]}/reprocess")
d = wait(A, ids[k])
after = db_counts(ids[k])
check("retry: reprocess after recovery succeeds with the same counts as before the failure",
      d["status"] == "processed" and all(before[t] == after[t] for t in before if t != "processing_jobs"), (before, after))
results["failure_retry"] = {"error": results["checks"][-4]["detail"], "before": before, "after_retry": after}

# ---------------------------------------------------------------- deletion consistency
k = "docx"
with SessionLocal() as db:
    stored = Path(S.upload_dir) / db.get(Document, uuid.UUID(ids[k])).stored_filename
r = A.delete(f"/documents/{ids[k]}")
cnt = db_counts(ids[k])
with SessionLocal() as db:
    gone = db.get(Document, uuid.UUID(ids[k])) is None
check("delete: file, document row, all derived rows and all vectors removed",
      r.status_code == 200 and gone and not stored.exists() and all(v == 0 for v in cnt.values()), (r.status_code, gone, stored.exists(), cnt))
# deleting while processing is refused
A.post(f"/documents/{ids['xls']}/reprocess")
for _ in range(60):
    if A.get(f"/documents/{ids['xls']}").json()["status"] == "processing":
        break
    time.sleep(0.2)
st = A.get(f"/documents/{ids['xls']}").json()["status"]
dr = A.delete(f"/documents/{ids['xls']}")
check("delete: refused (409) while the document is processing", st != "processing" or dr.status_code == 409, (st, dr.status_code))
wait(A, ids["xls"])
results["finished"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
results["document_ids"] = ids
Path(os.environ.get("AUDIT_OUT", "audit_results.json")).write_text(json.dumps(results, indent=2, default=str))
fails = [c for c in results["checks"] if not c["ok"]]
print(f"\n{len(results['checks']) - len(fails)}/{len(results['checks'])} checks passed")
sys.exit(1 if fails else 0)

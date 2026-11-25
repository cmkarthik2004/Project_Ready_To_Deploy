"""API integration tests against the isolated test DB + test Qdrant collection.

Documents are processed by the real worker code path (parsers, BGE embeddings,
Qdrant). The LLM is replaced by a scripted test double ONLY in the tests that
check the answer-verification logic (citations / unsupported numbers); one test
calls the real LLM endpoint and is skipped if it is unreachable.
"""
from __future__ import annotations

import io
import uuid

import docx
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.worker import claim_and_run_one
from tests.conftest import need_derived

PW = "Str0ngPassw0rd!"


def client_for(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201), r.text
    return c


@pytest.fixture(scope="module")
def admin():
    from app.database.session import SessionLocal
    from app.models import User

    email = f"admin-{uuid.uuid4().hex[:6]}@example.com"
    c = client_for(email)
    with SessionLocal() as s:  # roles are read from the DB on every request
        s.query(User).filter_by(email=email).update({"role": "admin"})
        s.commit()
    return c


def drain():
    while claim_and_run_one():
        pass


def verify_unvalidated(c: TestClient, doc_id: str, keys: set[str]) -> None:
    """Simulate a person verifying the given (unvalidated) values through the API."""
    for m in c.get(f"/api/documents/{doc_id}/metrics").json()["items"]:
        if m["metric_key"] in keys and m["validation_status"] == "unvalidated":
            assert c.post(f"/api/metrics/{m['id']}/verify", json={"note": "checked against the source"}).status_code == 200


def synthetic_docx() -> bytes:
    d = docx.Document()
    d.add_heading("SYNTHETIC TEST — Statement of Profit and Loss (in thousands)", 1)
    d.add_paragraph("For the year ended 31 December 2030. Example Widgets Limited test file. Example Widgets Limited.")
    t = d.add_table(rows=1, cols=3)
    for i, h in enumerate(["Particulars", "2030", "2029"]):
        t.rows[0].cells[i].text = h
    for row in (["Revenue from operations", "200", "150"], ["Other income", "10", "5"], ["Total income", "210", "155"], ["Profit for the year", "20", "15"]):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = v
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def test_auth_flow_and_password_policy():
    c = TestClient(app)
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/register", json={"email": "weak@example.com", "password": "short"}).status_code == 422
    assert c.post("/api/auth/register", json={"email": "weak2@example.com", "password": "alllowercase123"}).status_code == 422
    email = f"u-{uuid.uuid4().hex[:6]}@example.com"
    assert c.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 201
    assert c.post("/api/auth/register", json={"email": email, "password": PW}).status_code == 409
    me = c.get("/api/auth/me").json()
    assert me["email"] == email
    c2 = TestClient(app)
    assert c2.post("/api/auth/login", json={"email": email, "password": "Wr0ngPassword!"}).status_code == 401
    r = c2.post("/api/auth/login", json={"email": email, "password": PW})
    tok = r.json()["access_token"]
    assert TestClient(app).get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    assert TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_empty_state_overview_is_real_zero():
    c = client_for(f"empty-{uuid.uuid4().hex[:6]}@example.com")
    ov = c.get("/api/analytics/overview").json()
    assert ov["total_documents"] == 0 and ov["indexed_chunks"] == 0 and ov["extracted_metrics"] == 0 and ov["recent_documents"] == []


def test_rbac_viewer_cannot_upload(admin, db):
    from app.models import User

    email = f"viewer-{uuid.uuid4().hex[:6]}@example.com"
    v = client_for(email)
    u = db.query(User).filter_by(email=email).one()
    r = admin.patch(f"/api/admin/users/{u.id}", json={"role": "viewer"})
    assert r.status_code == 200
    assert v.post("/api/documents", files=[("files", ("a.csv", b"a,b\n1,2\n", "text/csv"))]).status_code == 403
    assert v.get("/api/admin/users").status_code == 403


def test_upload_validation_and_multi_upload(admin):
    # Build the DOCX once: python-docx stamps a modification time, so two builds can differ in bytes
    # (and SHA-256) when they straddle a second boundary — the duplicate check below needs identical bytes.
    docx_bytes = synthetic_docx()
    files = [("files", ("bad.pdf", b"not a pdf", "application/pdf")),
             ("files", ("x.exe", b"MZ", "application/octet-stream")),
             ("files", ("synthetic.docx", docx_bytes, "application/octet-stream"))]
    r = admin.post("/api/documents", files=files).json()["results"]
    assert [x["accepted"] for x in r] == [False, False, True]
    assert "not a PDF" in r[0]["error"] and "Unsupported" in r[1]["error"]
    dup = admin.post("/api/documents", files=[("files", ("again.docx", docx_bytes, "x"))]).json()["results"][0]
    assert dup["accepted"] is False and "already uploaded" in dup["error"]


def test_processing_metadata_metrics_and_isolation(admin):
    drain()
    docs = admin.get("/api/documents").json()["items"]
    d = next(x for x in docs if x["filename"] == "synthetic.docx")
    assert d["status"] == "processed", d["error_message"]
    assert d["chunk_count"] > 0 and d["metric_count"] > 0
    detail = admin.get(f"/api/documents/{d['id']}").json()
    assert detail["metadata"]["organisation"]["value"] == "Example Widgets Limited"
    assert detail["metadata"]["fiscal_year"]["value"] == "FY2030"
    assert detail["metadata"]["currency"]["status"] in ("not_detected", "uncertain")
    assert [j["stage"] for j in detail["jobs"][0]["log"]][-1] == "index"
    # metadata correction is recorded as user_corrected
    r = admin.patch(f"/api/documents/{d['id']}/metadata", json={"currency": "EUR"}).json()
    assert r["currency"] == "EUR" and r["metadata"]["currency"]["status"] == "user_corrected"
    ms = admin.get(f"/api/documents/{d['id']}/metrics").json()
    assert all(m["validation_status"] != "verified" for m in ms["items"])
    mid = next(m["id"] for m in ms["items"] if m["metric_key"] == "revenue_from_operations")
    assert admin.post(f"/api/metrics/{mid}/verify", json={"note": "checked against source"}).json()["validation_status"] == "verified"
    # ratios computed in Python from real stored values
    # validated-inputs-only policy: "Profit for the year" has no accounting identity here -> not computed yet
    rat = admin.post("/api/analytics/ratios", json={"document_ids": [d["id"]]}).json()["results"]
    npm = next(x for x in rat if x["calc_key"] == "net_profit_margin" and x["period_label"] == "2030")
    assert npm["status"] == "needs_verification" and npm["result"] is None and any("net_profit" in w for w in npm["warnings"])
    verify_unvalidated(admin, d["id"], {"net_profit"})
    rat = admin.post("/api/analytics/ratios", json={"document_ids": [d["id"]]}).json()["results"]
    npm = next(x for x in rat if x["calc_key"] == "net_profit_margin" and x["period_label"] == "2030")
    assert npm["status"] == "ok" and npm["result"] == "10.0000"
    gr = next(x for x in rat if x["calc_key"] == "revenue_from_operations_growth")
    assert gr["result"] == "33.3333"
    # another user cannot see this document
    other = client_for(f"other-{uuid.uuid4().hex[:6]}@example.com")
    assert other.get(f"/api/documents/{d['id']}").status_code == 404
    assert other.get("/api/documents").json()["total"] == 0
    rep = admin.post("/api/reports", json={"document_ids": [d["id"]]}).json()
    assert rep["financial_performance"] and any("not investment advice" in x for x in rep["limitations"])
    md = admin.post("/api/reports/markdown", json={"document_ids": [d["id"]]})
    assert md.status_code == 200 and "Net profit margin" in md.text


def test_ratios_align_income_statement_and_balance_sheet_years(admin):
    """SYNTHETIC: P&L column '2030' must pair with balance-sheet column 'As at 31 December 2030'."""
    d = docx.Document()
    d.add_heading("SYNTHETIC TEST — Statement of Profit and Loss (in millions)", 1)
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Particulars", "2030"
    for a, b in (["Revenue from operations", "500"], ["Profit for the year", "50"]):
        c = t.add_row().cells
        c[0].text, c[1].text = a, b
    d.add_heading("SYNTHETIC TEST — Balance Sheet (in millions)", 1)
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Particulars", "As at 31 December 2030"
    for a, b in (["Total assets", "1000"], ["Total equity", "400"], ["Total liabilities", "600"]):
        c = t.add_row().cells
        c[0].text, c[1].text = a, b
    b = io.BytesIO()
    d.save(b)
    res = admin.post("/api/documents", files=[("files", ("aligned.docx", b.getvalue(), "x"))]).json()["results"][0]
    drain()
    doc_id = res["document"]["id"]
    rat = admin.post("/api/analytics/ratios", json={"document_ids": [doc_id]}).json()["results"]
    assert next(x for x in rat if x["calc_key"] == "return_on_equity")["status"] == "needs_verification"
    verify_unvalidated(admin, doc_id, {"net_profit", "revenue_from_operations"})  # human verification path
    rat = admin.post("/api/analytics/ratios", json={"document_ids": [doc_id]}).json()["results"]
    roe = next(x for x in rat if x["calc_key"] == "return_on_equity")
    assert roe["status"] == "ok" and roe["result"] == "12.5000" and roe["period_label"] == "2030"
    roa = next(x for x in rat if x["calc_key"] == "return_on_assets")
    assert roa["result"] == "5.0000"


def test_compare_derived_real_formats(admin):
    paths = [need_derived("derived_p58.xlsx"), need_derived("derived_p58.csv")]
    files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    res = admin.post("/api/documents", files=files).json()["results"]
    drain()
    ids = [x["document"]["id"] for x in res if x["accepted"]]
    cmp = admin.post("/api/analytics/compare", json={"document_ids": ids}).json()
    assert len(cmp["columns"]) >= 2
    vals = {c["filename"]: c["values"]["revenue_from_operations"]["raw_value"] for c in cmp["columns"] if "revenue_from_operations" in c["values"] and c["period_label"] == "2024-25"}
    assert set(vals.values()) == {"5,32,792"}
    assert any("Units differ" in w or "no stated unit" in w for w in cmp["warnings"])  # CSV has no unit statement


def test_rag_verifier_rejects_uncited_and_flags_unsupported(admin, monkeypatch):
    """Scripted LLM test double: checks the VERIFICATION logic, not answer quality."""
    from app.llm import client as llm

    d = next(x for x in admin.get("/api/documents").json()["items"] if x["filename"] == "synthetic.docx")
    sid = admin.post("/api/chat/sessions", json={"document_ids": [d["id"]]}).json()["id"]
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "Revenue was 999,999.", "usage": {}, "latency_ms": 1, "model": "test-double"})
    m = admin.post(f"/api/chat/sessions/{sid}/messages", json={"question": "What was revenue from operations in 2030?"}).json()
    assert m["status"] == "insufficient_evidence" and "999,999" not in m["content"]
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "Revenue from operations was 200 [S1] and 777 [S1].", "usage": {}, "latency_ms": 1, "model": "test-double"})
    m = admin.post(f"/api/chat/sessions/{sid}/messages", json={"question": "What was revenue from operations in 2030?"}).json()
    assert m["status"] == "answered_with_warnings"
    assert "777" in m["verification"]["unsupported_numbers"]
    assert m["citations"] and m["citations"][0]["filename"] == "synthetic.docx"
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "Revenue from operations was 200 [S1]; the total is 977 [C9].", "usage": {}, "latency_ms": 1, "model": "test-double"})
    m = admin.post(f"/api/chat/sessions/{sid}/messages", json={"question": "What was revenue from operations in 2030?"}).json()
    assert m["status"] == "insufficient_evidence" and "977" not in m["content"]     # fabricated citation: answer withheld
    assert m["verification"]["invalid_citations"] == ["C9"]
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("down")))
    m = admin.post(f"/api/chat/sessions/{sid}/messages", json={"question": "What was revenue?"}).json()
    assert m["status"] == "error" and "not available" in m["content"]


def test_rag_real_llm_if_available(admin):
    from app.llm.client import endpoint_from_settings

    ep = endpoint_from_settings()
    try:
        httpx.get(f"{ep.base_url}/models", timeout=3).raise_for_status()
    except Exception:
        pytest.skip("LLM endpoint not reachable")
    d = next(x for x in admin.get("/api/documents").json()["items"] if x["filename"] == "synthetic.docx")
    sid = admin.post("/api/chat/sessions", json={"document_ids": [d["id"]]}).json()["id"]
    m = admin.post(f"/api/chat/sessions/{sid}/messages", json={"question": "What was the revenue from operations for 2030?"}).json()
    assert m["status"] in ("answered", "answered_with_warnings", "insufficient_evidence")
    if m["status"].startswith("answered"):
        assert "200" in m["content"] and m["citations"]


def test_delete_removes_vectors(admin):
    from app.core.config import get_settings
    from app.rag import vector_store

    d = next(x for x in admin.get("/api/documents").json()["items"] if x["filename"] == "synthetic.docx")
    assert admin.delete(f"/api/documents/{d['id']}").status_code == 200
    assert admin.get(f"/api/documents/{d['id']}").status_code == 404
    from qdrant_client.http import models as qm

    n = vector_store.client().count(get_settings().qdrant_collection, count_filter=qm.Filter(must=[
        qm.FieldCondition(key="document_id", match=qm.MatchValue(value=d["id"]))]), exact=True).count
    assert n == 0


def test_health_and_status(admin):
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}
    st = admin.get("/api/status").json()
    assert st["database"]["reachable"] and st["vector_store"]["reachable"]
    assert "cuda_available" in st["gpu"]


def test_unit_correction_propagates_to_document_level_values():
    """Values whose unit came from the document level follow a user's unit correction; normalised values are recomputed."""
    import csv as _csv
    c = client_for(f"units-{uuid.uuid4().hex[:6]}@example.com")
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["Particulars", "2030"])          # SYNTHETIC: no unit statement anywhere in the file
    w.writerow(["Total assets", "100"])
    doc = c.post("/api/documents", files=[("files", ("nounit.csv", buf.getvalue().encode(), "text/csv"))]).json()["results"][0]["document"]
    drain()
    m = c.get(f"/api/documents/{doc['id']}/metrics").json()["items"][0]
    assert m["unit"] is None and m["normalized_value"] is None
    c.patch(f"/api/documents/{doc['id']}/metadata", json={"unit": "thousand", "currency": "EUR"})
    m = c.get(f"/api/documents/{doc['id']}/metrics").json()["items"][0]
    assert m["unit"] == "thousand" and m["normalized_value"].startswith("100000") and m["currency"] == "EUR"


def test_failed_reprocess_with_vector_store_down_leaves_no_stale_data(monkeypatch):
    """A job that fails because the vector store is unreachable must not leave earlier metrics/chunks on a failed document,
    and a retry after recovery reproduces the same derived data."""
    from app.rag import vector_store
    c = client_for(f"retry-{uuid.uuid4().hex[:6]}@example.com")
    body = "Particulars,2030\nTotal assets,100\nTotal equity,40\n"   # SYNTHETIC test values
    doc = c.post("/api/documents", files=[("files", ("retry.csv", body.encode(), "text/csv"))]).json()["results"][0]["document"]
    drain()
    ok = c.get(f"/api/documents/{doc['id']}").json()
    assert ok["status"] == "processed" and ok["metric_count"] > 0

    def down(*a, **k):
        raise ConnectionError("vector store unreachable (simulated)")
    with monkeypatch.context() as m:
        m.setattr(vector_store, "delete_document", down)
        m.setattr(vector_store, "upsert", down)
        c.post(f"/api/documents/{doc['id']}/reprocess")
        drain()
    failed = c.get(f"/api/documents/{doc['id']}").json()
    assert failed["status"] == "failed" and "unreachable" in failed["error_message"]
    assert failed["metric_count"] == failed["chunk_count"] == 0
    assert c.get(f"/api/documents/{doc['id']}/metrics").json()["total"] == 0
    assert c.get(f"/api/documents/{doc['id']}/chunks").json()["total"] == 0
    c.post(f"/api/documents/{doc['id']}/reprocess")
    drain()
    again = c.get(f"/api/documents/{doc['id']}").json()
    assert again["status"] == "processed" and (again["metric_count"], again["chunk_count"]) == (ok["metric_count"], ok["chunk_count"])


def test_concurrent_duplicate_upload_accepts_exactly_one():
    """Two simultaneous uploads of the same bytes by one user: the unique (owner_id, sha256) index guarantees one document."""
    import threading
    email = f"race-{uuid.uuid4().hex[:6]}@example.com"
    clients = [client_for(email), client_for(email)]   # same user, two independent sessions
    body = f"Particulars,2030\nTotal assets,{uuid.uuid4().int % 1000}\n".encode()   # SYNTHETIC, unique per run
    gate, out = threading.Barrier(2), []

    def go(c):
        gate.wait()
        out.append(c.post("/api/documents", files=[("files", ("race.csv", body, "text/csv"))]).json()["results"][0])
    ts = [threading.Thread(target=go, args=(c,)) for c in clients]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(r["accepted"] for r in out) == [False, True], out
    assert clients[0].get("/api/documents").json()["total"] == 1
    drain()

"""Automatic dashboard: availability-driven KPIs/charts, de-duplication across documents, units, isolation, saved dashboards.

Inputs are SYNTHETIC CSV files (obviously artificial values, year 2030/2031) uploaded through the real API.
"""
from __future__ import annotations

import uuid

from tests.test_api import client_for, drain, verify_unvalidated


def _upload(c, name: str, body: str) -> str:
    r = c.post("/api/documents", files=[("files", (name, body.encode(), "text/csv"))]).json()["results"][0]
    assert r["accepted"], r
    return r["document"]["id"]


def _org(c, doc_id: str, org: str) -> None:
    assert c.patch(f"/api/documents/{doc_id}/metadata", json={"organisation": org}).status_code == 200


def test_single_period_dashboard_uses_available_metrics_only():
    c = client_for(f"dash1-{uuid.uuid4().hex[:6]}@example.com")
    assert c.post("/api/dashboard/build", json={}).json()["kpis"] == []      # empty state: nothing fabricated
    d1 = _upload(c, "one.csv", "Amounts in million\nParticulars,2030\nRevenue from operations,500\nTotal assets,900\n")
    drain()
    d = c.post("/api/dashboard/build", json={}).json()
    labels = {k["label"]: k for k in d["kpis"]}
    assert set(labels) == {"Revenue", "Total assets"}                       # no empty cards for missing metrics
    assert labels["Revenue"]["value"] == "500" and labels["Revenue"]["unit"] == "million" and labels["Revenue"]["fiscal_year"] == 2030
    src = labels["Revenue"]["sources"][0]
    assert src["document_id"] == d1 and src["location_text"] and src["raw_value"] == "500"
    types = {ch["type"] for ch in d["charts"]}
    assert "line" not in types and "heatmap" not in types                   # no trend charts for a single period
    assert any(ch["title"] == "Revenue and profit" for ch in d["charts"])
    assert not any("growth" in k["label"].lower() for k in d["kpis"])


def test_two_documents_same_organisation_are_not_double_counted_and_units_align():
    c = client_for(f"dash2-{uuid.uuid4().hex[:6]}@example.com")
    # Report B (later) repeats 2030 as a comparative; it states amounts in thousand, report A in million.
    a = _upload(c, "a.csv", "Amounts in million\nParticulars,2030\nRevenue from operations,500\nProfit for the year,50\n")
    b = _upload(c, "b.csv", "Amounts in thousand\nParticulars,2031,2030\nRevenue from operations,600000,500000\nProfit for the year,66000,50000\n")
    drain()
    _org(c, a, "Synthetic Test Co")
    _org(c, b, "Synthetic Test Co")
    d = c.post("/api/dashboard/build", json={}).json()
    assert len(d["entities"]) == 1 and d["entities"][0]["fiscal_years"] == [2030, 2031]
    assert d["stats"]["cross_document_duplicates"] == 2                    # 2030 revenue + profit seen twice, used once
    rev = next(ch for ch in d["charts"] if ch["title"] == "Revenue trend")
    unit = d["entities"][0]["unit"]
    vals = {r["x"]: r["revenue_from_operations"] for r in rev["rows"]}
    if unit == "thousand":
        assert vals == {"FY2030": 500000.0, "FY2031": 600000.0}
    else:
        assert unit == "million" and vals == {"FY2030": 500.0, "FY2031": 600.0}
    # growth is a calculation: only after the inputs are verified
    assert not any(k["label"] == "Revenue growth" for k in d["kpis"])
    assert any(p["label"] == "Revenue growth" and p["status"] == "needs_verification" for p in d["pending_verification"])
    for doc in (a, b):
        verify_unvalidated(c, doc, {"revenue_from_operations", "net_profit"})
    d = c.post("/api/dashboard/build", json={}).json()
    g = next(k for k in d["kpis"] if k["label"] == "Revenue growth")
    assert g["value"] == "20.0000" and g["origin"] == "calculated" and g["sources"][0]["formula"]
    m = next(k for k in d["kpis"] if k["label"] == "Net profit margin")
    assert m["value"] == "11.0000"


def test_different_organisations_stay_separate_and_filters_apply():
    c = client_for(f"dash3-{uuid.uuid4().hex[:6]}@example.com")
    x = _upload(c, "x.csv", "Amounts in million\nParticulars,2030\nRevenue from operations,100\n")
    y = _upload(c, "y.csv", "Amounts in million\nParticulars,2030\nRevenue from operations,300\n")
    drain()
    _org(c, x, "Synthetic Alpha")
    _org(c, y, "Synthetic Beta")
    d = c.post("/api/dashboard/build", json={}).json()
    assert len(d["entities"]) == 2 and d["stats"]["cross_document_duplicates"] == 0
    cmp_ = next(ch for ch in d["charts"] if ch["id"] == "all:cmp_revenue")
    assert sorted(r["value"] for r in cmp_["rows"]) == [100.0, 300.0]
    only = c.post("/api/dashboard/build", json={"document_ids": [y]}).json()
    assert [k["value"] for k in only["kpis"] if k["label"].endswith("Revenue")] == ["300"]
    assert c.post("/api/dashboard/build", json={"fiscal_years": [2031]}).json()["kpis"] == []


def test_saved_dashboard_is_recomputed_and_isolated():
    c = client_for(f"dash4-{uuid.uuid4().hex[:6]}@example.com")
    other = client_for(f"dash4o-{uuid.uuid4().hex[:6]}@example.com")
    doc = _upload(c, "s.csv", "Amounts in million\nParticulars,2030\nTotal assets,700\n")
    drain()
    sid = c.post("/api/dashboards", json={"name": "Board view", "filters": {"document_ids": [doc]}, "layout": {"hidden_charts": []}}).json()["id"]
    assert c.post("/api/dashboards", json={"name": "Board view"}).status_code == 409
    opened = c.get(f"/api/dashboards/{sid}").json()
    assert opened["dashboard"]["kpis"][0]["value"] == "700"
    assert other.get(f"/api/dashboards/{sid}").status_code == 404
    assert other.delete(f"/api/dashboards/{sid}").status_code == 404
    assert other.get("/api/dashboards").json() == []
    assert other.post("/api/dashboard/build", json={"document_ids": [doc]}).json()["kpis"] == []   # foreign ids ignored
    md = c.post("/api/dashboard/export.md", json={"document_ids": [doc]}).text
    assert "| Total assets | 700 |" in md
    c.delete(f"/api/documents/{doc}")                                     # deleting the document empties the saved view
    assert c.get(f"/api/dashboards/{sid}").json()["dashboard"]["kpis"] == []
    assert c.delete(f"/api/dashboards/{sid}").status_code == 200


def test_scenario_is_python_and_labelled_hypothetical():
    from app.rag.dashboard_context import dashboard_sources, scenario_sources
    d = {"kpis": [{"id": "e:revenue", "label": "Revenue", "value": "500", "unit": "million", "currency": None, "fiscal_year": 2030,
                   "origin": "reported", "sources": [{"kind": "reported", "filename": "a.csv", "location_text": "row 3", "validation_status": "validated"}]},
                  {"id": "e:net_margin", "label": "Net profit margin", "value": "11.0000", "unit": "%", "currency": None, "fiscal_year": 2030,
                   "origin": "calculated", "sources": [{"kind": "calculated", "formula": "net profit / revenue × 100"}]}],
         "charts": [], "pending_verification": [], "limitations": []}
    h = scenario_sources(d, "What happens if revenue grows by 10%?")
    assert len(h) == 1 and h[0]["sid"] == "H1" and h[0]["text"].startswith("HYPOTHETICAL SCENARIO")
    assert "would be 550 million" in h[0]["text"] and "implied net profit would be 60.5 million" in h[0]["text"]
    down = scenario_sources(d, "what if a 5% decline in revenue happens")
    assert "would be 475 million" in down[0]["text"]
    assert scenario_sources(d, "Explain the revenue trend") == []
    assert scenario_sources(d, "What if EBITDA grows by 10%?") == []          # no EBITDA on the dashboard: nothing invented
    src = dashboard_sources(d, "revenue", None)
    assert src[0]["sid"] == "D1" and "KPI 'Revenue' = 500 million for FY2030" in src[0]["text"] and "a.csv, row 3" in src[0]["text"]


def test_dashboard_chat_cites_dashboard_and_is_isolated(monkeypatch):
    """Scripted LLM test double: checks plumbing and verification, not answer quality."""
    from app.llm import client as llm
    c = client_for(f"dchat-{uuid.uuid4().hex[:6]}@example.com")
    other = client_for(f"dchato-{uuid.uuid4().hex[:6]}@example.com")
    doc = _upload(c, "c.csv", "Amounts in million\nParticulars,2030\nRevenue from operations,500\n")
    drain()
    seen = {}

    def fake(messages, ep, **k):
        seen["prompt"] = messages[-1]["content"]
        seen["system"] = messages[0]["content"]
        return {"content": "Revenue for FY2030 was 500 million [D1]. If it grew 10% it would be 550 million [H1].",
                "usage": {}, "latency_ms": 1, "model": "test-double"}
    monkeypatch.setattr(llm, "chat", fake)
    r = c.post("/api/dashboard/chat", json={"question": "What happens if revenue grows by 10%?"}).json()
    assert r["status"] == "answered" and r["scenario"] is True and {x["sid"] for x in r["citations"]} == {"D1", "H1"}
    assert "[D#] sources are the user's dashboard" in seen["system"] and 'id="H1" kind="scenario"' in seen["prompt"]
    sid = r["session_id"]
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "Revenue was 999 [D1].", "usage": {}, "latency_ms": 1, "model": "test-double"})
    r2 = c.post("/api/dashboard/chat", json={"question": "Explain revenue", "session_id": sid}).json()
    assert r2["status"] == "answered_with_warnings" and "999" in r2["verification"]["unsupported_numbers"]
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"content": "Revenue was 500 [D7].", "usage": {}, "latency_ms": 1, "model": "test-double"})
    assert c.post("/api/dashboard/chat", json={"question": "Explain revenue", "session_id": sid}).json()["status"] == "insufficient_evidence"
    assert other.post("/api/dashboard/chat", json={"question": "Explain revenue", "session_id": sid}).status_code == 404
    o = other.post("/api/dashboard/chat", json={"question": "Explain revenue", "filters": {"document_ids": [doc]}}).json()
    assert o["status"] == "insufficient_evidence" and not o["citations"]      # another user's document is not visible
    hist = c.get(f"/api/chat/sessions/{sid}").json()
    assert len(hist["messages"]) == 6 and hist["title"].startswith("Dashboard:")

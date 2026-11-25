"use client";

import { Download } from "lucide-react";
import { useState } from "react";
import DocPicker from "@/components/DocPicker";
import { Badge, Card, EmptyState, ErrorBox, Loading, MaybeValue, PageHeader, Warn } from "@/components/ui";
import { api, fmtResult } from "@/lib/api";
import type { Ratio } from "@/lib/types";

type Rep = {
  generated_at: string; overview: Record<string, string | number | null | string[]>[];
  financial_performance: { filename: string; period_label: string | null; basis: string | null; unit: string | null; currency: string | null; metrics: { metric_name: string; raw_value: string; validation_status: string; source: string }[] }[];
  trends: Ratio[]; ratios: Ratio[]; comparison: { warnings: string[] } | null; limitations: string[];
  ai_summary: { label: string; status: string; text: string; citations: { sid: string; filename?: string; location_text?: string }[] } | null;
};

export default function Reports() {
  const [docs, setDocs] = useState<string[]>([]);
  const [ai, setAi] = useState(false);
  const [rep, setRep] = useState<Rep | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const gen = async () => {
    setBusy(true); setError(null);
    try { setRep(await api<Rep>("/reports", { method: "POST", json: { document_ids: docs, include_ai_summary: ai } })); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const download = async () => {
    const res = await fetch("/api/reports/markdown", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_ids: docs, include_ai_summary: false }) });
    if (!res.ok) { setError(`Download failed (HTTP ${res.status})`); return; }
    const url = URL.createObjectURL(await res.blob()); const a = document.createElement("a"); a.href = url; a.download = "finrag-report.md"; a.click(); URL.revokeObjectURL(url);
  };
  return (
    <>
      <PageHeader title="Reports" subtitle="Financial analysis reports built from extracted, traceable values and Python calculations. Reports never contain investment recommendations." />
      <ErrorBox error={error} />
      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card title="Report scope">
          <DocPicker selected={docs} onChange={setDocs} />
          <label className="mt-3 flex items-center gap-2 text-xs"><input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} /> add AI-generated summary (cited, slower)</label>
          <button className="btn-primary mt-3 w-full justify-center" disabled={!docs.length || busy} onClick={gen}>{busy ? "Generating…" : "Generate report"}</button>
          {rep && <button className="btn-ghost mt-2 w-full justify-center" onClick={download}><Download className="h-4 w-4" /> Download Markdown</button>}
        </Card>
        <div className="space-y-6">
          {busy && <Loading label="Building report…" />}
          {!rep && !busy && <EmptyState title="No report generated yet.">Select one or more processed documents.</EmptyState>}
          {rep && (
            <>
              <Card title="1. Documents">
                <div className="overflow-x-auto"><table className="table"><thead><tr><th>File</th><th>Organisation</th><th>Period</th><th>Category</th><th>Currency</th><th>Unit</th></tr></thead>
                  <tbody>{rep.overview.map((o, i) => <tr key={i}><td>{String(o.filename)}</td><td>{String(o.organisation)}</td><td>{String(o.reporting_period)}</td><td>{String(o.category)}</td><td>{String(o.currency)}</td><td>{String(o.unit)}</td></tr>)}</tbody></table></div>
              </Card>
              <Card title="2. Financial performance (as reported)">
                {rep.financial_performance.length === 0 ? <p className="text-sm text-slate-500">No key financial metrics were extracted.</p> : rep.financial_performance.map((p, i) => (
                  <div key={i} className="mb-5">
                    <div className="mb-1 text-sm font-semibold">{p.filename} — {p.period_label || "period n/d"} <span className="font-normal text-slate-500">({p.basis || "basis n/d"}, unit: <MaybeValue value={p.unit} fallback="not stated" />, currency: <MaybeValue value={p.currency} />)</span></div>
                    <table className="table"><tbody>{p.metrics.map((m, j) => <tr key={j}><td>{m.metric_name}</td><td className="num font-medium">{m.raw_value}</td><td><Badge status={m.validation_status} /></td><td className="text-xs text-slate-500">{m.source}</td></tr>)}</tbody></table>
                  </div>))}
              </Card>
              <Card title="3. Trends">{rep.trends.length ? <ul className="space-y-1 text-sm">{rep.trends.map((r, i) => <li key={i}>{r.name}: <b>{fmtResult(r.result, r.result_unit)}</b> ({r.filename}, {r.period_label}, {r.basis || "basis n/d"})</li>)}</ul> : <p className="text-sm text-slate-500">No multi-period data available.</p>}</Card>
              <Card title="4. Profitability and ratios">{rep.ratios.length ? <ul className="space-y-1 text-sm">{rep.ratios.map((r, i) => <li key={i}>{r.name}: <b>{fmtResult(r.result, r.result_unit)}</b> — {r.formula} ({r.filename}, {r.period_label}, {r.basis || "basis n/d"})</li>)}</ul> : <p className="text-sm text-slate-500">No ratio could be computed from the available inputs.</p>}</Card>
              {rep.ai_summary && (
                <Card title={rep.ai_summary.label}><div className="mb-2"><Badge status={rep.ai_summary.status} /></div><p className="whitespace-pre-wrap text-sm">{rep.ai_summary.text}</p>
                  <ul className="mt-2 text-xs text-slate-500">{rep.ai_summary.citations.map((c) => <li key={c.sid}>[{c.sid}] {c.filename}, {c.location_text}</li>)}</ul></Card>)}
              <Card title="Limitations and missing information"><Warn><ul className="list-disc space-y-1 pl-4">{rep.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></Warn></Card>
            </>
          )}
        </div>
      </div>
    </>
  );
}

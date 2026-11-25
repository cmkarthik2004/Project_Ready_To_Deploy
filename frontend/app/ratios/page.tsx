"use client";

import { useState } from "react";
import DocPicker from "@/components/DocPicker";
import { Badge, Card, EmptyState, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api, fmtResult } from "@/lib/api";
import type { Ratio } from "@/lib/types";

export default function Ratios() {
  const [docs, setDocs] = useState<string[]>([]);
  const [res, setRes] = useState<Ratio[] | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setError(null);
    try { setRes((await api<{ results: Ratio[] }>("/analytics/ratios", { method: "POST", json: { document_ids: docs } })).results); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const shown = (res || []).filter((r) => showAll || r.status !== "insufficient_data");
  return (
    <>
      <PageHeader title="Financial Ratios" subtitle="Computed in Python (Decimal arithmetic) only when every input exists for the same document, fiscal year, basis and unit, and every input is validated by an accounting check or verified by a person. Ratios marked “needs verification” list the inputs to verify in Document Analysis." />
      <ErrorBox error={error} />
      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card title="Documents">
          <DocPicker selected={docs} onChange={setDocs} />
          <button className="btn-primary mt-3 w-full justify-center" onClick={run} disabled={busy}>{busy ? "Calculating…" : "Calculate ratios"}</button>
          <label className="mt-3 flex items-center gap-2 text-xs"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> also show ratios that could not be computed</label>
        </Card>
        <div className="space-y-4">
          {busy && <Loading />}
          {!res && !busy && <EmptyState title="No ratios calculated yet.">Select documents and press Calculate.</EmptyState>}
          {res && shown.length === 0 && <EmptyState title="No ratio could be computed.">The required inputs were not found in the selected documents. Tick the option on the left to see what is missing.</EmptyState>}
          {shown.map((r, i) => (
            <div key={i} className="card p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div><div className="font-semibold">{r.name}</div><div className="text-xs text-slate-500">{r.filename} · {r.period_label || "period n/d"} · basis: {r.basis || "not detected"} · unit: {r.unit || "not stated"}</div></div>
                <div className="flex items-center gap-3"><span className="num text-xl font-semibold">{fmtResult(r.result, r.result_unit)}</span><Badge status={r.status} /></div>
              </div>
              <div className="mt-2 text-xs"><span className="font-semibold">Formula:</span> {r.formula}</div>
              {r.missing.length > 0 && <div className="mt-1 text-xs text-slate-500">Missing inputs: {r.missing.join(", ")}</div>}
              {r.inputs.length > 0 && (
                <table className="table mt-2"><thead><tr><th>Input</th><th>Value</th><th>Period</th><th>Source</th><th>Validation</th></tr></thead>
                  <tbody>{r.inputs.map((x, j) => <tr key={j}><td>{x.key}</td><td className="num">{x.value.replace(/\.0+$/, "")}</td><td>{x.period_label}</td><td className="text-xs">{x.source || "derived"}</td><td><Badge status={x.validation_status} /></td></tr>)}</tbody></table>)}
              {r.warnings.length > 0 && <ul className="mt-2 list-disc pl-4 text-xs text-amber-700 dark:text-amber-300">{r.warnings.map((w, j) => <li key={j}>{w}</li>)}</ul>}
            </div>))}
        </div>
      </div>
    </>
  );
}

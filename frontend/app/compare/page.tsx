"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import DocPicker from "@/components/DocPicker";
import { Badge, Card, EmptyState, ErrorBox, Loading, PageHeader, Warn } from "@/components/ui";
import { api } from "@/lib/api";
import type { Metric } from "@/lib/types";

type Column = { column_id: string; document_id: string; filename: string; organisation: string | null; basis: string | null; unit: string | null; currency: string | null; period_label: string | null; values: Record<string, Metric> };
type Cmp = { documents: { id: string; filename: string; organisation: string | null; fiscal_year: string | null; currency: string | null; unit: string | null }[]; columns: Column[]; rows: { metric_key: string; metric_name: string; present_in: number }[]; warnings: string[] };
const COLORS = ["#2f6fed", "#0f9d76", "#d9822b", "#9b51e0", "#e0457b", "#1b9aaa"];

export default function Compare() {
  const [docs, setDocs] = useState<string[]>([]);
  const [lines, setLines] = useState(false);
  const [data, setData] = useState<Cmp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [chartKey, setChartKey] = useState<string>("");
  const run = async () => {
    setBusy(true); setError(null);
    try { const r = await api<Cmp>("/analytics/compare", { method: "POST", json: { document_ids: docs, include_line_items: lines } }); setData(r); setChartKey(r.rows.find((x) => x.present_in > 1)?.metric_key || ""); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  // Only columns that share the chart metric AND its unit are charted together.
  const chartCols = data && chartKey ? data.columns.filter((c) => c.values[chartKey]) : [];
  const units = new Set(chartCols.map((c) => c.unit));
  return (
    <>
      <PageHeader title="Compare Documents" subtitle="Select two or more documents. Documents may be from different organisations, the same organisation, or have no detected organisation; differences in currency, unit, period and basis are flagged." />
      <ErrorBox error={error} />
      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card title="Documents to compare">
          <DocPicker selected={docs} onChange={setDocs} />
          <label className="mt-3 flex items-center gap-2 text-xs"><input type="checkbox" checked={lines} onChange={(e) => setLines(e.target.checked)} /> include spreadsheet line items</label>
          <button className="btn-primary mt-3 w-full justify-center" disabled={docs.length < 2 || busy} onClick={run}>{busy ? "Comparing…" : "Compare"}</button>
          {docs.length < 2 && <p className="mt-2 text-xs text-slate-500">Select at least two documents.</p>}
        </Card>
        <div className="space-y-6">
          {busy && <Loading />}
          {!data && !busy && <EmptyState title="No comparison data available.">Choose documents and press Compare.</EmptyState>}
          {data && data.warnings.length > 0 && <Warn><ul className="list-disc space-y-1 pl-4">{data.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></Warn>}
          {data && data.columns.length === 0 && <EmptyState title="No comparable financial metrics were found in the selected documents." />}
          {data && data.columns.length > 0 && (
            <>
              <Card title="Chart" actions={
                <select className="input !w-auto !py-1 text-xs" value={chartKey} onChange={(e) => setChartKey(e.target.value)}>
                  <option value="">— choose metric —</option>{data.rows.map((r) => <option key={r.metric_key} value={r.metric_key}>{r.metric_name} ({r.present_in})</option>)}
                </select>}>
                {!chartKey ? <p className="text-sm text-slate-500">Choose a metric present in several columns.</p>
                  : units.size > 1 ? <Warn>The selected metric is reported in different units ({Array.from(units).map((u) => u || "not stated").join(", ")}), so it is not charted together. See the table below.</Warn>
                  : (
                    <div className="h-72"><ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartCols.map((c) => ({ name: `${c.filename.slice(0, 28)} · ${c.period_label || "?"} · ${c.basis || "n/d"}`, value: Number(c.values[chartKey].value) }))}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" /><XAxis dataKey="name" tick={{ fontSize: 10 }} interval={0} angle={-15} height={70} textAnchor="end" />
                        <YAxis width={80} tick={{ fontSize: 12 }} tickFormatter={(v) => Number(v).toLocaleString()} /><Tooltip formatter={(v) => Number(v).toLocaleString()} /><Legend />
                        <Bar dataKey="value" name={`${data.rows.find((r) => r.metric_key === chartKey)?.metric_name} (${Array.from(units)[0] || "unit not stated"})`} fill={COLORS[0]} />
                      </BarChart></ResponsiveContainer></div>)}
              </Card>
              <Card title="Side-by-side values (as printed)">
                <div className="overflow-x-auto"><table className="table">
                  <thead><tr><th>Metric</th>{data.columns.map((c) => <th key={c.column_id} className="min-w-36 normal-case"><div>{c.filename}</div><div className="font-normal">{c.period_label || "period n/d"} · {c.basis || "basis n/d"} · {c.unit || "unit n/d"}{c.currency ? ` · ${c.currency}` : ""}</div></th>)}</tr></thead>
                  <tbody>{data.rows.map((r) => (
                    <tr key={r.metric_key}><td className="font-medium">{r.metric_name}</td>
                      {data.columns.map((c) => { const v = c.values[r.metric_key]; return <td key={c.column_id} className="num" title={v ? `${v.location_text}` : ""}>{v ? <><div>{v.raw_value}</div><Badge status={v.validation_status} /></> : <span className="text-slate-400">—</span>}</td>; })}</tr>))}
                  </tbody></table></div>
                <p className="mt-2 text-xs text-slate-500">“—” means the metric was not found in that document/column. Hover a value for its source location.</p>
              </Card>
            </>
          )}
        </div>
      </div>
    </>
  );
}

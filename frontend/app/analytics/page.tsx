"use client";

import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import DocPicker from "@/components/DocPicker";
import { Badge, Card, EmptyState, ErrorBox, Loading, PageHeader, useApi } from "@/components/ui";
import { api } from "@/lib/api";

type Point = { period_label: string | null; period_sort: number | null; value: string; raw_value: string; validation_status: string };
type Series = { metric_key: string; metric_name: string; document_id: string; filename: string; organisation: string | null; basis: string | null; unit: string | null; currency: string | null; points: Point[] };
const COLORS = ["#2f6fed", "#0f9d76", "#d9822b", "#9b51e0", "#e0457b", "#1b9aaa", "#6b7280"];

export default function Analytics() {
  const avail = useApi<{ metric_key: string; metric_name: string; values: number; documents: number }[]>("/metrics/available");
  const [docs, setDocs] = useState<string[]>([]);
  const [keys, setKeys] = useState<string[]>([]);
  const [series, setSeries] = useState<Series[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState(false);

  useEffect(() => {
    if (!keys.length && avail.data?.length) {
      const pref = ["revenue_from_operations", "total_revenue", "net_profit", "total_assets"].filter((k) => avail.data!.some((a) => a.metric_key === k));
      setKeys(pref.length ? pref.slice(0, 2) : [avail.data[0].metric_key]);
    }
  }, [avail.data, keys.length]);
  useEffect(() => {
    if (!keys.length) return;
    setBusy(true);
    api<{ series: Series[] }>("/analytics/series", { method: "POST", json: { document_ids: docs, metric_keys: keys } })
      .then((r) => { setSeries(r.series); setError(null); }).catch((e) => setError(e.message)).finally(() => setBusy(false));
  }, [docs, keys]);

  // A chart is drawn per (metric, unit) only from series with >= 2 dated periods.
  const charts = useMemo(() => {
    const groups: Record<string, Series[]> = {};
    (series || []).forEach((s) => {
      const dated = s.points.filter((p) => p.period_sort != null && p.validation_status !== "failed_validation" && (review || p.validation_status !== "needs_review"));
      if (dated.length >= 2) (groups[`${s.metric_name}|${s.unit ?? "unit not stated"}`] ||= []).push({ ...s, points: dated });
    });
    return Object.entries(groups);
  }, [series, review]);

  return (
    <>
      <PageHeader title="Financial Analytics" subtitle="Charts and tables built only from values extracted from your documents. Series are kept separate by document, basis and unit." />
      <ErrorBox error={error || avail.error} />
      {avail.data && avail.data.length === 0 && <EmptyState title="No financial data available.">Upload and process financial documents to see analytics.</EmptyState>}
      {avail.data && avail.data.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <div className="space-y-6">
            <Card title="Documents"><DocPicker selected={docs} onChange={setDocs} /><p className="mt-2 text-xs text-slate-500">None selected = all processed documents.</p>
              <label className="mt-3 flex items-center gap-2 text-xs"><input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} /> include values that need review in charts</label></Card>
            <Card title="Metrics found in your documents">
              <div className="max-h-80 space-y-1 overflow-y-auto">{avail.data.map((a) => (
                <label key={a.metric_key} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={keys.includes(a.metric_key)} onChange={() => setKeys(keys.includes(a.metric_key) ? keys.filter((k) => k !== a.metric_key) : [...keys, a.metric_key])} />
                  <span className="flex-1">{a.metric_name}</span><span className="text-xs text-slate-500">{a.documents} doc</span>
                </label>))}</div>
            </Card>
          </div>
          <div className="space-y-6">
            {busy && <Loading />}
            {!busy && series && charts.length === 0 && (
              <Card><EmptyState title="Not enough data for a chart.">A trend chart needs at least two reporting periods of the same metric, document, basis and unit. The values found are listed below.</EmptyState></Card>
            )}
            {charts.map(([k, ss]) => {
              const [name, unit] = k.split("|");
              // x-axis = numeric period key, so "FY 2023-24" and "2023-24" share one position
              const sorts = Array.from(new Set(ss.flatMap((s) => s.points.map((p) => p.period_sort as number)))).sort((a, b) => a - b);
              const rows = sorts.map((sort) => {
                const labels = ss.flatMap((s) => s.points.filter((p) => p.period_sort === sort).map((p) => p.period_label || ""));
                const r: Record<string, string | number | null> = { period: labels.sort((a, b) => a.length - b.length)[0] || String(sort) };
                ss.forEach((s, i) => { const p = s.points.find((pp) => pp.period_sort === sort); r[`s${i}`] = p ? Number(p.value) : null; });
                return r;
              });
              return (
                <Card key={k} title={`${name} (${unit})`}>
                  <div className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={rows} margin={{ left: 10, right: 20 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="period" tick={{ fontSize: 12 }} /><YAxis tick={{ fontSize: 12 }} width={80} tickFormatter={(v) => Number(v).toLocaleString()} />
                        <Tooltip formatter={(v) => Number(v).toLocaleString()} /><Legend />
                        {ss.map((s, i) => <Line key={i} type="monotone" dataKey={`s${i}`} connectNulls name={`${s.filename} · ${s.basis || "basis n/d"}`} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot />)}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">Values as printed, in {unit}{ss[0].currency ? ` (${ss[0].currency})` : ", currency not detected"}. Periods ordered by the year stated in each column header.</p>
                </Card>);
            })}
            {series && series.length > 0 && (
              <Card title="All values">
                <div className="max-h-96 overflow-auto"><table className="table"><thead><tr><th>Metric</th><th>Document</th><th>Basis</th><th>Unit</th><th>Period</th><th>Value</th><th>Status</th></tr></thead>
                  <tbody>{series.flatMap((s) => s.points.map((p, i) => (
                    <tr key={`${s.metric_key}${s.document_id}${s.basis}${i}${p.period_label}`}><td>{s.metric_name}</td><td className="text-xs">{s.filename}</td><td>{s.basis || "—"}</td><td>{s.unit || "—"}</td><td>{p.period_label || "—"}</td><td className="num">{p.raw_value}</td><td><Badge status={p.validation_status} /></td></tr>)))}</tbody></table></div>
              </Card>
            )}
          </div>
        </div>
      )}
    </>
  );
}

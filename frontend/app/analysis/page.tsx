"use client";

import { Check, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import DocPicker from "@/components/DocPicker";
import { Badge, Card, EmptyState, ErrorBox, Loading, MaybeValue, PageHeader, useApi, Warn } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";
import type { Doc, MetaField, Metric } from "@/lib/types";

const META_LABELS: Record<string, string> = { organisation: "Organisation", reporting_period: "Reporting period", fiscal_year: "Financial year", category: "Document category", currency: "Currency", unit: "Units" };

function metaValue(f?: MetaField) {
  if (!f) return null;
  const v = f.value as unknown;
  if (v && typeof v === "object" && "label" in (v as object)) return (v as { label: string }).label;
  return v as string | null;
}

function MetadataCard({ doc, reload }: { doc: Doc; reload: () => void }) {
  const [edit, setEdit] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    try { await api(`/documents/${doc.id}/metadata`, { method: "PATCH", json: form }); setEdit(false); setForm({}); reload(); }
    catch (e) { setErr((e as Error).message); }
  };
  return (
    <Card title="Detected metadata" actions={<button className="btn-ghost !py-1" onClick={() => setEdit(!edit)}>{edit ? "Cancel" : "Correct metadata"}</button>}>
      <ErrorBox error={err} />
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(META_LABELS).map(([k, label]) => {
          const f = doc.metadata?.[k];
          return (
            <div key={k}>
              <dt className="label">{label}</dt>
              <dd className="text-sm">
                {f?.status === "uncertain" ? <span className="text-amber-700 dark:text-amber-300">Uncertain — needs verification{f.candidates?.length ? ` (mentioned: ${f.candidates.join(", ")})` : ""}</span>
                  : <MaybeValue value={metaValue(f)} />}
                {f && <span className="ml-2"><Badge status={f.status} /></span>}
                {f?.method && <div className="mt-1 text-xs text-slate-500">{f.method}{f.confidence ? ` · confidence ${Math.round(f.confidence * 100)}%` : ""}</div>}
                {f?.evidence?.snippet && <div className="mt-1 line-clamp-2 text-xs italic text-slate-400">“{f.evidence.snippet}”</div>}
                {edit && <input className="input mt-2" placeholder={`Set ${label.toLowerCase()}`} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />}
              </dd>
            </div>);
        })}
      </dl>
      {edit && <button className="btn-primary mt-4" onClick={save} disabled={!Object.values(form).some(Boolean)}>Save corrections</button>}
    </Card>
  );
}

function Metrics({ doc }: { doc: Doc }) {
  const [lines, setLines] = useState(false);
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useApi<{ total: number; status_counts: Record<string, number>; items: Metric[] }>(
    `/documents/${doc.id}/metrics?include_line_items=${lines}${status ? `&status=${status}` : ""}`, [lines, status]);
  const review = async (m: Metric, action: "verify" | "reject") => {
    const note = prompt(action === "verify" ? "Optional note: how did you verify this value?" : "Why is this value wrong?") ?? undefined;
    await api(`/metrics/${m.id}/${action}`, { method: "POST", json: { note } }); reload();
  };
  return (
    <Card title="Extracted financial values" actions={
      <div className="flex items-center gap-3 text-xs">
        <label className="flex items-center gap-1"><input type="checkbox" checked={lines} onChange={(e) => setLines(e.target.checked)} /> include line items</label>
        <select className="input !w-auto !py-1 text-xs" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">all statuses</option>{["validated", "unvalidated", "needs_review", "failed_validation", "verified", "rejected"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>}>
      <ErrorBox error={error} />
      {loading && <Loading />}
      {data && <div className="mb-3 flex flex-wrap gap-2">{Object.entries(data.status_counts).map(([k, v]) => <span key={k} className="flex items-center gap-1 text-xs"><Badge status={k} />{v}</span>)}</div>}
      {data && data.total === 0 && <EmptyState title="No financial values were extracted from this document." />}
      {data && data.total > 0 && (
        <div className="max-h-[32rem] overflow-auto">
          <table className="table">
            <thead className="sticky top-0"><tr><th>Metric</th><th>As printed</th><th>Unit</th><th>Column / period</th><th>Basis</th><th>Source location</th><th>Validation</th><th></th></tr></thead>
            <tbody>{data.items.map((m) => (
              <tr key={m.id}>
                <td><div className="font-medium">{m.metric_name}</div><div className="text-xs text-slate-500">label: “{m.raw_label}”</div></td>
                <td className="num whitespace-nowrap font-medium">{m.raw_value}</td>
                <td><MaybeValue value={m.unit} fallback="not stated" /></td>
                <td><MaybeValue value={m.period_label} /></td>
                <td><MaybeValue value={m.basis} /></td>
                <td className="text-xs">{m.location_text}</td>
                <td><Badge status={m.validation_status} />
                  <details className="mt-1 text-xs text-slate-500"><summary className="cursor-pointer">notes ({m.validation_notes.length})</summary>
                    <ul className="mt-1 space-y-1">{m.validation_notes.map((n, i) => <li key={i}><b>{n.check}</b>: {n.detail}</li>)}</ul></details></td>
                <td className="whitespace-nowrap">
                  <button className="btn-ghost !px-1.5 !py-1" title="Mark verified" onClick={() => review(m, "verify")}><Check className="h-3.5 w-3.5" /></button>{" "}
                  <button className="btn-ghost !px-1.5 !py-1" title="Reject" onClick={() => review(m, "reject")}><X className="h-3.5 w-3.5" /></button>
                </td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Detail({ id }: { id: string }) {
  const { data: d, error, loading, reload } = useApi<Doc>(`/documents/${id}`, [id]);
  const tables = useApi<{ total: number; items: { id: string; index: number; title: string | null; location_text: string; header: string[]; rows: string[][]; n_rows: number }[] }>(`/documents/${id}/tables?limit=20`, [id]);
  const chunks = useApi<{ total: number; items: { id: string; index: number; text: string; location_text: string; injection_flag: boolean }[] }>(`/documents/${id}/chunks?limit=10`, [id]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!d) return null;
  return (
    <div className="space-y-6">
      <Card title={d.filename}>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <Badge status={d.status} /><span>{d.file_format.toUpperCase()}</span>
          {d.page_count != null && <span>{d.page_count} PDF pages</span>}{d.sheet_names && <span>Sheets: {d.sheet_names.join(", ")}</span>}
          {d.row_count != null && <span>{d.row_count} CSV rows</span>}<span>{d.table_count} tables</span><span>{d.chunk_count} chunks indexed</span>
          <span>Uploaded {fmtDate(d.uploaded_at)}</span>{d.ocr_pages?.length ? <span>OCR on pages {d.ocr_pages.join(", ")}</span> : null}
          <a className="text-brand-600 hover:underline" href={`/api/documents/${d.id}/file`}>Download original</a>
        </div>
        {d.status === "failed" && <div className="mt-3"><ErrorBox error={d.error_message} /></div>}
        {d.warnings?.length > 0 && <div className="mt-3"><Warn><ul className="list-disc pl-4">{d.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></Warn></div>}
      </Card>
      <MetadataCard doc={d} reload={reload} />
      {d.statements && d.statements.length > 0 && (
        <Card title="Financial statements identified">
          <table className="table"><thead><tr><th>Statement</th><th>Basis</th><th>Unit</th><th>Columns</th><th>Location</th></tr></thead>
            <tbody>{d.statements.map((s) => <tr key={s.id}><td>{s.statement_type.replaceAll("_", " ")}</td><td><MaybeValue value={s.basis} /></td><td><MaybeValue value={s.unit} /></td><td className="text-xs">{s.periods.slice(0, 6).join(" · ")}</td><td className="text-xs">{s.location_text}</td></tr>)}</tbody></table>
        </Card>
      )}
      {d.status === "processed" && <Metrics doc={d} />}
      {d.validation_checks && d.validation_checks.length > 0 && (
        <Card title={`Accounting checks run (${d.validation_checks.length})`}>
          <div className="max-h-80 overflow-auto"><table className="table"><thead><tr><th>Check</th><th>Column</th><th>Left side</th><th>Right side</th><th>Difference</th><th>Result</th></tr></thead>
            <tbody>{d.validation_checks.map((c, i) => <tr key={i}><td>{c.description}</td><td>{c.period}</td><td className="num">{c.lhs}</td><td className="num">{c.rhs}</td><td className="num">{c.difference}</td><td><Badge status={c.result} /></td></tr>)}</tbody></table></div>
        </Card>
      )}
      <Card title={`Tables (${tables.data?.total ?? 0})`}>
        {tables.data?.items.length ? tables.data.items.map((t) => (
          <details key={t.id} className="mb-2 rounded-lg border border-slate-200 p-2 text-sm dark:border-slate-700">
            <summary className="cursor-pointer">Table {t.index + 1}{t.title ? ` — ${t.title}` : ""} · {t.n_rows} rows · {t.location_text}</summary>
            <div className="mt-2 overflow-x-auto"><table className="table"><thead><tr>{t.header.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
              <tbody>{t.rows.slice(0, 50).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="num">{c}</td>)}</tr>)}</tbody></table></div>
          </details>)) : <p className="text-sm text-slate-500">No tables found.</p>}
      </Card>
      <Card title={`Indexed chunks (showing ${chunks.data?.items.length ?? 0} of ${chunks.data?.total ?? 0})`}>
        {chunks.data?.items.map((c) => <div key={c.id} className="mb-3 rounded-lg bg-slate-50 p-2 text-xs dark:bg-slate-800/60"><div className="font-semibold">#{c.index} · {c.location_text} {c.injection_flag && <Badge status="needs_review" />}</div><div className="mt-1 line-clamp-4 whitespace-pre-wrap">{c.text}</div></div>)}
      </Card>
      {d.jobs?.[0] && (
        <Card title="Processing log (latest job)">
          <table className="table"><thead><tr><th>Stage</th><th>Seconds</th><th>Details</th></tr></thead>
            <tbody>{d.jobs[0].log.map((l, i) => { const { stage, seconds, ...rest } = l as Record<string, unknown>; return <tr key={i}><td>{String(stage)}</td><td className="num">{seconds != null ? String(seconds) : ""}</td><td className="text-xs">{JSON.stringify(rest)}</td></tr>; })}</tbody></table>
        </Card>
      )}
    </div>
  );
}

function AnalysisInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const id = sp.get("doc");
  return (
    <>
      <PageHeader title="Document Analysis" subtitle="Everything FinRAG extracted from one document, with source locations and validation status." />
      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card title="Document"><DocPicker single selected={id ? [id] : []} onChange={(ids) => router.push(`/analysis?doc=${ids[0]}`)} /></Card>
        <div>{id ? <Detail id={id} /> : <EmptyState title="Select a document">Choose a processed document to see its extracted information.</EmptyState>}</div>
      </div>
    </>
  );
}

export default function Analysis() { return <Suspense fallback={<Loading />}><AnalysisInner /></Suspense>; }

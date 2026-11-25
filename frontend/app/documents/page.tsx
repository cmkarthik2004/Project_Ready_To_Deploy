"use client";

import Link from "next/link";
import { Download, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Card, EmptyState, ErrorBox, Loading, MaybeValue, PageHeader, useApi } from "@/components/ui";
import { api, fmtBytes, fmtDate } from "@/lib/api";
import type { Doc } from "@/lib/types";

export default function Library() {
  const [q, setQ] = useState(""); const [fmt, setFmt] = useState(""); const [status, setStatus] = useState("");
  const params = new URLSearchParams({ ...(q && { q }), ...(fmt && { file_format: fmt }), ...(status && { status }) }).toString();
  const { data, error, loading, reload } = useApi<{ total: number; items: Doc[] }>(`/documents?${params}`, [params]);
  const [err, setErr] = useState<string | null>(null);
  const busy = data?.items.some((d) => ["queued", "processing"].includes(d.status));
  useEffect(() => { if (!busy) return; const t = setInterval(reload, 4000); return () => clearInterval(t); }, [busy, reload]);

  const del = async (d: Doc) => {
    if (!confirm(`Delete "${d.filename}"? This removes the file, its extracted data and its search index.`)) return;
    try { await api(`/documents/${d.id}`, { method: "DELETE" }); reload(); } catch (e) { setErr((e as Error).message); }
  };
  const reprocess = async (d: Doc) => { try { await api(`/documents/${d.id}/reprocess`, { method: "POST" }); reload(); } catch (e) { setErr((e as Error).message); } };

  return (
    <>
      <PageHeader title="Document Library" subtitle="All files you have uploaded, with their detected metadata and real processing status." actions={<Link href="/upload" className="btn-primary">Upload</Link>} />
      <ErrorBox error={error || err} />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <input className="input" placeholder="Search filename…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input" value={fmt} onChange={(e) => setFmt(e.target.value)}>
            <option value="">All formats</option>{["pdf", "docx", "xlsx", "xls", "csv"].map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
          </select>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>{["queued", "processing", "processed", "failed"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        {loading && !data && <Loading />}
        {data && data.total === 0 && <EmptyState title={params ? "No documents match these filters." : "No documents uploaded yet."}>Upload an annual report, statement or financial spreadsheet to begin analysis.</EmptyState>}
        {data && data.total > 0 && (
          <div className="overflow-x-auto">
            <table className="table">
              <thead><tr><th>Filename</th><th>Format</th><th>Organisation</th><th>Reporting period</th><th>Uploaded</th><th>Status</th><th>Size</th><th>Structure</th><th className="text-right">Actions</th></tr></thead>
              <tbody>{data.items.map((d) => (
                <tr key={d.id}>
                  <td className="max-w-64"><Link className="font-medium text-brand-600 hover:underline" href={`/analysis?doc=${d.id}`}>{d.filename}</Link>
                    {d.status === "failed" && <div className="mt-1 text-xs text-red-700">{d.error_message}</div>}
                    {d.warnings?.length > 0 && <div className="mt-1 text-xs text-amber-700">{d.warnings.length} warning(s)</div>}</td>
                  <td>{d.file_format.toUpperCase()}</td>
                  <td><MaybeValue value={d.organisation} /></td>
                  <td><MaybeValue value={d.reporting_period || d.fiscal_year} /></td>
                  <td className="whitespace-nowrap">{fmtDate(d.uploaded_at)}</td>
                  <td><Badge status={d.status} /></td>
                  <td className="whitespace-nowrap">{fmtBytes(d.file_size)}</td>
                  <td className="whitespace-nowrap text-xs text-slate-500">{d.page_count != null && `${d.page_count} pages`}{d.sheet_names && `${d.sheet_names.length} sheet(s)`}{d.row_count != null && `${d.row_count} rows`}<br />{d.chunk_count} chunks · {d.metric_count} values</td>
                  <td className="whitespace-nowrap text-right">
                    <a className="btn-ghost !px-2 !py-1" title="Download original" href={`/api/documents/${d.id}/file`}><Download className="h-4 w-4" /></a>{" "}
                    <button className="btn-ghost !px-2 !py-1" title="Reprocess" onClick={() => reprocess(d)} disabled={["queued", "processing"].includes(d.status)}><RefreshCw className="h-4 w-4" /></button>{" "}
                    <button className="btn-danger !px-2 !py-1" title="Delete" onClick={() => del(d)}><Trash2 className="h-4 w-4" /></button>
                  </td>
                </tr>))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

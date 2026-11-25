"use client";

import Link from "next/link";
import { CheckCircle2, FileUp, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Card, ErrorBox, PageHeader, useApi } from "@/components/ui";
import { api, fmtBytes } from "@/lib/api";
import type { Doc } from "@/lib/types";

type Result = { filename: string; accepted: boolean; error?: string; document?: Doc };
const ACCEPT = ".pdf,.docx,.xlsx,.xls,.csv";

export default function UploadPage() {
  const limits = useApi<{ max_upload_mb: number; max_files_per_request: number }>("/settings/limits");
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Result[]>([]);
  const [live, setLive] = useState<Record<string, Doc>>({});
  const input = useRef<HTMLInputElement>(null);

  const add = (list: FileList | null) => {
    if (!list) return;
    const ok = Array.from(list).filter((f) => /\.(pdf|docx|xlsx|xls|csv)$/i.test(f.name));
    const bad = Array.from(list).filter((f) => !ok.includes(f));
    setError(bad.length ? `Not added (unsupported type): ${bad.map((f) => f.name).join(", ")}` : null);
    setFiles((cur) => [...cur, ...ok.filter((f) => !cur.some((c) => c.name === f.name && c.size === f.size))]);
  };

  const upload = async () => {
    setBusy(true); setError(null);
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    try {
      const r = await api<{ results: Result[] }>("/documents", { method: "POST", body: fd });
      setResults(r.results); setFiles([]);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  // Poll the real processing status of accepted documents until they finish.
  const poll = useCallback(async () => {
    const ids = results.filter((r) => r.accepted && r.document).map((r) => r.document!.id);
    const pending = ids.filter((id) => !live[id] || ["queued", "processing"].includes(live[id].status));
    if (!pending.length) return;
    const upd: Record<string, Doc> = {};
    await Promise.all(pending.map(async (id) => { try { upd[id] = await api<Doc>(`/documents/${id}`); } catch {} }));
    setLive((l) => ({ ...l, ...upd }));
  }, [results, live]);
  useEffect(() => { if (!results.length) return; const t = setInterval(poll, 3000); poll(); return () => clearInterval(t); }, [results, poll]);

  return (
    <>
      <PageHeader title="Upload Documents" subtitle="Upload your own financial documents: PDF, Word (.docx), Excel (.xlsx, .xls) or CSV. FinRAG detects the organisation, period, currency, units and financial metrics automatically." />
      <ErrorBox error={error} />
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
        className={`card flex cursor-pointer flex-col items-center justify-center border-2 border-dashed px-6 py-14 text-center transition ${drag ? "border-brand-500 bg-brand-50 dark:bg-brand-700/10" : "border-slate-300 dark:border-slate-700"}`}>
        <FileUp className="mb-3 h-10 w-10 text-brand-600" />
        <div className="font-medium">Drag and drop files here, or click to choose</div>
        <div className="mt-1 text-sm text-slate-500">PDF · DOCX · XLSX · XLS · CSV
          {limits.data && ` — up to ${limits.data.max_upload_mb} MB each, ${limits.data.max_files_per_request} files per upload`}</div>
        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </div>

      {files.length > 0 && (
        <Card title={`${files.length} file(s) ready`} className="mt-6" actions={<button className="btn-primary" onClick={upload} disabled={busy}>{busy ? "Uploading…" : "Upload and process"}</button>}>
          <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">{files.map((f) => (
            <li key={f.name + f.size} className="flex items-center justify-between py-2"><span className="truncate">{f.name}</span>
              <span className="flex items-center gap-3 text-slate-500">{fmtBytes(f.size)}
                <button className="text-red-600 hover:underline" onClick={() => setFiles(files.filter((x) => x !== f))}>Remove</button></span></li>))}
          </ul>
        </Card>
      )}

      {results.length > 0 && (
        <Card title="Upload results and processing status" className="mt-6">
          <div className="overflow-x-auto">
            <table className="table">
              <thead><tr><th>File</th><th>Upload</th><th>Processing</th><th>Details</th></tr></thead>
              <tbody>{results.map((r, i) => {
                const d = r.document ? live[r.document.id] || r.document : undefined;
                const stage = d?.jobs?.[0]?.stage;
                return (
                  <tr key={i}>
                    <td className="font-medium">{r.filename}</td>
                    <td>{r.accepted ? <span className="flex items-center gap-1 text-emerald-700"><CheckCircle2 className="h-4 w-4" /> accepted</span>
                      : <span className="flex items-center gap-1 text-red-700"><XCircle className="h-4 w-4" /> rejected</span>}</td>
                    <td>{d ? <span className="flex items-center gap-2"><Badge status={d.status} />{d.status === "processing" && stage && <span className="text-xs text-slate-500">stage: {stage}</span>}</span> : "—"}</td>
                    <td className="text-sm">
                      {!r.accepted && <span className="text-red-700">{r.error}</span>}
                      {d?.status === "failed" && <span className="text-red-700">{d.error_message}</span>}
                      {d?.status === "processed" && <span>{d.chunk_count} chunks indexed · {d.metric_count} values extracted · <Link className="text-brand-600 hover:underline" href={`/analysis?doc=${d.id}`}>view analysis</Link></span>}
                    </td>
                  </tr>);
              })}</tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

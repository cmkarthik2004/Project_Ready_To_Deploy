"use client";

import { useEffect, useState } from "react";
import DocPicker from "@/components/DocPicker";
import { Badge, Card, EmptyState, ErrorBox, Loading, PageHeader, useApi } from "@/components/ui";
import { api, fmtDate } from "@/lib/api";

type Run = { id: string; kind: string; status: string; method: string; dataset: Record<string, unknown>; metrics: Record<string, unknown>; model_info: Record<string, unknown>; error: string | null; started_at: string; finished_at: string | null; details?: Record<string, unknown>[] };

const pct = (v: unknown) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : v === null || v === undefined ? "—" : String(v));

export default function Evaluation() {
  const runs = useApi<Run[]>("/evaluations");
  const methods = useApi<Record<string, string>>("/evaluations/methods");
  const [kind, setKind] = useState("extraction");
  const [docs, setDocs] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [sel, setSel] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = runs.data?.some((r) => r.status === "running");
  useEffect(() => { if (!running) return; const t = setInterval(runs.reload, 4000); return () => clearInterval(t); }, [running, runs.reload]);

  const start = async () => {
    setError(null);
    const fd = new FormData(); fd.append("kind", kind); fd.append("document_ids", docs.join(",")); if (file) fd.append("gold_file", file);
    try { await api("/evaluations", { method: "POST", body: fd }); runs.reload(); } catch (e) { setError((e as Error).message); }
  };
  const open = async (r: Run) => setSel(await api<Run>(`/evaluations/${r.id}`));

  return (
    <>
      <PageHeader title="Evaluation" subtitle="Results appear here only after an evaluation has actually been executed on your documents. Each run records its method, dataset and model." />
      <ErrorBox error={error || runs.error} />
      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card title="Run an evaluation">
          <label className="label">Type</label>
          <select className="input mb-2" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="extraction">Extraction consistency (no gold data)</option>
            <option value="extraction_gold">Extraction vs. gold values (JSONL)</option>
            <option value="rag">RAG Q&amp;A vs. gold questions (JSONL)</option>
          </select>
          {methods.data && <p className="mb-3 text-xs text-slate-500">{methods.data[kind]}</p>}
          {kind === "extraction" ? <DocPicker selected={docs} onChange={setDocs} /> : (
            <><label className="label">Gold file (.jsonl)</label><input type="file" accept=".jsonl,.json,.txt" onChange={(e) => setFile(e.target.files?.[0] || null)} className="text-sm" />
              <p className="mt-2 text-xs text-slate-500">You create the gold file from your own documents (expected values and locations you have checked). Format is documented in docs/EVALUATION.md.</p></>)}
          <button className="btn-primary mt-4 w-full justify-center" onClick={start} disabled={kind !== "extraction" && !file}>Start evaluation</button>
        </Card>
        <div className="space-y-6">
          {runs.loading && <Loading />}
          {runs.data && runs.data.length === 0 && <EmptyState title="No evaluation has been run yet.">Evaluation metrics are only shown after a run completes.</EmptyState>}
          {runs.data && runs.data.length > 0 && (
            <Card title="Evaluation runs">
              <div className="overflow-x-auto"><table className="table"><thead><tr><th>Started</th><th>Type</th><th>Status</th><th>Key results</th><th>Model</th><th></th></tr></thead>
                <tbody>{runs.data.map((r) => (
                  <tr key={r.id}><td className="whitespace-nowrap">{fmtDate(r.started_at)}</td><td>{r.kind}</td><td><Badge status={r.status} /></td>
                    <td className="text-xs">{r.status === "completed" ? Object.entries(r.metrics).filter(([, v]) => typeof v !== "object").map(([k, v]) => `${k}: ${k.includes("rate") || k.includes("accuracy") || k.includes("correct") || k.includes("faith") || k.includes("coverage") ? pct(v) : v}`).join(" · ") : r.error || "running…"}</td>
                    <td className="text-xs">{String(r.model_info.llm ?? "")}</td>
                    <td><button className="text-brand-600 hover:underline" onClick={() => open(r)}>details</button></td></tr>))}</tbody></table></div>
            </Card>
          )}
          {sel && (
            <Card title={`Run ${sel.id.slice(0, 8)} — ${sel.kind}`}>
              <p className="mb-3 text-sm"><b>Method:</b> {sel.method}</p>
              <p className="mb-3 text-sm"><b>Dataset:</b> {JSON.stringify(sel.dataset)}</p>
              <p className="mb-3 text-sm"><b>Models:</b> {JSON.stringify(sel.model_info)}</p>
              <pre className="max-h-96 overflow-auto rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-800">{JSON.stringify({ metrics: sel.metrics, details: sel.details }, null, 2)}</pre>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

"use client";

import { Loader2, Plus, Send, ShieldAlert, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import DocPicker from "@/components/DocPicker";
import { Badge, Card, ErrorBox, PageHeader, useApi, Warn } from "@/components/ui";
import { api, fmtDate, fmtResult } from "@/lib/api";
import type { ChatMsg } from "@/lib/types";

type Sess = { id: string; title: string; created_at: string; message_count: number; document_ids: string[]; messages?: ChatMsg[] };

function Answer({ m }: { m: ChatMsg }) {
  const [open, setOpen] = useState(false);
  const v = m.verification as { unsupported_numbers?: string[]; invalid_citations?: string[]; numbers_in_uncited_sources?: string[]; timings?: Record<string, number> };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <Badge status={m.status} />{m.model && <span>model: {m.model}</span>}{m.latency_ms != null && <span>· {(m.latency_ms / 1000).toFixed(1)} s</span>}
      </div>
      <div className="whitespace-pre-wrap text-sm leading-relaxed">{m.content}</div>
      {(v?.unsupported_numbers?.length || v?.invalid_citations?.length) ? (
        <Warn>
          {v.unsupported_numbers?.length ? <div>These numbers in the answer were not found in the cited sources (possible model arithmetic or error): <b>{v.unsupported_numbers.join(", ")}</b></div> : null}
          {v.invalid_citations?.length ? <div>The model cited sources that do not exist: {v.invalid_citations.join(", ")}</div> : null}
        </Warn>
      ) : null}
      {m.citations.length > 0 && (
        <div>
          <div className="label">Sources cited</div>
          <ul className="space-y-2">{m.citations.map((c) => (
            <li key={c.sid} className="rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-700">
              <div className="font-semibold">[{c.sid}] {c.kind === "calculation" ? "FinRAG calculation (Python)" : c.filename} <span className="font-normal text-slate-500">— {c.location_text}</span></div>
              <div className="mt-1 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{c.snippet}</div>
            </li>))}
          </ul>
        </div>
      )}
      {m.calculations?.length > 0 && (
        <div className="text-xs text-slate-500">Calculations provided to the model: {m.calculations.map((c) => `${c.name} ${fmtResult(c.result, c.result_unit)} (${c.period_label})`).join("; ")}</div>
      )}
      {m.evidence.length > 0 && (
        <button className="text-xs text-brand-600 hover:underline" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} all retrieved evidence ({m.evidence.length})</button>
      )}
      {open && (
        <ul className="space-y-2">{m.evidence.map((e) => (
          <li key={e.sid} className="rounded-lg bg-slate-50 p-2 text-xs dark:bg-slate-800/60">
            <div className="font-semibold">[{e.sid}] {e.filename || "calculation"} — {e.location_text} {e.score != null && <span className="font-normal text-slate-500">(rerank score {e.score})</span>}</div>
            <div className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap">{e.text}</div>
          </li>))}
        </ul>
      )}
    </div>
  );
}

export default function Chat() {
  const sessions = useApi<Sess[]>("/chat/sessions");
  const [sid, setSid] = useState<string | null>(null);
  const [sess, setSess] = useState<Sess | null>(null);
  const [docs, setDocs] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { if (!sid) { setSess(null); return; } api<Sess>(`/chat/sessions/${sid}`).then((s) => { setSess(s); setDocs(s.document_ids); }).catch((e) => setError(e.message)); }, [sid]);
  // Block body: an effect must return nothing or a cleanup function (scrollIntoView may return a Promise in newer browsers).
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [sess?.messages?.length, busy]);

  const ask = async () => {
    if (!q.trim()) return;
    setBusy(true); setError(null);
    try {
      let id = sid;
      if (!id) { const s = await api<Sess>("/chat/sessions", { method: "POST", json: { document_ids: docs } }); id = s.id; setSid(id); setSess(s); }
      const question = q; setQ("");
      setSess((s) => s ? { ...s, messages: [...(s.messages || []), { id: "pending", role: "user", content: question } as ChatMsg] } : s);
      await api<ChatMsg>(`/chat/sessions/${id}/messages`, { method: "POST", json: { question, document_ids: docs } });
      setSess(await api<Sess>(`/chat/sessions/${id}`)); sessions.reload();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const remove = async (id: string) => { await api(`/chat/sessions/${id}`, { method: "DELETE" }); if (id === sid) setSid(null); sessions.reload(); };

  return (
    <>
      <PageHeader title="AI Financial Chat" subtitle="Ask questions about your uploaded documents. Answers must cite the retrieved passages, extracted values or Python calculations; if evidence is insufficient FinRAG says so." />
      <ErrorBox error={error} />
      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card title="Documents in scope">
            <DocPicker selected={docs} onChange={setDocs} />
            <p className="mt-3 text-xs text-slate-500">{docs.length ? `${docs.length} selected.` : "None selected = all your processed documents."}</p>
          </Card>
          <Card title="Conversations" actions={<button className="btn-ghost !px-2 !py-1" onClick={() => setSid(null)}><Plus className="h-4 w-4" /></button>}>
            {sessions.data?.length ? (
              <ul className="space-y-1 text-sm">{sessions.data.map((s) => (
                <li key={s.id} className={`flex items-center justify-between rounded-lg px-2 py-1.5 ${s.id === sid ? "bg-brand-50 dark:bg-brand-700/20" : "hover:bg-slate-50 dark:hover:bg-slate-800"}`}>
                  <button className="min-w-0 flex-1 truncate text-left" onClick={() => setSid(s.id)} title={fmtDate(s.created_at)}>{s.title}</button>
                  <button aria-label="Delete conversation" onClick={() => remove(s.id)}><Trash2 className="h-3.5 w-3.5 text-slate-400 hover:text-red-600" /></button>
                </li>))}</ul>
            ) : <p className="text-sm text-slate-500">No conversations yet.</p>}
          </Card>
        </div>
        <Card className="flex min-h-[60vh] flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto">
            {!sess?.messages?.length && !busy && (
              <div className="py-10 text-center text-sm text-slate-500">
                <ShieldAlert className="mx-auto mb-2 h-6 w-6" />Ask about revenue, profit, expenses, risks, the balance sheet, or ask FinRAG to compare or calculate ratios from your documents.
              </div>
            )}
            {sess?.messages?.map((m) => (
              <div key={m.id} className={m.role === "user" ? "ml-auto max-w-[85%] rounded-xl bg-brand-600 px-4 py-2 text-sm text-white" : "max-w-full rounded-xl border border-slate-200 p-4 dark:border-slate-700"}>
                {m.role === "user" ? m.content : <Answer m={m} />}
              </div>
            ))}
            {busy && <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Retrieving evidence and generating an answer (CPU inference can take a minute or more)…</div>}
            <div ref={end} />
          </div>
          <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(); }}>
            <input className="input" placeholder="e.g. What is the total revenue in this document?" value={q} onChange={(e) => setQ(e.target.value)} disabled={busy} maxLength={2000} />
            <button className="btn-primary" disabled={busy || !q.trim()}><Send className="h-4 w-4" /></button>
          </form>
        </Card>
      </div>
    </>
  );
}

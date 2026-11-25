"use client";

import clsx from "clsx";
import {
  ArrowDownRight, ArrowUpRight, Bot, Calculator, ChevronDown, FileDown, Filter, Info, Loader2, Printer, Save, Send, ShieldCheck, Sparkles, X,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartCard } from "@/components/dashboard/Charts";
import { Badge, EmptyState, ErrorBox, Loading, Warn } from "@/components/ui";
import { api } from "@/lib/api";
import type { Chart, DashboardData, Filters, Kpi, Point } from "@/lib/viz";
import { download, fmtNum } from "@/lib/viz";

const EMPTY: Filters = { document_ids: [], organisations: [], fiscal_years: [], basis: null };
type Saved = { id: string; name: string; filters: Filters };
type Msg = { role: "user" | "assistant"; content: string; status?: string; citations?: { sid: string; kind: string; filename?: string; location_text?: string; snippet?: string }[];
  verification?: { unsupported_numbers?: string[] }; scenario?: boolean };

const ACCENTS = ["from-sky-500/15", "from-orange-500/15", "from-emerald-500/15", "from-amber-500/15", "from-pink-500/15", "from-green-600/15", "from-violet-500/15", "from-rose-500/15"];

function Chip({ on, children, onClick }: { on: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className={clsx("rounded-full border px-3 py-1 text-xs font-medium transition",
      on ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 bg-white text-slate-700 hover:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200")}>
      {children}
    </button>
  );
}

function KpiCard({ k, i, onOpen }: { k: Kpi; i: number; onOpen: () => void }) {
  const ch = k.change_pct !== null ? Number(k.change_pct) : null;
  const unit = [k.currency, k.unit].filter(Boolean).join(" ");
  return (
    <button onClick={onOpen} className={clsx("card group relative overflow-hidden bg-gradient-to-br to-transparent p-4 text-left transition hover:-translate-y-0.5 hover:shadow-md", ACCENTS[i % 8])}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">{k.label}</div>
        {k.origin === "calculated" ? <Calculator className="h-4 w-4 text-violet-500" aria-label="calculated" /> : <ShieldCheck className="h-4 w-4 text-slate-400" aria-label="reported" />}
      </div>
      <div className="num mt-2 text-2xl font-bold tracking-tight">
        {fmtNum(k.value, k.unit)}{k.unit === "%" ? "%" : k.unit === "times" ? "×" : ""}
        {unit && k.unit !== "%" && k.unit !== "times" && <span className="ml-1 text-sm font-medium text-slate-500">{unit}</span>}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        <span>FY{k.fiscal_year}</span>
        {ch !== null && (
          <span className={clsx("inline-flex items-center font-semibold", ch >= 0 ? "text-[var(--viz-up)]" : "text-[var(--viz-down)]")}>
            {ch >= 0 ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}{ch > 0 ? "+" : ""}{ch}% vs FY{k.previous_fiscal_year}
          </span>
        )}
        {ch === null && k.previous && <span>prev. {fmtNum(k.previous, k.unit)} (FY{k.previous_fiscal_year})</span>}
      </div>
      <div className="mt-2 flex flex-wrap gap-1"><Badge status={k.origin === "calculated" ? "calculated" : k.validation_status} />
        {k.origin === "inferred_mapping" && <Badge status="inferred mapping" />}</div>
    </button>
  );
}

function PointDetail({ p }: { p: Point }) {
  if (p.kind === "calculated") {
    return (
      <div className="space-y-1 text-xs">
        <div><span className="font-semibold">Calculated (Python):</span> {p.formula}</div>
        {p.value && <div>Result: <span className="num font-semibold">{p.value}</span></div>}
        {!!p.inputs?.length && <div className="font-semibold">Inputs</div>}
        <ul className="space-y-1">{p.inputs?.map((i, n) => {
          const ip = i as Point & { key?: string; source?: string | null };
          return <li key={n} className="rounded bg-slate-50 p-2 dark:bg-slate-800/60">{ip.key || ip.metric_key}: <span className="num font-medium">{ip.raw_value || (ip.value && ip.value.includes(".") ? ip.value.replace(/\.?0+$/, "") : ip.value)}</span>
            {" "}· {ip.source || `${ip.filename}, ${ip.location_text}`} <Badge status={ip.validation_status} /></li>;
        })}</ul>
        {p.warnings?.map((w) => <div key={w} className="text-slate-500">{w}</div>)}
      </div>
    );
  }
  return (
    <div className="space-y-1 text-xs">
      <div><span className="text-slate-500">Printed label:</span> “{p.raw_label}”</div>
      <div><span className="text-slate-500">Printed value:</span> <span className="num font-semibold">{p.raw_value}</span> <span className="text-slate-500">({p.period_label})</span></div>
      <div><span className="text-slate-500">Source:</span> <Link className="text-brand-600 hover:underline" href={`/analysis?doc=${p.document_id}`}>{p.filename}</Link> — {p.location_text}</div>
      <div className="flex gap-1"><Badge status={p.validation_status} />{p.value_origin === "inferred_mapping" && <Badge status="inferred mapping" />}</div>
      {!!p.alternatives?.length && (
        <details className="mt-1"><summary className="cursor-pointer text-slate-500">{p.alternatives.length} other occurrence(s)</summary>
          <ul className="mt-1 space-y-1">{p.alternatives.map((a, n) => <li key={n}>{a.raw_value} in {a.filename} · {a.note} <Badge status={a.validation_status} /></li>)}</ul>
        </details>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [data, setData] = useState<DashboardData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState<string>("");
  const [selectedX, setSelectedX] = useState<string | null>(null);
  const [drill, setDrill] = useState<{ title: string; points: [string, Point][] } | null>(null);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [showFilters, setShowFilters] = useState(false);
  // AI assistant
  const [chatOpen, setChatOpen] = useState(false);
  const [focus, setFocus] = useState<Chart | null>(null);
  const [q, setQ] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);
  // Block body: an effect must return nothing (scrollIntoView can return a Promise in current browsers).
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: busy ? "end" : "start", behavior: "smooth" }); }, [msgs.length, busy]);

  const load = useCallback(async (f: Filters) => {
    setLoading(true);
    try { setData(await api<DashboardData>("/dashboard/build", { method: "POST", json: f })); setErr(null); }
    catch (e) { setErr((e as Error).message); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(filters); }, [filters, load]);
  useEffect(() => { api<Saved[]>("/dashboards").then(setSaved).catch(() => {}); }, []);

  const toggle = <K extends keyof Filters>(key: K, v: Filters[K] extends (infer T)[] ? T : never) =>
    setFilters((f) => { const arr = f[key] as unknown[]; return { ...f, [key]: arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v] }; });

  const charts = useMemo(() => (data?.charts || []).filter((c) => !metric || c.series.some((s) => s.key === metric) ||
    Object.values(c.points).some((p) => p.metric_key === metric || p.calc_key === metric)), [data, metric]);

  const onSelect = (c: Chart, x: string) => {
    if (/^FY\d{4}$/.test(x)) setSelectedX((s) => (s === x ? null : x));
    const pts = x.includes("|") ? Object.entries(c.points).filter(([k]) => k === x) : Object.entries(c.points).filter(([k]) => k.startsWith(`${x}|`));
    setDrill({ title: `${c.title} — ${x.replace("|", " · ")}`, points: pts.map(([k, p]) => [c.series.find((s) => s.key === k.split("|")[1])?.label || k.split("|")[0], p]) });
  };

  const save = async () => {
    const name = prompt("Name for this dashboard view:");
    if (!name) return;
    try { await api("/dashboards", { method: "POST", json: { name, filters, layout: { metric } } }); setSaved(await api<Saved[]>("/dashboards")); }
    catch (e) { setErr((e as Error).message); }
  };
  const exportMd = async () => {
    try { download("finrag-dashboard.md", await api<string>("/dashboard/export.md", { method: "POST", json: filters }), "text/markdown"); }
    catch (e) { setErr((e as Error).message); }
  };
  const ask = async (question: string) => {
    if (!question.trim()) return;
    setChatOpen(true); setBusy(true); setQ("");
    setMsgs((m) => [...m, { role: "user", content: question + (focus ? `  (about: ${focus.title})` : "") }]);
    try {
      const r = await api<Msg & { session_id: string }>("/dashboard/chat", { method: "POST", json: { question, filters, chart_id: focus?.id ?? null, selected_x: selectedX, session_id: sessionId } });
      setSessionId(r.session_id);
      setMsgs((m) => [...m, { ...r, role: "assistant" }]);
    } catch (e) { setMsgs((m) => [...m, { role: "assistant", content: (e as Error).message, status: "error" }]); }
    finally { setBusy(false); }
  };

  const ent = data?.entities || [];
  return (
    <div className={clsx("transition-[padding]", chatOpen && "xl:pr-[400px]")}>
      <div className="mb-5 overflow-hidden rounded-2xl bg-gradient-to-r from-[#1a46a8] via-[#2a78d6] to-[#1baf7a] p-5 text-white shadow-md">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-white/80"><Sparkles className="h-4 w-4" /> Automatic financial dashboard</div>
            <h1 className="mt-1 text-2xl font-bold">{ent.length === 1 ? ent[0].name : ent.length > 1 ? `${ent.length} organisations` : "Financial Dashboard"}</h1>
            <p className="mt-1 text-sm text-white/85">
              {data ? <>Built from {data.stats.documents} document(s) · {data.stats.facts_used ?? 0} figures · basis: {data.basis || "not stated"}
                {ent.length === 1 && <> · {ent[0].currency ? `${ent[0].currency} ` : ""}{ent[0].unit || "unit not stated"} · FY{ent[0].fiscal_years.join(", FY")}</>}
                {data.stats.cross_document_duplicates ? <> · {data.stats.cross_document_duplicates} repeated figure(s) counted once</> : null}</> : "Loading…"}
            </p>
          </div>
          <div className="no-print flex flex-wrap gap-2">
            <button className="btn border border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => setShowFilters(!showFilters)}><Filter className="h-4 w-4" /> Filters</button>
            <button className="btn border border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={save}><Save className="h-4 w-4" /> Save view</button>
            <button className="btn border border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={exportMd}><FileDown className="h-4 w-4" /> Export</button>
            <button className="btn border border-white/30 bg-white/10 text-white hover:bg-white/20" onClick={() => window.print()}><Printer className="h-4 w-4" /> Print / PDF</button>
            <button className="btn bg-white text-brand-700 hover:bg-white/90" onClick={() => { setFocus(null); setChatOpen(true); }}><Bot className="h-4 w-4" /> Ask AI</button>
          </div>
        </div>
      </div>

      <ErrorBox error={err} />
      {data && (showFilters || filters.organisations.length + filters.fiscal_years.length + filters.document_ids.length > 0 || filters.basis) && (
        <div className="card no-print mb-5 space-y-3 p-4">
          {data.available.organisations.length > 1 && (
            <div className="flex flex-wrap items-center gap-2"><span className="label !mb-0 w-24">Company</span>
              {data.available.organisations.map((o) => <Chip key={o.id} on={filters.organisations.includes(o.id)} onClick={() => toggle("organisations", o.id)}>{o.name}</Chip>)}</div>)}
          <div className="flex flex-wrap items-center gap-2"><span className="label !mb-0 w-24">Fiscal year</span>
            {data.available.fiscal_years.map((y) => <Chip key={y} on={filters.fiscal_years.includes(y)} onClick={() => toggle("fiscal_years", y)}>FY{y}</Chip>)}</div>
          <div className="flex flex-wrap items-center gap-2"><span className="label !mb-0 w-24">Basis</span>
            {[null, ...data.available.bases].map((b) => <Chip key={String(b)} on={filters.basis === b} onClick={() => setFilters((f) => ({ ...f, basis: b }))}>{b === null ? "auto" : b.replace("_", " ")}</Chip>)}</div>
          <div className="flex flex-wrap items-center gap-2"><span className="label !mb-0 w-24">Documents</span>
            {data.available.documents.map((d) => <Chip key={d.id} on={filters.document_ids.includes(d.id)} onClick={() => toggle("document_ids", d.id)}>{d.filename}</Chip>)}</div>
          <div className="flex flex-wrap items-center gap-3"><span className="label !mb-0 w-24">Metric</span>
            <select className="input !w-auto !py-1 text-xs" value={metric} onChange={(e) => setMetric(e.target.value)}>
              <option value="">All charts</option>{data.available.metrics.map((m) => <option key={m} value={m}>{m.replaceAll("_", " ")}</option>)}</select>
            {saved.length > 0 && <select className="input !w-auto !py-1 text-xs" value="" onChange={(e) => { const s = saved.find((x) => x.id === e.target.value); if (s) setFilters({ ...EMPTY, ...s.filters }); }}>
              <option value="">Open saved view…</option>{saved.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}
            <button className="text-xs text-brand-600 hover:underline" onClick={() => { setFilters(EMPTY); setMetric(""); setSelectedX(null); }}>Reset</button>
          </div>
        </div>
      )}

      {loading && !data ? <Loading label="Building dashboard from your extracted data…" /> : data && data.kpis.length === 0 && data.charts.length === 0 ? (
        <EmptyState title={data.stats.documents ? "No financial figures match these filters." : "No documents yet."}>
          {data.limitations[0]} <Link href="/upload" className="text-brand-600 hover:underline">Upload documents</Link>
        </EmptyState>
      ) : data && (
        <>
          <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {data.kpis.map((k, i) => <KpiCard key={k.id} k={k} i={i} onOpen={() => setDrill({ title: `${k.label} — FY${k.fiscal_year}`, points: k.sources.map((p, n) => [n === 0 ? `FY${k.fiscal_year}` : `FY${k.previous_fiscal_year}`, p]) })} />)}
          </div>
          {(data.pending_verification.length > 0 || data.limitations.length > 0) && (
            <details className="card no-print mb-5 p-4 text-sm">
              <summary className="flex cursor-pointer items-center gap-2 font-medium"><Info className="h-4 w-4 text-amber-500" />
                {data.pending_verification.length} calculation(s) waiting for verified inputs · {data.limitations.length} note(s) on interpretation <ChevronDown className="h-4 w-4" /></summary>
              <div className="mt-3 grid gap-4 md:grid-cols-2">
                <ul className="space-y-1 text-xs">{data.pending_verification.map((p, i) => <li key={i}><Badge status={p.status} /> <b>{p.label}</b> (FY{p.fiscal_year}): {p.reason}</li>)}
                  {data.pending_verification.length > 0 && <li className="pt-1"><Link className="text-brand-600 hover:underline" href="/analysis">Verify values in Document Analysis →</Link></li>}</ul>
                <ul className="space-y-1 text-xs text-slate-600 dark:text-slate-300">{data.limitations.map((l, i) => <li key={i}>• {l}</li>)}</ul>
              </div>
            </details>
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {charts.map((c) => <ChartCard key={c.id} chart={c} selectedX={selectedX} onSelect={onSelect} onAsk={(ch) => { setFocus(ch); setChatOpen(true); }} />)}
          </div>
        </>
      )}

      {drill && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setDrill(null)}>
          <aside className="h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-xl dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex items-start justify-between"><h2 className="font-semibold">{drill.title}</h2>
              <button aria-label="Close" onClick={() => setDrill(null)}><X className="h-5 w-5" /></button></div>
            {drill.points.length === 0 ? <p className="text-sm text-slate-500">No value for this point.</p> :
              <ul className="space-y-3">{drill.points.map(([lab, p], i) => <li key={i} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700"><div className="mb-1 text-sm font-semibold">{lab}</div><PointDetail p={p} /></li>)}</ul>}
          </aside>
        </div>
      )}

      {chatOpen && (
        <aside className="no-print fixed bottom-0 right-0 top-0 z-30 flex w-full max-w-[400px] flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
            <div className="flex items-center gap-2 font-semibold"><Bot className="h-5 w-5 text-brand-600" /> Dashboard assistant</div>
            <button aria-label="Close assistant" onClick={() => setChatOpen(false)}><X className="h-5 w-5" /></button>
          </div>
          {focus && <div className="flex items-center justify-between bg-brand-50 px-4 py-2 text-xs text-brand-700 dark:bg-brand-700/20 dark:text-brand-100">
            About chart: <b className="truncate px-1">{focus.title}</b><button onClick={() => setFocus(null)} className="underline">clear</button></div>}
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {msgs.length === 0 && (
              <div className="space-y-2 text-xs text-slate-500">
                <p>Ask about the figures on this dashboard. Answers cite the dashboard data, extracted values and document passages; calculations are done in Python.</p>
                {["Explain the revenue trend.", "Generate an executive summary.", "Which financial metric needs attention?", "What happens if revenue grows by 10%?"].map((s) =>
                  <button key={s} className="block w-full rounded-lg border border-slate-200 px-3 py-2 text-left hover:border-brand-500 dark:border-slate-700" onClick={() => ask(s)}>{s}</button>)}
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} ref={i === msgs.length - 1 && !busy ? chatEnd : undefined} className={m.role === "user" ? "ml-8 rounded-xl bg-brand-600 px-3 py-2 text-sm text-white" : "rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700"}>
                {m.role === "assistant" && m.status && <div className="mb-1"><Badge status={m.status} />{m.scenario && <span className="ml-1"><Badge status="hypothetical scenario" /></span>}</div>}
                <div className="whitespace-pre-wrap">{m.content}</div>
                {!!m.verification?.unsupported_numbers?.length && <div className="mt-2"><Warn>Not found in the cited sources: {m.verification.unsupported_numbers.join(", ")}</Warn></div>}
                {!!m.citations?.length && <ul className="mt-2 space-y-1">{m.citations.map((c) => (
                  <li key={c.sid} className="rounded bg-slate-50 p-2 text-[11px] dark:bg-slate-800/60"><b>[{c.sid}]</b> {c.kind === "dashboard" ? "Dashboard data" : c.kind === "scenario" ? "Scenario (Python, hypothetical)" : c.kind === "calculation" ? "FinRAG calculation (Python)" : c.filename} — {c.location_text}
                    <div className="mt-0.5 line-clamp-3 text-slate-500">{c.snippet}</div></li>))}</ul>}
              </div>
            ))}
            {busy && <div className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Reading the dashboard and documents (CPU inference can take a minute)…</div>}
            {busy && <div ref={chatEnd} />}
          </div>
          <form className="flex gap-2 border-t border-slate-200 p-3 dark:border-slate-800" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
            <input className="input" placeholder={focus ? "Ask about this chart…" : "Ask about this dashboard…"} value={q} onChange={(e) => setQ(e.target.value)} disabled={busy} maxLength={1000} />
            <button className="btn-primary" disabled={busy || !q.trim()} aria-label="Send"><Send className="h-4 w-4" /></button>
          </form>
        </aside>
      )}
    </div>
  );
}

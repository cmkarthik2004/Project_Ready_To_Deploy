"use client";

import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";

export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const load = useCallback(async () => {
    if (!path) { setLoading(false); return; }
    setLoading(true);
    try { setData(await api<T>(path)); setError(null); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { load(); }, [load]);
  return { data, error, loading, reload: load, setData };
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, children, className, actions }: { title?: ReactNode; children: ReactNode; className?: string; actions?: ReactNode }) {
  return (
    <section className={clsx("card", className)}>
      {title && (
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className="num mt-2 text-2xl font-semibold">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 px-6 py-10 text-center dark:border-slate-700">
      <Inbox className="mb-3 h-8 w-8 text-slate-400" />
      <div className="font-medium">{title}</div>
      {children && <div className="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> <span>{error}</span>
    </div>
  );
}

export function Warn({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> <div>{children}</div>
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="flex items-center gap-2 py-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> {label}</div>;
}

const STATUS: Record<string, string> = {
  processed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  succeeded: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  answered: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  verified: "bg-emerald-600 text-white",
  validated: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  passed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  queued: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  processing: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  unvalidated: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  needs_review: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  answered_with_warnings: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  mismatch: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  uncertain: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  insufficient_data: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  insufficient_evidence: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  failed_validation: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  error: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  zero_denominator: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  needs_verification: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  invalid_input: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  calculated: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200",
  "inferred mapping": "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  "hypothetical scenario": "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200",
};

export function Badge({ status }: { status: string | null | undefined }) {
  const s = status || "unknown";
  return <span className={clsx("inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", STATUS[s] || "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300")}>{s.replaceAll("_", " ")}</span>;
}

/** Shows a value or an explicit "Not detected" — never a placeholder value. */
export function MaybeValue({ value, fallback = "Not detected" }: { value: ReactNode; fallback?: string }) {
  if (value === null || value === undefined || value === "") return <span className="italic text-slate-400">{fallback}</span>;
  return <>{value}</>;
}

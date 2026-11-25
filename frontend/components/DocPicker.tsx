"use client";

import { useApi } from "@/components/ui";
import type { Doc } from "@/lib/types";

/** Multi-select of the user's processed documents (real records only). */
export default function DocPicker({ selected, onChange, single = false }: { selected: string[]; onChange: (ids: string[]) => void; single?: boolean }) {
  const { data, loading, error } = useApi<{ items: Doc[] }>("/documents?status=processed&limit=500");
  if (loading) return <div className="text-sm text-slate-500">Loading documents…</div>;
  if (error) return <div className="text-sm text-red-600">{error}</div>;
  const docs = data?.items ?? [];
  if (!docs.length) return <div className="text-sm text-slate-500">No processed documents yet. Upload a document to begin analysis.</div>;
  const toggle = (id: string) => {
    if (single) return onChange([id]);
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  };
  return (
    <div className="max-h-64 space-y-1 overflow-y-auto pr-1">
      {!single && (
        <div className="mb-2 flex gap-2 text-xs">
          <button className="text-brand-600 hover:underline" onClick={() => onChange(docs.map((d) => d.id))}>Select all</button>
          <button className="text-brand-600 hover:underline" onClick={() => onChange([])}>Clear</button>
        </div>
      )}
      {docs.map((d) => (
        <label key={d.id} className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800">
          <input type={single ? "radio" : "checkbox"} checked={selected.includes(d.id)} onChange={() => toggle(d.id)} className="mt-1" />
          <span className="min-w-0">
            <span className="block truncate font-medium">{d.filename}</span>
            <span className="block text-xs text-slate-500">{d.file_format.toUpperCase()} · {d.organisation || "organisation not detected"} · {d.fiscal_year || d.reporting_period || "period not detected"}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

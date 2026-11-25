// Dashboard types and helpers. Every number shown comes from the /api/dashboard payload; nothing is computed here
// except presentation (formatting, CSV export, waterfall bar geometry).

export type Point = {
  kind: "reported" | "calculated"; value: string | null; metric_id?: string; metric_key?: string; raw_label?: string; raw_value?: string;
  period_label?: string | null; fiscal_year?: number; validation_status?: string; value_origin?: string; document_id?: string;
  filename?: string; location_text?: string | null; formula?: string; calc_key?: string; warnings?: string[];
  inputs?: (Point | { key: string; value: string; source: string | null; validation_status: string; period_label?: string | null })[];
  alternatives?: { filename: string; raw_value: string; validation_status: string; differs: boolean; note: string }[];
};
export type Series = { key: string; label: string; origin: string };
export type Row = { x: string; kind?: string } & Record<string, number | string | undefined>;
export type Chart = {
  id: string; entity: string; type: "bar" | "grouped_bar" | "stacked_bar" | "line" | "area" | "pie" | "donut" | "waterfall" | "heatmap" | "treemap";
  title: string; description: string; unit: string; series: Series[]; rows: Row[]; points: Record<string, Point>;
};
export type Kpi = {
  id: string; entity: string; label: string; value: string; unit: string | null; currency: string | null; fiscal_year: number;
  period_label: string | null; origin: string; validation_status: string; previous: string | null; previous_fiscal_year: number | null;
  change_pct: string | null; change_note?: string | null; formula?: string; sources: Point[];
};
export type DashboardData = {
  filters: Filters; basis: string | null; stats: Record<string, unknown> & { documents: number; facts_used?: number; cross_document_duplicates: number };
  available: { documents: { id: string; filename: string; organisation: string | null; format: string }[]; organisations: { id: string; name: string }[];
    fiscal_years: number[]; bases: string[]; metrics: string[] };
  kpis: Kpi[]; charts: Chart[]; pending_verification: { entity: string; label: string; fiscal_year: number; status: string; reason: string }[];
  limitations: string[]; entities: { id: string; name: string; unit: string | null; currency: string | null; fiscal_years: number[] }[];
};
export type Filters = { document_ids: string[]; organisations: string[]; fiscal_years: number[]; basis: string | null };

export const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);

/** Slot i of a chart's FULL series list (fixed order, never cycled: charts have at most 8 series). Hiding a series via
 *  the legend does not repaint the others, because the index comes from the full list, not the visible one. */
export const slot = (i: number) => SERIES[Math.min(i, 7)];

export function fmtNum(v: number | string | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  const locale = unit && /crore|lakh/.test(unit) ? "en-IN" : "en-US";
  const digits = Math.abs(n) >= 1000 ? 0 : Math.abs(n) >= 10 ? 1 : 2;
  return n.toLocaleString(locale, { maximumFractionDigits: digits });
}

export function compact(n: number, unit?: string | null): string {
  if (!Number.isFinite(n)) return "";
  if (unit && /crore|lakh/.test(unit)) return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function toCsv(c: Chart): string {
  const esc = (s: unknown) => { const t = s === undefined || s === null ? "" : String(s); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  const head = ["x", ...c.series.map((s) => `${s.label} (${c.unit})`), "sources"];
  const lines = [head.map(esc).join(",")];
  for (const r of c.rows) {
    const src = c.series.map((s) => c.points[`${r.x}|${s.key}`]).filter(Boolean)
      .map((p) => p!.kind === "reported" ? `${p!.filename} ${p!.location_text ?? ""} [${p!.validation_status}]` : `calculated: ${p!.formula}`).join("; ");
    lines.push([r.x, ...c.series.map((s) => r[s.key]), src].map(esc).join(","));
  }
  return lines.join("\n") + "\n";
}

export function download(name: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Diverging fill for growth heatmaps: blue (positive) ↔ neutral gray ↔ red (negative). */
export function divergingFill(v: number, maxAbs: number): string {
  const t = Math.min(1, Math.abs(v) / (maxAbs || 1));
  const pole = v >= 0 ? "var(--viz-pos)" : "var(--viz-neg)";
  return `color-mix(in oklab, ${pole} ${Math.round(15 + t * 75)}%, var(--viz-mid))`;
}

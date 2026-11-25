"use client";

import { Download, MessageSquareText, Table2 } from "lucide-react";
import { useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ReferenceLine,
  ResponsiveContainer, Tooltip, Treemap, XAxis, YAxis,
} from "recharts";
import { compact, divergingFill, download, fmtNum, slot, toCsv, type Chart, type Row } from "@/lib/viz";

const AXIS = { stroke: "var(--viz-axis)", tick: { fill: "var(--viz-muted)", fontSize: 11 }, tickLine: false } as const;
const GRID = <CartesianGrid stroke="var(--viz-grid)" strokeDasharray="0" vertical={false} />;

type Props = {
  chart: Chart;
  selectedX: string | null;
  onSelect: (chart: Chart, x: string) => void;
  onAsk: (chart: Chart) => void;
};

function TooltipBox({ active, payload, label, unit }: { active?: boolean; payload?: { name?: string; value?: number; color?: string; dataKey?: string; payload?: Row }[]; label?: string; unit: string }) {
  if (!active || !payload?.length) return null;
  const rows = payload.filter((p) => p.dataKey !== "__base" && p.value !== undefined && p.value !== null);
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-1 font-semibold text-slate-900 dark:text-slate-100">{label ?? rows[0]?.payload?.x}</div>
      {rows.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-500 dark:text-slate-400">{p.name}</span>
          <span className="num ml-auto pl-3 font-medium text-slate-900 dark:text-slate-100">
            {fmtNum(p.dataKey === "__delta" ? Number(p.payload?.value) : p.value, unit)} {unit === "%" ? "%" : ""}
          </span>
        </div>
      ))}
      <div className="mt-1 text-[10px] text-slate-400">Click for sources</div>
    </div>
  );
}

function useHidden() {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const toggle = (k: string) => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  return { hidden, toggle };
}

function waterfallRows(rows: Row[]) {
  let run = 0;
  return rows.map((r) => {
    const v = Number(r.value);
    if (r.kind === "start" || r.kind === "end") {
      run = v;
      return { ...r, __base: Math.min(0, v), __delta: Math.abs(v), __sign: r.kind as string };
    }
    const base = Math.min(run, run + v);
    run += v;
    return { ...r, __base: base, __delta: Math.abs(v), __sign: v >= 0 ? "up" : "down" };
  });
}

function TreeCell(props: { x?: number; y?: number; width?: number; height?: number; index?: number; name?: string; value?: number; unit?: string }) {
  const { x = 0, y = 0, width = 0, height = 0, index = 0, name, value, unit } = props;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={slot(index)} stroke="var(--viz-surface)" strokeWidth={2} rx={4} />
      {width > 70 && height > 34 && (
        <>
          <text x={x + 8} y={y + 18} fill="#ffffff" fontSize={11} fontWeight={600}>{name}</text>
          <text x={x + 8} y={y + 32} fill="#ffffff" fontSize={11}>{fmtNum(value, unit)}</text>
        </>
      )}
    </g>
  );
}

export function ChartView({ chart, selectedX, onSelect }: Omit<Props, "onAsk">) {
  const { hidden, toggle } = useHidden();
  const [stacked, setStacked] = useState(chart.type === "stacked_bar");
  const c = chart;
  const isTime = c.rows.every((r) => /^FY\d{4}$/.test(String(r.x)));
  const fade = (x: string) => (selectedX && isTime && selectedX !== x ? 0.35 : 1);
  const click = (st: { activeLabel?: string | number } | null) => { if (st?.activeLabel !== undefined) onSelect(c, String(st.activeLabel)); };
  const legend = c.series.length >= 2 ? (
    <Legend wrapperStyle={{ fontSize: 12, cursor: "pointer", color: "var(--viz-ink-2)" }} onClick={(e) => e.dataKey && toggle(String(e.dataKey))}
      itemSorter={(it) => c.series.findIndex((s) => s.key === String(it.dataKey))}
      formatter={(v, e) => <span style={{ color: "var(--viz-ink-2)", opacity: hidden.has(String(e.dataKey)) ? 0.4 : 1 }}>{v}</span>} />
  ) : null;
  const yTick = (v: number) => (c.unit === "%" ? `${v}%` : c.unit === "times" ? `${v}×` : compact(v, c.unit));
  const tip = <Tooltip cursor={{ fill: "var(--viz-grid)", opacity: 0.5 }} content={<TooltipBox unit={c.unit} />} />;

  if (c.type === "heatmap") {
    const cols = c.series.map((s) => s.key);
    const max = Math.max(1, ...c.rows.flatMap((r) => cols.map((k) => Math.abs(Number(r[k] ?? 0)))));
    return (
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-[2px] text-xs">
          <thead><tr><th className="text-left font-medium text-slate-500">Metric</th>{cols.map((k) => <th key={k} className="px-2 py-1 font-medium text-slate-500">{k}</th>)}</tr></thead>
          <tbody>{c.rows.map((r) => (
            <tr key={r.x}><td className="pr-2 text-slate-600 dark:text-slate-300">{r.x}</td>
              {cols.map((k) => {
                const v = r[k];
                return (
                  <td key={k} title="Click for sources" onClick={() => v !== undefined && onSelect(c, `${r.x}|${k}`)}
                    className="num h-11 cursor-pointer rounded px-2 text-center font-semibold" style={{ background: v === undefined ? "transparent" : divergingFill(Number(v), max), color: "var(--viz-ink)" }}>
                    {v === undefined ? <span className="font-normal text-slate-400">n/a</span> : `${Number(v) > 0 ? "+" : ""}${fmtNum(Number(v))}%`}
                  </td>);
              })}
            </tr>))}
          </tbody>
        </table>
        <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500"><span className="h-2 w-6 rounded" style={{ background: "var(--viz-neg)" }} /> decline
          <span className="h-2 w-6 rounded" style={{ background: "var(--viz-mid)" }} /> ~0
          <span className="h-2 w-6 rounded" style={{ background: "var(--viz-pos)" }} /> growth · n/a = not computed (inputs missing or not verified)</div>
      </div>
    );
  }
  if (c.type === "pie" || c.type === "donut") {
    const total = c.rows.reduce((a, r) => a + Number(r.value), 0);
    return (
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie data={c.rows} dataKey="value" nameKey="x" innerRadius={c.type === "donut" ? 62 : 0} outerRadius={95} paddingAngle={c.type === "donut" ? 2 : 0}
            stroke="var(--viz-surface)" strokeWidth={2} onClick={(_d: unknown, i: number) => onSelect(c, String(c.rows[i].x))} cursor="pointer"
            label={({ name, value }: { name?: string; value?: number }) => `${name}: ${Math.round((Number(value) / total) * 100)}%`} labelLine={false}>
            {c.rows.map((r, i) => <Cell key={r.x} fill={slot(i)} />)}
          </Pie>
          <Tooltip content={<TooltipBox unit={c.unit} />} />
          <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => <span style={{ color: "var(--viz-ink-2)" }}>{v}</span>} />
        </PieChart>
      </ResponsiveContainer>
    );
  }
  if (c.type === "treemap") {
    return (
      <ResponsiveContainer width="100%" height={260}>
        <Treemap data={c.rows.map((r) => ({ name: r.x, value: Number(r.value) }))} dataKey="value" nameKey="name" isAnimationActive={false}
          content={<TreeCell unit={c.unit} />} onClick={(n: { name?: string }) => n?.name && onSelect(c, n.name)}>
          <Tooltip content={<TooltipBox unit={c.unit} />} />
        </Treemap>
      </ResponsiveContainer>
    );
  }
  if (c.type === "waterfall") {
    const rows = waterfallRows(c.rows);
    return (
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={rows} onClick={click} margin={{ left: 8, right: 8, top: 8 }}>
          {GRID}<XAxis dataKey="x" {...AXIS} interval={0} fontSize={10} /><YAxis {...AXIS} tickFormatter={yTick} width={70} />
          {tip}<ReferenceLine y={0} stroke="var(--viz-axis)" />
          <Bar dataKey="__base" stackId="w" fill="transparent" isAnimationActive={false} />
          <Bar dataKey="__delta" stackId="w" name="Amount" radius={[4, 4, 4, 4]} cursor="pointer">
            {rows.map((r) => <Cell key={r.x} fill={r.__sign === "up" ? "var(--series-3)" : r.__sign === "down" ? "var(--series-8)" : "var(--series-1)"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }
  if (c.type === "line" || c.type === "area") {
    const Chart = c.type === "line" ? LineChart : AreaChart;
    return (
      <ResponsiveContainer width="100%" height={260}>
        <Chart data={c.rows} onClick={click} margin={{ left: 8, right: 16, top: 8 }}>
          {GRID}<XAxis dataKey="x" {...AXIS} /><YAxis {...AXIS} tickFormatter={yTick} width={70} />
          <Tooltip content={<TooltipBox unit={c.unit} />} cursor={{ stroke: "var(--viz-axis)" }} />{legend}
          {selectedX && isTime && <ReferenceLine x={selectedX} stroke="var(--viz-muted)" strokeDasharray="4 3" />}
          {c.series.map((s, i) => c.type === "line"
            ? <Line key={s.key} dataKey={s.key} name={s.label} hide={hidden.has(s.key)} stroke={slot(i)} strokeWidth={2} connectNulls
                dot={{ r: 4, fill: slot(i), stroke: "var(--viz-surface)", strokeWidth: 2 }} activeDot={{ r: 6 }} />
            : <Area key={s.key} dataKey={s.key} name={s.label} hide={hidden.has(s.key)} stroke={slot(i)} strokeWidth={2} fill={slot(i)} fillOpacity={0.15} connectNulls />)}
        </Chart>
      </ResponsiveContainer>
    );
  }
  // bar / grouped_bar / stacked_bar
  const canStack = c.series.length >= 2 && c.series.every((s) => c.rows.every((r) => r[s.key] === undefined || Number(r[s.key]) >= 0));
  return (
    <div>
      {canStack && c.type !== "bar" && (
        <div className="mb-1 flex justify-end gap-1 text-[11px]">
          {["grouped", "stacked"].map((m) => (
            <button key={m} onClick={() => setStacked(m === "stacked")}
              className={`rounded px-2 py-0.5 ${stacked === (m === "stacked") ? "bg-slate-200 font-semibold dark:bg-slate-700" : "text-slate-500"}`}>{m}</button>))}
        </div>
      )}
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={c.rows} onClick={click} margin={{ left: 8, right: 8, top: 8 }} barGap={2}>
          {GRID}<XAxis dataKey="x" {...AXIS} interval={0} /><YAxis {...AXIS} tickFormatter={yTick} width={70} />
          {tip}{legend}<ReferenceLine y={0} stroke="var(--viz-axis)" />
          {c.series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} hide={hidden.has(s.key)} fill={slot(c.type === "bar" && c.series.length === 1 ? 0 : i)}
              stackId={stacked && canStack ? "s" : undefined} radius={stacked ? 0 : [4, 4, 0, 0]} stroke="var(--viz-surface)" strokeWidth={stacked ? 1 : 0}
              maxBarSize={48} cursor="pointer">
              {c.rows.map((r) => <Cell key={r.x} fillOpacity={fade(String(r.x))} />)}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ChartCard({ chart, selectedX, onSelect, onAsk }: Props) {
  const [table, setTable] = useState(false);
  const keys = useMemo(() => chart.series.map((s) => s.key), [chart]);
  const calculated = chart.series.some((s) => s.origin === "calculated");
  return (
    <section className="card flex flex-col overflow-hidden">
      <div className="flex items-start justify-between gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold">{chart.title}</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">{chart.series.length === 1 && chart.series[0].key !== "value" && <span className="font-medium text-slate-700 dark:text-slate-200">{chart.series[0].label} · </span>}{chart.description} · <span className="font-medium">{chart.unit}</span>
            {calculated && <span className="ml-1 rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold text-violet-800 dark:bg-violet-900/40 dark:text-violet-200">calculated</span>}</p>
        </div>
        <div className="no-print flex shrink-0 gap-1">
          <button className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" title="Table view" aria-label="Table view" onClick={() => setTable(!table)}><Table2 className="h-4 w-4" /></button>
          <button className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" title="Download chart data (CSV)" aria-label="Download chart data"
            onClick={() => download(`${chart.title.replace(/[^\w]+/g, "_")}.csv`, toCsv(chart))}><Download className="h-4 w-4" /></button>
          <button className="rounded p-1.5 text-brand-600 hover:bg-brand-50 dark:hover:bg-brand-700/20" title="Ask AI about this chart" aria-label="Ask AI about this chart"
            onClick={() => onAsk(chart)}><MessageSquareText className="h-4 w-4" /></button>
        </div>
      </div>
      <div className="flex-1 p-3">
        {table ? (
          <div className="max-h-64 overflow-auto">
            <table className="table text-xs"><thead><tr><th></th>{chart.series.map((s) => <th key={s.key}>{s.label}</th>)}</tr></thead>
              <tbody>{chart.rows.map((r) => (
                <tr key={r.x} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50" onClick={() => onSelect(chart, r.x)}>
                  <td className="font-medium">{r.x}</td>{keys.map((k) => <td key={k} className="num">{fmtNum(r[k] as number, chart.unit)}</td>)}</tr>))}
              </tbody></table>
          </div>
        ) : <ChartView chart={chart} selectedX={selectedX} onSelect={onSelect} />}
      </div>
    </section>
  );
}

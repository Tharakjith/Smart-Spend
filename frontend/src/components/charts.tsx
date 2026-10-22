import * as React from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chartNum, money } from "@/lib/format";

const ANIMATE = typeof window === "undefined" || !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

const AXIS = { stroke: "var(--chart-axis)", fontSize: 12, tickLine: false, axisLine: false } as const;

function TooltipBox({ title, rows, currency }: { title: string; rows: { label: string; value: string | number; color?: string }[]; currency: string }) {
  return (
    <div className="rounded-md border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium">{title}</p>
      {rows.map((r) => (
        <p key={r.label} className="flex items-center gap-2 tabular">
          {r.color && <span className="inline-block size-2 rounded-full" style={{ background: r.color }} aria-hidden />}
          <span className="text-muted-foreground">{r.label}</span>
          <span className="ml-auto font-medium">{money(String(r.value), currency)}</span>
        </p>
      ))}
    </div>
  );
}

const compact = (v: number) => new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(v);

/** Multi-series line chart over months. Legend + table view so identity is never color-alone. */
export function TrendChart({ data, series, currency, height = 260 }: { data: Record<string, string>[]; series: { key: string; label: string; color: string }[]; currency: string; height?: number }) {
  const rows = data.map((d) => ({ ...d, ...Object.fromEntries(series.map((s) => [s.key, chartNum(d[s.key])])) }));
  return (
    <figure>
      <div style={{ height }} role="img" aria-label={`Line chart of ${series.map((s) => s.label).join(" and ")} by month`}>
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis dataKey="month" {...AXIS} tickFormatter={(m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short" })} />
            <YAxis {...AXIS} width={52} tickFormatter={compact} />
            <Tooltip
              cursor={{ stroke: "var(--chart-axis)", strokeDasharray: "3 3" }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <TooltipBox title={String(label)} currency={currency} rows={series.map((s) => ({ label: s.label, value: (data.find((d) => d.month === label) ?? {})[s.key] ?? "0", color: s.color }))} />
                ) : null
              }
            />
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
            {series.map((s) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }} isAnimationActive={ANIMATE} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TableView
        columns={["Month", ...series.map((s) => s.label)]}
        rows={data.map((d) => [d.month, ...series.map((s) => money(d[s.key], currency))])}
      />
    </figure>
  );
}

/** Vertical single-hue bars (one series): daily spending etc. */
export function ColumnChart({ data, xKey, yKey, label, currency, height = 220, xFormat }: { data: Record<string, string>[]; xKey: string; yKey: string; label: string; currency: string; height?: number; xFormat?: (v: string) => string }) {
  const rows = data.map((d) => ({ ...d, __v: chartNum(d[yKey]) }));
  return (
    <figure>
      <div style={{ height }} role="img" aria-label={`Bar chart of ${label}`}>
        <ResponsiveContainer>
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap={2}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis dataKey={xKey} {...AXIS} tickFormatter={xFormat} interval="preserveStartEnd" minTickGap={16} />
            <YAxis {...AXIS} width={52} tickFormatter={compact} />
            <Tooltip
              cursor={{ fill: "var(--muted)" }}
              content={({ active, payload }) =>
                active && payload?.length ? <TooltipBox title={xFormat ? xFormat(String(payload[0].payload[xKey])) : String(payload[0].payload[xKey])} currency={currency} rows={[{ label, value: payload[0].payload[yKey] }]} /> : null
              }
            />
            <Bar dataKey="__v" name={label} fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={ANIMATE} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView columns={["Date", label]} rows={data.map((d) => [xFormat ? xFormat(d[xKey]) : d[xKey], money(d[yKey], currency)])} />
    </figure>
  );
}

/** Ranked horizontal bars in HTML: magnitude in one hue, values as text (never colored text). */
export function BarList({ items, currency, empty = "No data for this period", max: maxItems = 10 }: { items: { name: string; amount: string; sub?: string }[]; currency: string; empty?: string; max?: number }) {
  const shown = items.slice(0, maxItems);
  const top = Math.max(...shown.map((i) => Math.abs(chartNum(i.amount))), 1);
  if (!shown.length) return <p className="py-6 text-center text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="grid gap-2.5">
      {shown.map((i) => (
        <li key={i.name} className="group grid gap-1" title={`${i.name}: ${money(i.amount, currency)}`}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="truncate">{i.name}</span>
            <span className="shrink-0 font-medium tabular">{money(i.amount, currency)}</span>
          </div>
          <div className="h-2 rounded-full bg-muted">
            <div className="animate-grow h-2 rounded-full bg-[var(--chart-1)] transition-[opacity,width] duration-500 group-hover:opacity-80" style={{ width: `${Math.max(2, (Math.abs(chartNum(i.amount)) / top) * 100)}%` }} />
          </div>
          {i.sub && <span className="text-xs text-muted-foreground">{i.sub}</span>}
        </li>
      ))}
    </ul>
  );
}

export function TableView({ columns, rows }: { columns: string[]; rows: (string | number)[][] }) {
  const [open, setOpen] = React.useState(false);
  return (
    <figcaption className="mt-2">
      <button className="text-xs text-muted-foreground underline-offset-2 hover:underline cursor-pointer" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? "Hide table" : "View as table"}
      </button>
      {open && (
        <div className="mt-2 max-h-64 overflow-auto rounded-md border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted">
              <tr>
                {columns.map((c) => (
                  <th key={c} className="px-2 py-1 text-left font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t">
                  {r.map((v, j) => (
                    <td key={j} className="px-2 py-1 tabular">
                      {v}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figcaption>
  );
}

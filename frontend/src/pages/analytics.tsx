import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Download, FileSpreadsheet, FileText, Search } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { BarList, TableView, TrendChart } from "@/components/charts";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, PageHeader, Select, Skeleton, Table, TBody, TD, TH, THead, TR, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api, ApiError, download, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { chartNum, currentMonth, date, label, money, monthLabel, today } from "@/lib/format";
import { categoryOptions, useCategories } from "@/lib/queries";

const REPORTS = [
  ["transactions", "Transactions (filtered)"],
  ["monthly", "Monthly summary"],
  ["annual", "Annual summary"],
  ["category", "Category report"],
  ["merchant", "Merchant report"],
  ["person", "Person-wise report"],
  ["budget", "Budget performance"],
  ["items", "Item-level purchases"],
  ["loans", "Loans & repayments"],
  ["unmatched", "Unmatched transactions"],
  ["duplicates", "Duplicate detection"],
  ["reconciliation", "Reconciliation summary"],
] as const;

function Overview() {
  const { household } = useAuth();
  const cur = household?.base_currency ?? "INR";
  const [month, setMonth] = React.useState(currentMonth());
  const [level, setLevel] = React.useState("top");
  const trend = useQuery({ queryKey: ["trend12", month], queryFn: () => api<any[]>(`/analytics/trend?months=12&end_month=${month}`) });
  const cats = useQuery({ queryKey: ["cats", month, level], queryFn: () => api<any[]>(`/analytics/categories?month=${month}&level=${level}`) });
  const pm = useQuery({ queryKey: ["pm", month], queryFn: () => api<any[]>(`/analytics/payment-methods?month=${month}`) });
  const fv = useQuery({ queryKey: ["fv", month], queryFn: () => api<any>(`/analytics/fixed-variable?month=${month}`) });
  const top = useQuery({ queryKey: ["top", month], queryFn: () => api<any>(`/analytics/merchants?month=${month}&limit=10`) });
  const bva = useQuery({ queryKey: ["bva"], queryFn: () => api<any[]>(`/analytics/budget-vs-actual`) });
  const fixedTotal = fv.data ? chartNum(fv.data.fixed) + chartNum(fv.data.variable) : 0;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Month" htmlFor="a-month">
          <Input id="a-month" type="month" value={month} max={currentMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} className="w-44" />
        </Field>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Income vs net spending — 12 months to {monthLabel(month)}</CardTitle>
          <CardDescription>Gross purchases minus refunds; transfers, loan principal and reimbursements are excluded.</CardDescription>
        </CardHeader>
        <CardContent>
          {trend.data ? (
            <TrendChart
              data={trend.data}
              currency={cur}
              height={300}
              series={[
                { key: "net_spending", label: "Net spending", color: "var(--chart-1)" },
                { key: "income", label: "Income", color: "var(--chart-2)" },
              ]}
            />
          ) : (
            <Skeleton className="h-72" />
          )}
        </CardContent>
      </Card>
      <div className="stagger grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Spending by category</CardTitle>
            <Select aria-label="Category level" className="w-40" value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="top">Main categories</option>
              <option value="leaf">Subcategories</option>
            </Select>
          </CardHeader>
          <CardContent>{cats.data ? <BarList items={cats.data} currency={cur} max={15} /> : <Skeleton className="h-64" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Payment methods</CardTitle>
          </CardHeader>
          <CardContent>{pm.data ? <BarList items={pm.data.map((p) => ({ name: label(p.payment_method), amount: p.amount }))} currency={cur} /> : <Skeleton className="h-40" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Fixed vs variable</CardTitle>
            <CardDescription>Fixed = categories marked fixed (rent, utilities, insurance…) or recurring transactions</CardDescription>
          </CardHeader>
          <CardContent>
            {fv.data ? (
              <div className="grid gap-3">
                <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={`Fixed ${money(fv.data.fixed, cur)}, variable ${money(fv.data.variable, cur)}`}>
                  <div className="h-full bg-[var(--chart-1)]" style={{ width: `${fixedTotal ? (chartNum(fv.data.fixed) / fixedTotal) * 100 : 0}%` }} />
                  <div className="h-full border-l-2 border-card bg-[var(--chart-2)]" style={{ width: `${fixedTotal ? (chartNum(fv.data.variable) / fixedTotal) * 100 : 0}%` }} />
                </div>
                <div className="flex justify-between text-sm">
                  <span className="flex items-center gap-2">
                    <span className="inline-block size-2.5 rounded-full bg-[var(--chart-1)]" aria-hidden /> Fixed <strong className="tabular">{money(fv.data.fixed, cur)}</strong>
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="inline-block size-2.5 rounded-full bg-[var(--chart-2)]" aria-hidden /> Variable <strong className="tabular">{money(fv.data.variable, cur)}</strong>
                  </span>
                </div>
              </div>
            ) : (
              <Skeleton className="h-16" />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Budget vs actual (current period)</CardTitle>
          </CardHeader>
          <CardContent>
            {(bva.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No budgets. <Link className="text-primary hover:underline" to="/budgets">Create one</Link>.
              </p>
            ) : (
              <>
                <ul className="grid gap-3">
                  {bva.data!.map((b) => (
                    <li key={b.budget_id} className="grid gap-1 text-sm">
                      <div className="flex justify-between">
                        <span>{b.name}</span>
                        <span className="tabular text-muted-foreground">
                          {money(b.spent, cur)} / {money(b.amount, cur)}
                        </span>
                      </div>
                      <div className="relative h-2 rounded-full bg-muted">
                        <div className={`h-2 rounded-full ${b.state === "over" ? "bg-destructive" : "bg-[var(--chart-1)]"}`} style={{ width: `${Math.min(100, b.percent_used)}%` }} />
                      </div>
                    </li>
                  ))}
                </ul>
                <TableView columns={["Budget", "Budget amount", "Spent", "Remaining"]} rows={bva.data!.map((b) => [b.name, money(b.amount, cur), money(b.spent, cur), money(b.remaining, cur)])} />
              </>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Top merchants</CardTitle>
          </CardHeader>
          <CardContent>{top.data ? <BarList items={top.data.merchants.map((m: any) => ({ name: m.name, amount: m.amount, sub: `${m.count} purchase(s)` }))} currency={cur} /> : <Skeleton className="h-40" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Top people</CardTitle>
            <CardDescription>All money moved with each person this month</CardDescription>
          </CardHeader>
          <CardContent>{top.data ? <BarList items={top.data.counterparties.map((m: any) => ({ name: m.name, amount: m.amount, sub: `${m.count} transaction(s)` }))} currency={cur} empty="No person-to-person transactions" /> : <Skeleton className="h-40" />}</CardContent>
        </Card>
      </div>
    </div>
  );
}

function Prices() {
  const [q, setQ] = React.useState("");
  const [product, setProduct] = React.useState<string | null>(null);
  const search = useQuery({ queryKey: ["price-search", q], queryFn: () => api<any[]>(`/prices/search?q=${encodeURIComponent(q)}`) });
  const hist = useQuery({ queryKey: ["price-hist", product], queryFn: () => api<any>(`/prices/history?product=${encodeURIComponent(product!)}`), enabled: !!product });
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>Products</CardTitle>
          <CardDescription>From confirmed receipts with line items</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input aria-label="Search products" className="pl-8" placeholder="rice, milk…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <ul className="grid max-h-[60vh] gap-1 overflow-y-auto">
            {(search.data ?? []).length === 0 && <p className="text-sm text-muted-foreground">No products yet. Confirm receipts with line items to build price history.</p>}
            {(search.data ?? []).map((p) => (
              <li key={p.product}>
                <button className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted cursor-pointer ${product === p.product ? "bg-accent" : ""}`} onClick={() => setProduct(p.product)}>
                  <span className="flex-1 truncate">{p.display_name}</span>
                  {p.repeated && <Badge>{p.purchases}×</Badge>}
                </button>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
      <div className="lg:col-span-2">
        {!product ? (
          <Card className="p-8 text-center text-sm text-muted-foreground">Pick a product to see its price history.</Card>
        ) : !hist.data ? (
          <Skeleton className="h-64" />
        ) : (
          <div className="grid gap-4">
            <p className="text-xs text-muted-foreground">{hist.data.note}</p>
            {hist.data.series.map((s: any) => (
              <Card key={s.dimension}>
                <CardHeader>
                  <CardTitle className="text-sm">{s.price_unit ? `Price per ${s.price_unit}` : "Unit not known — listed, not compared"}</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-3">
                  {s.unusual_increases.map((f: any, i: number) => (
                    <p key={i} className="flex items-center gap-2 rounded-md bg-amber-100/60 p-2 text-sm dark:bg-amber-950/40">
                      <AlertTriangle className="size-4 text-warning" aria-hidden /> {f.increase_pct}% increase on {date(f.date)} at {f.merchant}: {money(f.from)} → {money(f.to)}
                    </p>
                  ))}
                  <Table>
                    <THead>
                      <tr>
                        <TH>Date</TH>
                        <TH>Merchant</TH>
                        <TH>Item</TH>
                        <TH className="text-right">Qty</TH>
                        <TH className="text-right">Paid</TH>
                        <TH className="text-right">Unit price</TH>
                        <TH>Source</TH>
                      </tr>
                    </THead>
                    <TBody>
                      {s.observations.map((o: any, i: number) => (
                        <TR key={i}>
                          <TD>{date(o.date)}</TD>
                          <TD>{o.merchant}</TD>
                          <TD>{o.item_name}</TD>
                          <TD className="text-right tabular">{o.quantity ? `${Number(o.quantity)} ${o.unit ?? ""}` : "—"}</TD>
                          <TD className="text-right tabular">{money(o.line_total, o.currency)}</TD>
                          <TD className="text-right tabular">{o.unit_price ? `${money(o.unit_price, o.currency)}${o.price_unit ? `/${o.price_unit}` : ""}` : "—"}</TD>
                          <TD>
                            {o.document_id ? (
                              <Link className="text-xs text-primary hover:underline" to={`/upload?doc=${o.document_id}`}>
                                Receipt
                              </Link>
                            ) : (
                              <Link className="text-xs text-primary hover:underline" to={`/transactions?open=${o.transaction_id}`}>
                                Transaction
                              </Link>
                            )}
                          </TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                  {s.merchant_comparison.length > 1 && (
                    <div className="text-sm">
                      <p className="font-medium">Merchant comparison</p>
                      {s.merchant_comparison.map((m: any) => (
                        <p key={m.merchant} className="text-muted-foreground">
                          {m.merchant}: latest {money(m.latest_unit_price)}, lowest {money(m.lowest_unit_price)} ({m.observations} purchase(s))
                        </p>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Reports() {
  const cats = useCategories();
  const first = `${today().slice(0, 7)}-01`;
  const [f, setF] = React.useState({ kind: "monthly", date_from: `${today().slice(0, 4)}-01-01`, date_to: today(), category_id: "", q: "" });
  const [busy, setBusy] = React.useState("");
  const params = { date_from: f.date_from, date_to: f.date_to, category_id: f.kind === "transactions" ? f.category_id : "", q: ["transactions", "items"].includes(f.kind) ? f.q : "" };
  const preview = useQuery({ queryKey: ["report", f], queryFn: () => api<any>(`/reports/${f.kind}${qs(params)}`) });
  const exp = async (format: string) => {
    setBusy(format);
    try {
      await download(`/reports/${f.kind}${qs({ ...params, format })}`, `smartspend-${f.kind}.${format}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Export failed");
    } finally {
      setBusy("");
    }
  };
  const r = preview.data;
  return (
    <div className="grid gap-4">
      <Card className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Report" htmlFor="rep-k">
          <Select id="rep-k" value={f.kind} onChange={(e) => setF((x) => ({ ...x, kind: e.target.value }))}>
            {REPORTS.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="From" htmlFor="rep-f">
          <Input id="rep-f" type="date" value={f.date_from} onChange={(e) => setF((x) => ({ ...x, date_from: e.target.value || first }))} />
        </Field>
        <Field label="To" htmlFor="rep-t">
          <Input id="rep-t" type="date" value={f.date_to} onChange={(e) => setF((x) => ({ ...x, date_to: e.target.value || today() }))} />
        </Field>
        {f.kind === "transactions" && (
          <Field label="Category" htmlFor="rep-c">
            <Select id="rep-c" value={f.category_id} onChange={(e) => setF((x) => ({ ...x, category_id: e.target.value }))}>
              <option value="">All</option>
              {categoryOptions(cats.data).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {["transactions", "items"].includes(f.kind) && (
          <Field label="Search" htmlFor="rep-q">
            <Input id="rep-q" value={f.q} onChange={(e) => setF((x) => ({ ...x, q: e.target.value }))} />
          </Field>
        )}
        <div className="flex flex-wrap items-end gap-2 sm:col-span-2 lg:col-span-5">
          <Button variant="outline" loading={busy === "csv"} onClick={() => exp("csv")}>
            <Download /> CSV
          </Button>
          <Button variant="outline" loading={busy === "xlsx"} onClick={() => exp("xlsx")}>
            <FileSpreadsheet /> Excel
          </Button>
          <Button variant="outline" loading={busy === "pdf"} onClick={() => exp("pdf")}>
            <FileText /> PDF
          </Button>
        </div>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{r?.meta.title ?? "Report"}</CardTitle>
          {r && (
            <CardDescription>
              {date(r.meta.date_from)} – {date(r.meta.date_to)} · Currency {r.meta.currency}
              {Object.keys(r.meta.filters).length ? ` · Filters: ${Object.entries(r.meta.filters).map(([k, v]) => `${k}=${v}`).join(", ")}` : " · No filters"}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          {preview.isLoading ? (
            <Skeleton className="h-40" />
          ) : preview.isError ? (
            <p className="text-sm text-destructive">{(preview.error as Error).message}</p>
          ) : (
            r && (
              <div className="max-h-[60vh] overflow-auto">
                <Table>
                  <THead>
                    <tr>
                      {r.columns.map((c: string) => (
                        <TH key={c}>{c}</TH>
                      ))}
                    </tr>
                  </THead>
                  <TBody>
                    {r.rows.slice(0, 500).map((row: string[], i: number) => (
                      <TR key={i}>
                        {row.map((c, j) => (
                          <TD key={j} className="tabular">
                            {c}
                          </TD>
                        ))}
                      </TR>
                    ))}
                    {r.totals && (
                      <TR className="font-semibold">
                        {r.totals.map((c: string, j: number) => (
                          <TD key={j} className="tabular">
                            {c}
                          </TD>
                        ))}
                      </TR>
                    )}
                  </TBody>
                </Table>
                {r.rows.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">No data for this period.</p>}
                {r.rows.length > 500 && <p className="p-2 text-xs text-muted-foreground">Showing 500 of {r.rows.length} rows — export for the full report.</p>}
              </div>
            )
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function AnalyticsPage() {
  return (
    <>
      <PageHeader title="Analytics & Reports" description="Trends, breakdowns, item prices and exportable reports — all from reconciled, canonical records." />
      <Tabs defaultValue="overview">
        <TabsList className="mb-4">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="prices">Item prices</TabsTrigger>
          <TabsTrigger value="reports">Reports & export</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <Overview />
        </TabsContent>
        <TabsContent value="prices">
          <Prices />
        </TabsContent>
        <TabsContent value="reports">
          <Reports />
        </TabsContent>
      </Tabs>
    </>
  );
}

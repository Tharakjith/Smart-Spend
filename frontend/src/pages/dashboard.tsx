import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronLeft, ChevronRight, CreditCard, FileWarning, GitCompareArrows, Plus } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { BarList, ColumnChart, TrendChart } from "@/components/charts";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, ErrorState, PageHeader, Progress, Skeleton, Stat } from "@/components/ui/primitives";
import { TransactionDialog } from "@/pages/transactions";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { currentMonth, date, money, monthLabel, shiftMonth } from "@/lib/format";

export function DashboardPage() {
  const { household, canWrite } = useAuth();
  const cur = household?.base_currency ?? "INR";
  const [month, setMonth] = React.useState(currentMonth());
  const [adding, setAdding] = React.useState(false);
  const summary = useQuery({ queryKey: ["dashboard", month], queryFn: () => api(`/dashboard/summary?month=${month}`) });
  const trend = useQuery({ queryKey: ["trend", month], queryFn: () => api(`/analytics/trend?months=6&end_month=${month}`) });
  const cats = useQuery({ queryKey: ["cat-breakdown", month], queryFn: () => api(`/analytics/categories?month=${month}`) });
  const daily = useQuery({ queryKey: ["daily", month], queryFn: () => api(`/analytics/daily?month=${month}`) });
  const merchants = useQuery({ queryKey: ["merchants-top", month], queryFn: () => api(`/analytics/merchants?month=${month}&limit=6`) });

  const s = summary.data;
  const t = s?.totals;
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Totals come from the reconciled ledger: a receipt and its matching payment count once."
        actions={
          <>
            <div className="flex items-center gap-1 rounded-md border bg-card p-0.5">
              <Button variant="ghost" size="icon" onClick={() => setMonth((m) => shiftMonth(m, -1))} aria-label="Previous month">
                <ChevronLeft />
              </Button>
              <span className="min-w-36 text-center text-sm font-medium">{monthLabel(month)}</span>
              <Button variant="ghost" size="icon" onClick={() => setMonth((m) => shiftMonth(m, 1))} aria-label="Next month" disabled={month >= currentMonth()}>
                <ChevronRight />
              </Button>
            </div>
            {canWrite && (
              <Button onClick={() => setAdding(true)}>
                <Plus /> Add transaction
              </Button>
            )}
          </>
        }
      />
      {summary.isError && <ErrorState error={summary.error} onRetry={() => summary.refetch()} />}

      {s?.credit_cards?.next_bill && (
        <Link
          to="/credit-cards"
          className={`mb-4 flex items-center gap-3 rounded-lg border p-3 text-sm ${s.credit_cards.next_bill.status === "overdue" ? "border-destructive/50 bg-destructive/5" : ""}`}
        >
          <CreditCard className={`size-5 ${s.credit_cards.next_bill.status === "overdue" ? "text-destructive" : "text-muted-foreground"}`} aria-hidden />
          <span>
            <strong>{s.credit_cards.next_bill.name}</strong> bill {s.credit_cards.next_bill.status === "overdue" ? "is overdue" : `due ${date(s.credit_cards.next_bill.due_date)}`}:{" "}
            {money(s.credit_cards.next_bill.remaining_amount, cur)} remaining (minimum {money(s.credit_cards.next_bill.minimum_remaining, cur)}). Total card dues {money(s.credit_cards.total_outstanding, cur)}.
          </span>
        </Link>
      )}
      {(s?.duplicate_alerts > 0 || s?.pending_document_reviews > 0 || s?.failed_documents > 0) && (
        <div className="mb-4 grid gap-2 sm:grid-cols-2">
          {s.duplicate_alerts > 0 && (
            <Link to="/reconciliation" className="flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/40">
              <GitCompareArrows className="size-5 text-warning" aria-hidden />
              <span>
                <strong>{s.duplicate_alerts}</strong> possible duplicate or matching record{s.duplicate_alerts === 1 ? "" : "s"} need review
              </span>
            </Link>
          )}
          {(s.pending_document_reviews > 0 || s.failed_documents > 0) && (
            <Link to="/upload" className="flex items-center gap-3 rounded-lg border p-3 text-sm">
              <FileWarning className="size-5 text-muted-foreground" aria-hidden />
              <span>
                {s.pending_document_reviews > 0 && <><strong>{s.pending_document_reviews}</strong> document(s) awaiting review. </>}
                {s.failed_documents > 0 && <><strong>{s.failed_documents}</strong> failed to process.</>}
              </span>
            </Link>
          )}
        </div>
      )}

      <section aria-label="Key figures" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!t ? (
          Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-24" />)
        ) : (
          <>
            <Stat
              label="Net spending"
              value={money(t.net_spending, cur)}
              sub={
                s.month_over_month_net_spending_pct === null ? (
                  "No spending last month to compare"
                ) : (
                  <span>
                    {s.month_over_month_net_spending_pct > 0 ? "▲" : "▼"} {Math.abs(s.month_over_month_net_spending_pct)}% vs last month
                  </span>
                )
              }
            />
            <Stat label="Income" value={money(t.income, cur)} />
            <Stat label="Net cash flow" value={money(t.net_cash_flow, cur)} tone={Number(t.net_cash_flow) < 0 ? "negative" : "positive"} sub="Money in minus money out" />
            <Stat
              label="Remaining budget"
              value={s.remaining_budget === null ? "—" : money(s.remaining_budget, cur)}
              sub={s.remaining_budget === null ? <Link className="text-primary hover:underline" to="/budgets">Set a monthly budget</Link> : `of ${money(s.overall_budget.amount, cur)}`}
              tone={s.remaining_budget !== null && Number(s.remaining_budget) < 0 ? "negative" : undefined}
            />
            <Stat label="Gross purchases" value={money(t.gross_spending, cur)} sub={`Refunds −${money(t.refunds, cur)}`} />
            <Stat label="Estimated savings" value={money(t.estimated_savings, cur)} sub="Income minus your share of spending" />
            <Stat label="Owed to you" value={money(s.owed_to_you, cur)} sub={`Loans ${money(s.outstanding_loans.receivable, cur)} · Shared ${money(s.unsettled_shared_expenses.receivable, cur)}`} />
            <Stat label="You owe" value={money(s.you_owe, cur)} sub={`Loans ${money(s.outstanding_loans.payable, cur)} · Shared ${money(s.unsettled_shared_expenses.payable, cur)}`} />
          </>
        )}
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Spending and income, last 6 months</CardTitle>
            <CardDescription>Net spending is purchases minus refunds; transfers and loan principal are excluded.</CardDescription>
          </CardHeader>
          <CardContent>
            {trend.data ? (
              <TrendChart
                data={trend.data}
                currency={cur}
                series={[
                  { key: "net_spending", label: "Net spending", color: "var(--chart-1)" },
                  { key: "income", label: "Income", color: "var(--chart-2)" },
                ]}
              />
            ) : (
              <Skeleton className="h-64" />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>By category</CardTitle>
            <CardDescription>{monthLabel(month)}, net of refunds</CardDescription>
          </CardHeader>
          <CardContent>{cats.data ? <BarList items={cats.data} currency={cur} max={8} /> : <Skeleton className="h-64" />}</CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Daily spending</CardTitle>
          </CardHeader>
          <CardContent>
            {daily.data ? <ColumnChart data={daily.data} xKey="date" yKey="net_spending" label="Net spending" currency={cur} xFormat={(d) => String(Number(d.slice(8)))} /> : <Skeleton className="h-56" />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Top merchants</CardTitle>
          </CardHeader>
          <CardContent>{merchants.data ? <BarList items={merchants.data.merchants.map((m: any) => ({ name: m.name, amount: m.amount, sub: `${m.count} transaction(s)` }))} currency={cur} max={6} /> : <Skeleton className="h-56" />}</CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Budgets</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {!s ? (
              <Skeleton className="h-24" />
            ) : s.budgets.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No budgets yet. <Link className="text-primary hover:underline" to="/budgets">Create one</Link>.
              </p>
            ) : (
              s.budgets.slice(0, 5).map((b: any) => (
                <div key={b.budget_id} className="grid gap-1">
                  <div className="flex justify-between text-sm">
                    <span className="flex items-center gap-1.5">
                      {b.state !== "ok" && <AlertTriangle className="size-3.5 text-warning" aria-label={b.state === "over" ? "Over budget" : "Near limit"} />}
                      {b.name}
                    </span>
                    <span className="tabular text-muted-foreground">
                      {money(b.spent, cur)} / {money(b.amount, cur)}
                    </span>
                  </div>
                  <Progress value={b.percent_used} tone={b.state === "over" ? "danger" : b.state === "warning" ? "warning" : "primary"} />
                </div>
              ))
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Upcoming recurring</CardTitle>
            <CardDescription>Predictions — not counted until paid</CardDescription>
          </CardHeader>
          <CardContent>
            {!s ? (
              <Skeleton className="h-24" />
            ) : s.upcoming_recurring.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing due in the next 14 days.</p>
            ) : (
              <ul className="divide-y text-sm">
                {s.upcoming_recurring.map((r: any) => (
                  <li key={r.id} className="flex justify-between py-2">
                    <span>
                      {r.name} <span className="text-muted-foreground">· {date(r.next_due_date)}</span>
                    </span>
                    <span className="tabular">{money(r.amount, r.currency)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Reconciliation</CardTitle>
            <CardDescription>Bills and payments linked so nothing is double counted</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            {!s ? (
              <Skeleton className="h-24" />
            ) : (
              <>
                <div className="flex justify-between">
                  <span>Completion</span>
                  <span className="font-medium tabular">{Math.round(s.reconciliation_completion_rate * 100)}%</span>
                </div>
                <Progress value={s.reconciliation_completion_rate * 100} />
                <div className="flex justify-between">
                  <span>Needs review</span>
                  <Badge tone={s.duplicate_alerts ? "warning" : "success"}>{s.duplicate_alerts}</Badge>
                </div>
                <div className="flex justify-between">
                  <span>Cash movements excluded from spending</span>
                  <span className="tabular">{money(t.internal_transfers, cur)}</span>
                </div>
                {s.other_currencies.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    Also spent (not converted): {s.other_currencies.map((o: any) => money(o.gross_spending, o.currency)).join(", ")}
                  </p>
                )}
                <Button variant="outline" size="sm" asChild>
                  <Link to="/reconciliation">Open review queue</Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
      <TransactionDialog open={adding} onOpenChange={setAdding} />
    </>
  );
}

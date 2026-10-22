import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronLeft, ChevronRight, CreditCard, FileSpreadsheet, FileUp, FileWarning, GitCompareArrows, PencilLine, Plus, X } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { BarList, ColumnChart, TrendChart } from "@/components/charts";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, ErrorState, PageHeader, Progress, Skeleton, Stat } from "@/components/ui/primitives";
import { AddTransactionDialog } from "@/components/add-transaction";
import { CountUp } from "@/components/count-up";
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
  // Any transaction at all, in any month: decides whether to show the "Get started" card.
  const anyTx = useQuery({ queryKey: ["transactions", "any"], queryFn: () => api<{ total: number }>("/transactions?page_size=1") });

  const s = summary.data;
  const t = s?.totals;
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Your month at a glance. A bill and its matching payment are counted once."
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
      {canWrite && anyTx.data?.total === 0 && <GetStarted onAdd={() => setAdding(true)} />}

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

      <section aria-label="Key figures" className="stagger grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-4">
        {!t ? (
          Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-24" />)
        ) : (
          <>
            <Stat
              label="Net spending"
              value={<CountUp value={t.net_spending} currency={cur} />}
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
            <Stat label="Income" value={<CountUp value={t.income} currency={cur} />} />
            <Stat label="Net cash flow" value={<CountUp value={t.net_cash_flow} currency={cur} />} tone={Number(t.net_cash_flow) < 0 ? "negative" : "positive"} sub="Money in minus money out" />
            <Stat
              label="Remaining budget"
              value={s.remaining_budget === null ? "—" : <CountUp value={s.remaining_budget} currency={cur} />}
              sub={s.remaining_budget === null ? <Link className="text-primary hover:underline" to="/budgets">Set a monthly budget</Link> : `of ${money(s.overall_budget.amount, cur)}`}
              tone={s.remaining_budget !== null && Number(s.remaining_budget) < 0 ? "negative" : undefined}
            />
            <Stat label="Gross purchases" value={<CountUp value={t.gross_spending} currency={cur} />} sub={`Refunds −${money(t.refunds, cur)}`} />
            <Stat label="Estimated savings" value={<CountUp value={t.estimated_savings} currency={cur} />} sub="Income minus your share of spending" />
            <Stat label="Owed to you" value={<CountUp value={s.owed_to_you} currency={cur} />} sub={`Loans ${money(s.outstanding_loans.receivable, cur)} · Shared ${money(s.unsettled_shared_expenses.receivable, cur)}`} />
            <Stat label="You owe" value={<CountUp value={s.you_owe} currency={cur} />} sub={`Loans ${money(s.outstanding_loans.payable, cur)} · Shared ${money(s.unsettled_shared_expenses.payable, cur)}`} />
          </>
        )}
      </section>

      <div className="stagger mt-4 grid gap-4 lg:grid-cols-3">
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

      <div className="stagger mt-4 grid gap-4 lg:grid-cols-3">
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

      <div className="stagger mt-4 grid gap-4 lg:grid-cols-3">
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
      <AddTransactionDialog open={adding} onOpenChange={setAdding} />
    </>
  );
}

function GetStarted({ onAdd }: { onAdd: () => void }) {
  const [hidden, setHidden] = React.useState(() => {
    try {
      return localStorage.getItem("ss-get-started-hidden") === "1";
    } catch {
      return false;
    }
  });
  if (hidden) return null;
  const hide = () => {
    try {
      localStorage.setItem("ss-get-started-hidden", "1");
    } catch {
      /* ignore */
    }
    setHidden(true);
  };
  const steps = [
    { icon: FileUp, title: "Upload a bill", text: "Snap a receipt or upload a PDF. We read the amount, date, shop and category for you.", to: "/upload" },
    { icon: PencilLine, title: "Add a payment", text: "Record cash, UPI or card spending that has no bill.", onClick: onAdd },
    { icon: FileSpreadsheet, title: "Import a statement", text: "Bring in a bank or card statement (CSV, Excel or PDF). Duplicates are skipped.", to: "/upload?tab=statements" },
  ];
  return (
    <Card className="relative mb-4 overflow-hidden border-primary/30 bg-gradient-to-br from-accent/60 to-card">
      <Button variant="ghost" size="icon" className="absolute right-2 top-2" onClick={hide} aria-label="Hide getting started">
        <X />
      </Button>
      <CardHeader>
        <CardTitle>Welcome to SmartSpend</CardTitle>
        <CardDescription>Add your first expense. When a bill and its payment both show up, they're matched so the spend is counted once.</CardDescription>
      </CardHeader>
      <CardContent className="stagger grid gap-3 sm:grid-cols-3">
        {steps.map((st) => {
          const body = (
            <>
              <span className="inline-flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                <st.icon className="size-5" aria-hidden />
              </span>
              <span className="font-medium">{st.title}</span>
              <span className="text-xs text-muted-foreground">{st.text}</span>
            </>
          );
          const cls = "lift flex flex-col items-start gap-1.5 rounded-lg border bg-card p-4 text-left hover:border-primary/60";
          return st.to ? (
            <Link key={st.title} to={st.to} className={cls}>
              {body}
            </Link>
          ) : (
            <button key={st.title} type="button" onClick={st.onClick} className={cls + " cursor-pointer"}>
              {body}
            </button>
          );
        })}
      </CardContent>
    </Card>
  );
}

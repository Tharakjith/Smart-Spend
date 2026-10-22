import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, Check, Pause, Play, Plus, Sparkles, Target, Trash2 } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Field, Input, PageHeader, Progress, Select, Skeleton } from "@/components/ui/primitives";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, label, money, today } from "@/lib/format";
import { categoryOptions, type Page, type Transaction, useCategories } from "@/lib/queries";

const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong");

function BudgetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const cats = useCategories();
  const [f, setF] = React.useState({ name: "", period: "monthly", category_id: "", amount: "", alert_threshold_pct: "80" });
  const save = useMutation({
    mutationFn: () => api("/budgets", { body: { ...f, category_id: f.category_id || null, alert_threshold_pct: Number(f.alert_threshold_pct) } }),
    onSuccess: () => {
      qc.invalidateQueries();
      onOpenChange(false);
      setF({ name: "", period: "monthly", category_id: "", amount: "", alert_threshold_pct: "80" });
      toast.success("Budget created");
    },
    onError: err,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="New budget" description="Leave the category empty for an overall budget. Spending is net of refunds, from the reconciled ledger.">
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Name" htmlFor="b-n">
            <Input id="b-n" required value={f.name} onChange={set("name")} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Period" htmlFor="b-p">
              <Select id="b-p" value={f.period} onChange={set("period")}>
                <option value="monthly">Monthly</option>
                <option value="weekly">Weekly</option>
              </Select>
            </Field>
            <Field label="Amount" htmlFor="b-a">
              <Input id="b-a" required inputMode="decimal" value={f.amount} onChange={set("amount")} />
            </Field>
          </div>
          <Field label="Category" htmlFor="b-c">
            <Select id="b-c" value={f.category_id} onChange={set("category_id")}>
              <option value="">All spending</option>
              {categoryOptions(cats.data, "expense").map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Alert at % used" htmlFor="b-t">
            <Input id="b-t" inputMode="numeric" value={f.alert_threshold_pct} onChange={set("alert_threshold_pct")} />
          </Field>
          <Button type="submit" loading={save.isPending}>
            Create budget
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function GoalDialog({ open, onOpenChange, goal }: { open: boolean; onOpenChange: (o: boolean) => void; goal?: any }) {
  const qc = useQueryClient();
  const [f, setF] = React.useState({ name: "", target_amount: "", saved_amount: "0", target_date: "" });
  React.useEffect(() => {
    setF(goal ? { name: goal.name, target_amount: String(Number(goal.target_amount)), saved_amount: String(Number(goal.saved_amount)), target_date: goal.target_date ?? "" } : { name: "", target_amount: "", saved_amount: "0", target_date: "" });
  }, [goal, open]);
  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, target_date: f.target_date || null };
      return goal ? api(`/savings-goals/${goal.id}`, { method: "PUT", body }) : api("/savings-goals", { body });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["goals"] });
      onOpenChange(false);
    },
    onError: err,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={goal ? "Update savings goal" : "New savings goal"}>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Name" htmlFor="g-n">
            <Input id="g-n" required value={f.name} onChange={set("name")} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Target" htmlFor="g-t">
              <Input id="g-t" required inputMode="decimal" value={f.target_amount} onChange={set("target_amount")} />
            </Field>
            <Field label="Saved so far" htmlFor="g-s">
              <Input id="g-s" inputMode="decimal" value={f.saved_amount} onChange={set("saved_amount")} />
            </Field>
          </div>
          <Field label="Target date" htmlFor="g-d">
            <Input id="g-d" type="date" value={f.target_date} onChange={set("target_date")} />
          </Field>
          <Button type="submit" loading={save.isPending}>
            Save
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function BudgetsPage() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [goalDlg, setGoalDlg] = React.useState<{ open: boolean; goal?: any }>({ open: false });
  const status = useQuery({ queryKey: ["budget-status"], queryFn: () => api<any[]>("/budgets/status") });
  const goals = useQuery({ queryKey: ["goals"], queryFn: () => api<any[]>("/savings-goals") });
  const del = useMutation({ mutationFn: (id: string) => api(`/budgets/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries(), onError: err });
  return (
    <>
      <PageHeader
        title="Budgets"
        description="Track spending against limits. Alerts fire at your threshold; refunds reduce what counts."
        actions={
          canWrite && (
            <>
              <Button variant="outline" onClick={() => setGoalDlg({ open: true })}>
                <Target /> New goal
              </Button>
              <Button onClick={() => setOpen(true)}>
                <Plus /> New budget
              </Button>
            </>
          )
        }
      />
      {status.isLoading ? (
        <Skeleton className="h-40" />
      ) : (status.data ?? []).length === 0 ? (
        <EmptyState title="No budgets yet" description="Create an overall monthly budget or one per category." action={canWrite && <Button onClick={() => setOpen(true)}>New budget</Button>} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {status.data!.map((b) => (
            <Card key={b.budget_id} className="p-4">
              <div className="flex items-start gap-2">
                <div className="flex-1">
                  <p className="font-medium">{b.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {b.category_name ?? "All spending"} · {b.period} · {date(b.period_start)} – {date(new Date(new Date(b.period_end_exclusive).getTime() - 86400000).toISOString().slice(0, 10))}
                  </p>
                </div>
                {b.state !== "ok" && (
                  <Badge tone={b.state === "over" ? "danger" : "warning"}>
                    <AlertTriangle className="size-3" /> {b.state === "over" ? "Over" : "Near limit"}
                  </Badge>
                )}
              </div>
              <p className="mt-3 text-xl font-semibold tabular">
                {money(b.spent, b.currency)} <span className="text-sm font-normal text-muted-foreground">of {money(b.amount, b.currency)}</span>
              </p>
              <Progress className="mt-2" value={b.percent_used} tone={b.state === "over" ? "danger" : b.state === "warning" ? "warning" : "primary"} />
              <p className="mt-1 text-xs text-muted-foreground">
                {b.percent_used}% used · {Number(b.remaining) >= 0 ? `${money(b.remaining, b.currency)} left` : `${money(String(b.remaining).replace("-", ""), b.currency)} over`}
              </p>
              {canWrite && (
                <Button variant="ghost" size="sm" className="mt-2" onClick={() => del.mutate(b.budget_id)}>
                  <Trash2 /> Delete
                </Button>
              )}
            </Card>
          ))}
        </div>
      )}
      <h2 className="mb-3 mt-8 text-lg font-semibold">Savings goals</h2>
      {(goals.data ?? []).length === 0 ? (
        <EmptyState title="No savings goals" description="Set a target and track progress toward it." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {goals.data!.map((g) => (
            <Card key={g.id} className="p-4">
              <div className="flex items-center gap-2">
                <p className="flex-1 font-medium">{g.name}</p>
                <Badge tone={g.status === "achieved" ? "success" : "default"}>{g.status}</Badge>
              </div>
              <p className="mt-2 text-xl font-semibold tabular">
                {money(g.saved_amount, g.currency)} <span className="text-sm font-normal text-muted-foreground">of {money(g.target_amount, g.currency)}</span>
              </p>
              <Progress className="mt-2" value={g.percent} />
              <p className="mt-1 text-xs text-muted-foreground">
                {g.target_date ? `By ${date(g.target_date)}` : "No target date"}
                {g.monthly_needed ? ` · save ${money(g.monthly_needed, g.currency)}/month` : ""}
              </p>
              {canWrite && (
                <Button variant="ghost" size="sm" className="mt-2" onClick={() => setGoalDlg({ open: true, goal: g })}>
                  Update progress
                </Button>
              )}
            </Card>
          ))}
        </div>
      )}
      <BudgetDialog open={open} onOpenChange={setOpen} />
      <GoalDialog open={goalDlg.open} goal={goalDlg.goal} onOpenChange={(o) => setGoalDlg({ open: o })} />
    </>
  );
}

function RecurringDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const cats = useCategories();
  const [f, setF] = React.useState({ name: "", amount: "", frequency: "monthly", next_due_date: today(), category_id: "", is_subscription: false, remind_days_before: "3" });
  const save = useMutation({
    mutationFn: () => api("/recurring", { body: { ...f, category_id: f.category_id || null, remind_days_before: Number(f.remind_days_before) } }),
    onSuccess: () => {
      qc.invalidateQueries();
      onOpenChange(false);
      toast.success("Recurring expense added. It stays a prediction until you mark a real payment.");
    },
    onError: err,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Add recurring expense">
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Name" htmlFor="r-n">
            <Input id="r-n" required value={f.name} onChange={set("name")} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Amount" htmlFor="r-a">
              <Input id="r-a" required inputMode="decimal" value={f.amount} onChange={set("amount")} />
            </Field>
            <Field label="Frequency" htmlFor="r-f">
              <Select id="r-f" value={f.frequency} onChange={set("frequency")}>
                {["weekly", "monthly", "quarterly", "yearly"].map((x) => (
                  <option key={x} value={x}>
                    {label(x)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Next due" htmlFor="r-d">
              <Input id="r-d" type="date" value={f.next_due_date} onChange={set("next_due_date")} />
            </Field>
            <Field label="Remind days before" htmlFor="r-r">
              <Input id="r-r" inputMode="numeric" value={f.remind_days_before} onChange={set("remind_days_before")} />
            </Field>
          </div>
          <Field label="Category" htmlFor="r-c">
            <Select id="r-c" value={f.category_id} onChange={set("category_id")}>
              <option value="">—</option>
              {categoryOptions(cats.data, "expense").map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </Select>
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.is_subscription} onChange={(e) => setF((x) => ({ ...x, is_subscription: e.target.checked }))} /> This is a subscription
          </label>
          <Button type="submit" loading={save.isPending}>
            Add
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MarkPaidDialog({ rec, onClose }: { rec: any; onClose: () => void }) {
  const qc = useQueryClient();
  const txs = useQuery({ queryKey: ["mark-paid", rec?.id], queryFn: () => api<Page<Transaction>>(`/transactions${qs({ q: rec.merchant_name ?? rec.name.split(" ")[0], type: "expense", page_size: 20 })}`), enabled: !!rec });
  const pay = useMutation({
    mutationFn: (txId: string) => api(`/recurring/${rec.id}/mark-paid`, { body: { transaction_id: txId } }),
    onSuccess: () => {
      qc.invalidateQueries();
      onClose();
      toast.success("Linked to the actual payment; next due date advanced");
    },
    onError: err,
  });
  return (
    <Dialog open={!!rec} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`Mark ${rec?.name ?? ""} paid`} description="Pick the real transaction. Predictions never count toward totals on their own.">
        <ul className="grid max-h-80 gap-1 overflow-y-auto">
          {(txs.data?.items ?? []).length === 0 && <p className="text-sm text-muted-foreground">No matching transactions found. Record the payment first.</p>}
          {(txs.data?.items ?? []).map((t) => (
            <li key={t.id}>
              <button className="flex w-full items-center gap-2 rounded-md border p-2 text-left text-sm hover:bg-muted cursor-pointer" onClick={() => pay.mutate(t.id)}>
                <span className="flex-1 truncate">
                  {t.description} · {date(t.occurred_on)}
                </span>
                <span className="tabular">{money(t.amount, t.currency)}</span>
              </button>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

export function RecurringPage() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const [open, setOpen] = React.useState(false);
  const [paying, setPaying] = React.useState<any>(null);
  const recs = useQuery({ queryKey: ["recurring"], queryFn: () => api<any[]>("/recurring") });
  const upcoming = useQuery({ queryKey: ["recurring-upcoming"], queryFn: () => api<any[]>("/recurring/upcoming?days=45") });
  const detect = useMutation({
    mutationFn: () => api("/recurring/detect", { method: "POST" }),
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["recurring"] });
      toast.success(r.suggested.length ? `Found ${r.suggested.length} likely recurring payment(s) to review` : "No new recurring patterns found");
    },
    onError: err,
  });
  const update = useMutation({
    mutationFn: ({ r, patch }: { r: any; patch: any }) =>
      api(`/recurring/${r.id}`, { method: "PUT", body: { name: r.name, amount: r.amount, frequency: r.frequency, next_due_date: r.next_due_date, category_id: r.category_id, merchant_id: r.merchant_id, is_subscription: r.is_subscription, remind_days_before: r.remind_days_before, notes: r.notes, status: r.status, ...patch } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recurring"] }),
    onError: err,
  });
  const del = useMutation({ mutationFn: (id: string) => api(`/recurring/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["recurring"] }), onError: err });
  const list = recs.data ?? [];
  const groups = [
    ["suggested", "Detected — confirm or dismiss"],
    ["active", "Active"],
    ["paused", "Paused"],
  ] as const;
  return (
    <>
      <PageHeader
        title="Recurring Expenses"
        description="Rent, utilities and subscriptions. Upcoming items are predictions until an actual payment is linked."
        actions={
          canWrite && (
            <>
              <Button variant="outline" loading={detect.isPending} onClick={() => detect.mutate()}>
                <Sparkles /> Detect from history
              </Button>
              <Button onClick={() => setOpen(true)}>
                <Plus /> Add
              </Button>
            </>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid content-start gap-4 lg:col-span-2">
          {recs.isLoading ? (
            <Skeleton className="h-40" />
          ) : list.length === 0 ? (
            <EmptyState title="No recurring expenses" description="Add rent or a subscription, or detect patterns from your history." />
          ) : (
            groups.map(([st, title]) => {
              const items = list.filter((r) => r.status === st);
              if (!items.length) return null;
              return (
                <section key={st}>
                  <h2 className="mb-2 text-sm font-semibold text-muted-foreground">{title}</h2>
                  <div className="grid gap-2">
                    {items.map((r) => (
                      <Card key={r.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                        <CalendarClock className="size-4 text-muted-foreground" aria-hidden />
                        <div className="min-w-0 flex-1">
                          <p className="font-medium">
                            {r.name} {r.is_subscription && <Badge tone="info">subscription</Badge>}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {label(r.frequency)} · next {date(r.next_due_date)} · ≈ {money(r.monthly_equivalent, r.currency)}/month
                          </p>
                        </div>
                        <span className="font-semibold tabular">{money(r.amount, r.currency)}</span>
                        {canWrite && (
                          <div className="flex gap-1">
                            {st === "suggested" && (
                              <Button size="sm" onClick={() => update.mutate({ r, patch: { status: "active" } })}>
                                <Check /> Confirm
                              </Button>
                            )}
                            {st === "active" && (
                              <>
                                <Button size="sm" variant="outline" onClick={() => setPaying(r)}>
                                  Mark paid
                                </Button>
                                <Button size="icon" variant="ghost" aria-label="Pause" onClick={() => update.mutate({ r, patch: { status: "paused" } })}>
                                  <Pause />
                                </Button>
                              </>
                            )}
                            {st === "paused" && (
                              <Button size="icon" variant="ghost" aria-label="Resume" onClick={() => update.mutate({ r, patch: { status: "active" } })}>
                                <Play />
                              </Button>
                            )}
                            <Button size="icon" variant="ghost" aria-label={`Delete ${r.name}`} onClick={() => del.mutate(r.id)}>
                              <Trash2 />
                            </Button>
                          </div>
                        )}
                      </Card>
                    ))}
                  </div>
                </section>
              );
            })
          )}
        </div>
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Next 45 days</CardTitle>
            <CardDescription>Predicted — not counted in totals</CardDescription>
          </CardHeader>
          <CardContent>
            {(upcoming.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing scheduled.</p>
            ) : (
              <ul className="divide-y text-sm">
                {upcoming.data!.map((u, i) => (
                  <li key={i} className="flex justify-between py-2">
                    <span>
                      {u.name} <span className="text-muted-foreground">· {date(u.due_date)}</span>
                    </span>
                    <span className="tabular">{money(u.amount, u.currency)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
      <RecurringDialog open={open} onOpenChange={setOpen} />
      <MarkPaidDialog rec={paying} onClose={() => setPaying(null)} />
    </>
  );
}

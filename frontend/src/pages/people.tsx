import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HandCoins, Plus, Split, UserPlus } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, Card, EmptyState, Field, Input, PageHeader, Select, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api, ApiError, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, date, money, today } from "@/lib/format";
import { useCounterparties } from "@/lib/queries";

const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong");

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

function AddPerson({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const inv = useInvalidate();
  const [f, setF] = React.useState({ name: "", phone: "", email: "", upi_id: "", notes: "" });
  const save = useMutation({
    mutationFn: () => api("/counterparties", { body: f }),
    onSuccess: () => {
      inv();
      onOpenChange(false);
      setF({ name: "", phone: "", email: "", upi_id: "", notes: "" });
      toast.success("Person added");
    },
    onError: err,
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Add a person" description="Friends, family, landlords — anyone you pay, lend to or split bills with.">
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          {(["name", "phone", "email", "upi_id", "notes"] as const).map((k) => (
            <Field key={k} label={k === "upi_id" ? "UPI ID" : k[0].toUpperCase() + k.slice(1)} htmlFor={`p-${k}`}>
              <Input id={`p-${k}`} required={k === "name"} value={f[k]} onChange={(e) => setF((x) => ({ ...x, [k]: e.target.value }))} />
            </Field>
          ))}
          <Button type="submit" loading={save.isPending}>
            Add person
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function LoanDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const inv = useInvalidate();
  const { household } = useAuth();
  const people = useCounterparties();
  const [f, setF] = React.useState({ counterparty_id: "", direction: "given", principal: "", start_date: today(), due_date: "", interest_rate_pct: "", notes: "" });
  const save = useMutation({
    mutationFn: () => api("/loans", { body: { ...f, currency: household?.base_currency, due_date: f.due_date || null, interest_rate_pct: f.interest_rate_pct || null } }),
    onSuccess: () => {
      inv();
      onOpenChange(false);
      toast.success("Loan recorded. Principal is a cash movement, not spending.");
    },
    onError: err,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Record a loan">
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <Field label="Person" htmlFor="l-p">
              <Select id="l-p" required value={f.counterparty_id} onChange={set("counterparty_id")}>
                <option value="">Choose…</option>
                {(people.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Direction" htmlFor="l-d">
              <Select id="l-d" value={f.direction} onChange={set("direction")}>
                <option value="given">I lent money</option>
                <option value="received">I borrowed money</option>
              </Select>
            </Field>
            <Field label="Principal" htmlFor="l-a">
              <Input id="l-a" inputMode="decimal" required value={f.principal} onChange={set("principal")} />
            </Field>
            <Field label="Interest % (optional)" htmlFor="l-i">
              <Input id="l-i" inputMode="decimal" value={f.interest_rate_pct} onChange={set("interest_rate_pct")} />
            </Field>
            <Field label="Start date" htmlFor="l-s">
              <Input id="l-s" type="date" value={f.start_date} onChange={set("start_date")} />
            </Field>
            <Field label="Due date" htmlFor="l-due">
              <Input id="l-due" type="date" value={f.due_date} onChange={set("due_date")} />
            </Field>
          </div>
          <Field label="Notes" htmlFor="l-n">
            <Input id="l-n" value={f.notes} onChange={set("notes")} />
          </Field>
          <Button type="submit" loading={save.isPending}>
            Save loan
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RepayDialog({ loan, onClose }: { loan: any; onClose: () => void }) {
  const inv = useInvalidate();
  const [f, setF] = React.useState({ paid_on: today(), principal_amount: "", interest_amount: "" });
  const save = useMutation({
    mutationFn: () => api(`/loans/${loan.id}/repayments`, { body: { ...f, principal_amount: f.principal_amount || "0", interest_amount: f.interest_amount || "0" } }),
    onSuccess: () => {
      inv();
      onClose();
      toast.success("Repayment recorded");
    },
    onError: err,
  });
  return (
    <Dialog open={!!loan} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Record repayment" description={loan ? `Outstanding principal ${money(loan.outstanding, loan.currency)}. Interest is tracked separately and is the only part counted as an expense/income.` : undefined}>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field label="Date" htmlFor="r-d">
            <Input id="r-d" type="date" value={f.paid_on} onChange={(e) => setF((x) => ({ ...x, paid_on: e.target.value }))} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Principal" htmlFor="r-p">
              <Input id="r-p" inputMode="decimal" value={f.principal_amount} onChange={(e) => setF((x) => ({ ...x, principal_amount: e.target.value }))} />
            </Field>
            <Field label="Interest" htmlFor="r-i">
              <Input id="r-i" inputMode="decimal" value={f.interest_amount} onChange={(e) => setF((x) => ({ ...x, interest_amount: e.target.value }))} />
            </Field>
          </div>
          <Button type="submit" loading={save.isPending}>
            Save repayment
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SplitDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const inv = useInvalidate();
  const { household } = useAuth();
  const people = useCounterparties();
  const [f, setF] = React.useState({ description: "", total_amount: "", occurred_on: today(), payer: "", split_method: "equal", merchant_name: "" });
  const [parts, setParts] = React.useState<{ counterparty_id: string | null; share_amount: string; share_percent: string }[]>([{ counterparty_id: null, share_amount: "", share_percent: "" }]);
  React.useEffect(() => {
    if (open) setParts([{ counterparty_id: null, share_amount: "", share_percent: "" }]);
  }, [open]);
  const save = useMutation({
    mutationFn: () =>
      api("/shared-expenses", {
        body: {
          description: f.description,
          total_amount: f.total_amount,
          occurred_on: f.occurred_on,
          currency: household?.base_currency,
          payer_counterparty_id: f.payer || null,
          split_method: f.split_method,
          merchant_name: f.merchant_name || null,
          participants: parts.map((p) => ({
            counterparty_id: p.counterparty_id,
            share_amount: f.split_method === "exact" ? p.share_amount : null,
            share_percent: f.split_method === "percent" ? p.share_percent : null,
          })),
        },
      }),
    onSuccess: () => {
      inv();
      onOpenChange(false);
      toast.success("Shared expense recorded. The purchase is counted once; settlements are tracked separately.");
    },
    onError: err,
  });
  const names = new Map((people.data ?? []).map((p) => [p.id, p.name]));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title="Split a bill" description="Record who paid and each person's share. Reimbursements are settlements and never add to the purchase total.">
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Description" htmlFor="s-d">
              <Input id="s-d" required value={f.description} onChange={(e) => setF((x) => ({ ...x, description: e.target.value }))} />
            </Field>
            <Field label="Total" htmlFor="s-t">
              <Input id="s-t" required inputMode="decimal" value={f.total_amount} onChange={(e) => setF((x) => ({ ...x, total_amount: e.target.value }))} />
            </Field>
            <Field label="Date" htmlFor="s-o">
              <Input id="s-o" type="date" value={f.occurred_on} onChange={(e) => setF((x) => ({ ...x, occurred_on: e.target.value }))} />
            </Field>
            <Field label="Merchant" htmlFor="s-m">
              <Input id="s-m" value={f.merchant_name} onChange={(e) => setF((x) => ({ ...x, merchant_name: e.target.value }))} />
            </Field>
            <Field label="Who paid?" htmlFor="s-p">
              <Select id="s-p" value={f.payer} onChange={(e) => setF((x) => ({ ...x, payer: e.target.value }))}>
                <option value="">I paid</option>
                {(people.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} paid
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Split" htmlFor="s-sm">
              <Select id="s-sm" value={f.split_method} onChange={(e) => setF((x) => ({ ...x, split_method: e.target.value }))}>
                <option value="equal">Equally</option>
                <option value="exact">Exact amounts</option>
                <option value="percent">Percentages</option>
              </Select>
            </Field>
          </div>
          <div className="grid gap-2">
            <p className="text-sm font-medium">Participants</p>
            {parts.map((p, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-40 truncate text-sm">{p.counterparty_id ? names.get(p.counterparty_id) : "You"}</span>
                {f.split_method === "exact" && (
                  <Input className="w-32" inputMode="decimal" placeholder="Amount" aria-label="Share amount" value={p.share_amount} onChange={(e) => setParts((x) => x.map((y, j) => (j === i ? { ...y, share_amount: e.target.value } : y)))} />
                )}
                {f.split_method === "percent" && (
                  <Input className="w-24" inputMode="decimal" placeholder="%" aria-label="Share percent" value={p.share_percent} onChange={(e) => setParts((x) => x.map((y, j) => (j === i ? { ...y, share_percent: e.target.value } : y)))} />
                )}
                {i > 0 && (
                  <Button type="button" variant="ghost" size="sm" onClick={() => setParts((x) => x.filter((_, j) => j !== i))}>
                    Remove
                  </Button>
                )}
              </div>
            ))}
            <Select
              aria-label="Add participant"
              className="w-60"
              value=""
              onChange={(e) => e.target.value && setParts((x) => [...x, { counterparty_id: e.target.value, share_amount: "", share_percent: "" }])}
            >
              <option value="">+ Add a person…</option>
              {(people.data ?? [])
                .filter((p) => !parts.some((x) => x.counterparty_id === p.id))
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
            </Select>
          </div>
          <Button type="submit" loading={save.isPending} disabled={parts.length < 2}>
            <Split /> Save split
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SettleDialog({ target, onClose }: { target: { se: any; p: any } | null; onClose: () => void }) {
  const inv = useInvalidate();
  const [amount, setAmount] = React.useState("");
  const [on, setOn] = React.useState(today());
  React.useEffect(() => setAmount(target ? String(Number(target.p.outstanding)) : ""), [target]);
  const save = useMutation({
    mutationFn: () => api(`/shared-expenses/${target!.se.id}/settle`, { body: { participant_id: target!.p.id, amount, settled_on: on } }),
    onSuccess: () => {
      inv();
      onClose();
      toast.success("Settlement recorded");
    },
    onError: err,
  });
  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Record settlement" description={target ? `${target.p.name} — outstanding ${money(target.p.outstanding, target.se.currency)}` : undefined}>
        <div className="grid gap-3">
          <Field label="Amount" htmlFor="st-a">
            <Input id="st-a" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Field label="Date" htmlFor="st-d">
            <Input id="st-d" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
          </Field>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            <HandCoins /> Save
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function PeoplePage() {
  const { household, canWrite } = useAuth();
  const cur = household?.base_currency ?? "INR";
  const [dlg, setDlg] = React.useState<"" | "person" | "loan" | "split">("");
  const [repay, setRepay] = React.useState<any>(null);
  const [settle, setSettle] = React.useState<{ se: any; p: any } | null>(null);
  const balances = useQuery({ queryKey: ["people-balances"], queryFn: () => api<any[]>("/counterparties/balances") });
  const loans = useQuery({ queryKey: ["loans"], queryFn: () => api<any[]>("/loans") });
  const shared = useQuery({ queryKey: ["shared"], queryFn: () => api<any[]>("/shared-expenses") });
  const names = new Map((balances.data ?? []).map((p) => [p.id, p.name]));
  return (
    <>
      <PageHeader
        title="People & Shared Expenses"
        description="Money sent and received, loans, and split bills — with who owes what."
        actions={
          canWrite && (
            <>
              <Button variant="outline" onClick={() => setDlg("person")}>
                <UserPlus /> Add person
              </Button>
              <Button variant="outline" onClick={() => setDlg("loan")}>
                <HandCoins /> Record loan
              </Button>
              <Button onClick={() => setDlg("split")}>
                <Split /> Split a bill
              </Button>
            </>
          )
        }
      />
      <Tabs defaultValue="people">
        <TabsList className="mb-4">
          <TabsTrigger value="people">Balances</TabsTrigger>
          <TabsTrigger value="shared">Shared expenses</TabsTrigger>
          <TabsTrigger value="loans">Loans</TabsTrigger>
        </TabsList>
        <TabsContent value="people">
          {balances.isLoading ? (
            <Skeleton className="h-40" />
          ) : (balances.data ?? []).length === 0 ? (
            <EmptyState title="No people yet" description="Add someone to track payments, loans and shared bills." action={canWrite && <Button onClick={() => setDlg("person")}>Add person</Button>} />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {balances.data!.map((p) => (
                <Card key={p.id} className="p-4">
                  <p className="font-medium">{p.name}</p>
                  <p className="text-xs text-muted-foreground">{[p.phone, p.upi_id].filter(Boolean).join(" · ") || "—"}</p>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <p className="text-xs text-muted-foreground">Owes you</p>
                      <p className="font-semibold tabular">{money(p.receivable, cur)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">You owe</p>
                      <p className="font-semibold tabular">{money(p.payable, cur)}</p>
                    </div>
                  </div>
                  <div className="mt-3 flex gap-1">
                    <Button size="sm" variant="ghost" asChild>
                      <Link to={`/transactions?counterparty_id=${p.id}`}>Transactions</Link>
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => download(`/reports/person?counterparty_id=${p.id}&date_from=2000-01-01&format=pdf`, `${p.name}.pdf`)}>
                      Export
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="shared" className="grid gap-3">
          {(shared.data ?? []).length === 0 ? (
            <EmptyState title="No shared expenses" description="Split a restaurant bill or trip cost; the purchase is counted once." />
          ) : (
            shared.data!.map((s) => (
              <Card key={s.id} className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{s.description}</span>
                  <span className="text-sm text-muted-foreground">
                    {date(s.occurred_on)} · {money(s.total_amount, s.currency)} · paid by {s.payer}
                  </span>
                  <Badge tone="primary" className="ml-auto">
                    Your share {money(s.your_share, s.currency)}
                  </Badge>
                </div>
                <ul className="mt-3 grid gap-1.5 text-sm">
                  {s.participants.map((p: any) => {
                    const open = Number(p.outstanding) > 0;
                    const withYou = (s.payer_counterparty_id === null && p.counterparty_id !== null) || (s.payer_counterparty_id !== null && p.counterparty_id === null);
                    return (
                      <li key={p.id} className="flex flex-wrap items-center gap-2">
                        <span className="w-32 truncate">{p.name}</span>
                        <span className="tabular">{money(p.share_amount, s.currency)}</span>
                        <span className={cn("text-xs", open ? "text-warning" : "text-success")}>{open ? `${money(p.outstanding, s.currency)} outstanding` : "settled"}</span>
                        {canWrite && open && withYou && (
                          <Button size="sm" variant="outline" className="ml-auto" onClick={() => setSettle({ se: s, p })}>
                            Record settlement
                          </Button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </Card>
            ))
          )}
        </TabsContent>
        <TabsContent value="loans" className="grid gap-3">
          {(loans.data ?? []).length === 0 ? (
            <EmptyState title="No loans" description="Track money lent or borrowed. Principal never counts as spending; only interest does." />
          ) : (
            loans.data!.map((l) => (
              <Card key={l.id} className="p-4 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {l.direction === "given" ? "Lent to" : "Borrowed from"} {names.get(l.counterparty_id) ?? "—"}
                  </span>
                  <Badge tone={l.status === "open" ? "warning" : "success"}>{l.status}</Badge>
                  <span className="ml-auto font-semibold tabular">{money(l.outstanding, l.currency)} outstanding</span>
                </div>
                <p className="mt-1 text-muted-foreground">
                  Principal {money(l.principal, l.currency)} · repaid {money(l.principal_repaid, l.currency)} · interest {money(l.interest_paid, l.currency)} · since {date(l.start_date)}
                  {l.due_date ? ` · due ${date(l.due_date)}` : ""}
                </p>
                {canWrite && l.status === "open" && (
                  <Button size="sm" variant="outline" className="mt-2" onClick={() => setRepay(l)}>
                    <Plus /> Repayment
                  </Button>
                )}
              </Card>
            ))
          )}
        </TabsContent>
      </Tabs>
      <AddPerson open={dlg === "person"} onOpenChange={(o) => setDlg(o ? "person" : "")} />
      <LoanDialog open={dlg === "loan"} onOpenChange={(o) => setDlg(o ? "loan" : "")} />
      <SplitDialog open={dlg === "split"} onOpenChange={(o) => setDlg(o ? "split" : "")} />
      <RepayDialog loan={repay} onClose={() => setRepay(null)} />
      <SettleDialog target={settle} onClose={() => setSettle(null)} />
    </>
  );
}

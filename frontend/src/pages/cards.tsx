import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Calculator, CreditCard, FileText, Link2, Plus, Trash2, Unlink, Wallet } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, Field, Input, PageHeader, Progress, Select, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { AccountDialog } from "@/pages/accounts";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, date, label, money, today } from "@/lib/format";
import { useAccounts } from "@/lib/queries";

type Statement = {
  id: string;
  account_id: string;
  period_start: string;
  statement_date: string;
  due_date: string;
  total_due: string;
  minimum_due: string;
  interest_charged: string;
  fees_charged: string;
  currency: string;
  paid_amount: string;
  remaining_amount: string;
  minimum_remaining: string;
  status: "unpaid" | "partially_paid" | "minimum_paid" | "paid" | "overdue" | "no_dues";
  days_until_due: number;
  paid_late: boolean;
  interest_may_apply: boolean;
  notes: string;
  payments?: { link_id: string; transaction_id: string; occurred_on: string; description: string; amount: string; transaction_amount: string; status: string; on_time: boolean }[];
  payment_suggestions?: { transaction_id: string; occurred_on: string; description: string; amount: string; available: string; reasons: string[] }[];
  cycle?: { previous_balance: string; purchases: string; credits: string; payments: string; computed_total_due: string; transactions: { id: string; occurred_on: string; description: string; kind: string; amount: string }[] };
  charge_transaction_ids?: string[];
};

type CardSummary = {
  account_id: string;
  name: string;
  institution: string;
  masked_number: string;
  currency: string;
  credit_limit: string | null;
  statement_day: number | null;
  due_day: number | null;
  outstanding: string;
  credit_balance: string;
  available_credit: string | null;
  utilization_pct: number | null;
  unbilled_amount: string;
  next_statement_date: string | null;
  last_statement: Statement | null;
  statements?: Statement[];
};

const STATUS_TONE: Record<Statement["status"], "success" | "warning" | "danger" | "info" | "default"> = {
  paid: "success",
  no_dues: "success",
  minimum_paid: "info",
  partially_paid: "warning",
  unpaid: "warning",
  overdue: "danger",
};

const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong");

export function BillStatus({ s }: { s: Statement }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Badge tone={STATUS_TONE[s.status]}>{s.status === "no_dues" ? "No dues" : label(s.status)}</Badge>
      {s.paid_late && <Badge tone="danger">Paid late</Badge>}
    </span>
  );
}

function dueText(s: Statement) {
  if (s.status === "paid" || s.status === "no_dues") return `Was due ${date(s.due_date)}`;
  if (s.days_until_due < 0) return `${-s.days_until_due} day(s) overdue (${date(s.due_date)})`;
  if (s.days_until_due === 0) return "Due today";
  return `Due in ${s.days_until_due} day(s) · ${date(s.due_date)}`;
}

function StatementDialog({ card, open, onOpenChange }: { card: CardSummary | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const blank = { statement_date: today(), period_start: "", due_date: "", total_due: "", minimum_due: "", interest_charged: "", fees_charged: "", record_charges: false, notes: "" };
  const [f, setF] = React.useState(blank);
  const [preview, setPreview] = React.useState<any>(null);
  React.useEffect(() => {
    if (open) {
      setF(blank);
      setPreview(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, card?.account_id]);
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  const calc = useMutation({
    mutationFn: () => api(`/credit-cards/${card!.account_id}/statement-preview?statement_date=${f.statement_date}${f.period_start ? `&period_start=${f.period_start}` : ""}`),
    onSuccess: (p: any) => {
      setPreview(p);
      setF((x) => ({ ...x, period_start: x.period_start || p.period_start, due_date: x.due_date || p.suggested_due_date || "" }));
    },
    onError: err,
  });
  const save = useMutation({
    mutationFn: () =>
      api(`/credit-cards/${card!.account_id}/statements`, {
        body: {
          ...f,
          period_start: f.period_start || null,
          interest_charged: f.interest_charged || "0",
          fees_charged: f.fees_charged || "0",
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries();
      onOpenChange(false);
      toast.success("Bill saved. Pay it or link an existing payment from the bill.");
    },
    onError: err,
  });
  const cur = card?.currency ?? "INR";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title={`Add bill · ${card?.name ?? ""}`} description="Enter the figures from your card statement. SmartSpend can also total the cycle from your recorded card transactions so you can cross-check.">
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Statement date" htmlFor="st-date">
              <Input id="st-date" type="date" required value={f.statement_date} onChange={set("statement_date")} />
            </Field>
            <Field label="Cycle start (optional)" htmlFor="st-start" hint="Defaults to the day after the previous bill">
              <Input id="st-start" type="date" value={f.period_start} onChange={set("period_start")} />
            </Field>
            <Field label="Due date" htmlFor="st-due">
              <Input id="st-due" type="date" required value={f.due_date} onChange={set("due_date")} />
            </Field>
          </div>
          <div className="rounded-md border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="outline" size="sm" loading={calc.isPending} onClick={() => calc.mutate()}>
                <Calculator /> Calculate from my card transactions
              </Button>
              {preview && (
                <Button type="button" size="sm" variant="ghost" onClick={() => setF((x) => ({ ...x, total_due: String(Number(preview.computed_total_due)) }))}>
                  Use {money(preview.computed_total_due, cur)} as total due
                </Button>
              )}
            </div>
            {preview && (
              <div className="mt-3 grid gap-2 text-sm">
                <p className="text-muted-foreground">
                  {date(preview.period_start)} – {date(preview.period_end)}: previous balance {money(preview.previous_balance, cur)} + purchases {money(preview.purchases, cur)} − refunds/credits {money(preview.credits, cur)} − payments {money(preview.payments, cur)} ={" "}
                  <strong className="text-foreground">{money(preview.computed_total_due, cur)}</strong>
                </p>
                <p className="text-xs text-muted-foreground">If this differs from your statement, a transaction may be missing or not recorded on this card. The statement's own figures are what you owe.</p>
                {preview.transactions.length > 0 && (
                  <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground">{preview.transactions.length} transaction(s) in this cycle</summary>
                    <ul className="mt-2 max-h-40 overflow-y-auto text-xs">
                      {preview.transactions.map((t: any) => (
                        <li key={t.id} className="flex justify-between gap-2 py-0.5">
                          <span className="truncate">
                            {date(t.occurred_on)} · {t.description} <span className="text-muted-foreground">({t.kind})</span>
                          </span>
                          <span className="tabular">{money(t.amount, cur)}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Total amount due" htmlFor="st-total">
              <Input id="st-total" inputMode="decimal" required value={f.total_due} onChange={set("total_due")} />
            </Field>
            <Field label="Minimum amount due" htmlFor="st-min" hint="As printed on the statement">
              <Input id="st-min" inputMode="decimal" required value={f.minimum_due} onChange={set("minimum_due")} />
            </Field>
            <Field label="Interest charged (optional)" htmlFor="st-int">
              <Input id="st-int" inputMode="decimal" value={f.interest_charged} onChange={set("interest_charged")} />
            </Field>
            <Field label="Fees & late charges (optional)" htmlFor="st-fee">
              <Input id="st-fee" inputMode="decimal" value={f.fees_charged} onChange={set("fees_charged")} />
            </Field>
          </div>
          {(Number(f.interest_charged) > 0 || Number(f.fees_charged) > 0) && (
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={f.record_charges} onChange={(e) => setF((x) => ({ ...x, record_charges: e.target.checked }))} />
              <span>
                Record interest and fees as expenses on this card. Leave unticked if you'll import the card statement, which already contains these charges.
              </span>
            </label>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              Save bill
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PayDialog({ s, onClose }: { s: Statement | null; onClose: () => void }) {
  const qc = useQueryClient();
  const accounts = useAccounts();
  // Card bills are usually paid from a bank account, so list those first (and default to one).
  const ORDER: Record<string, number> = { bank: 0, upi: 1, wallet: 2, debit_card: 3, other: 4, cash: 5 };
  const sources = (accounts.data ?? [])
    .filter((a) => a.type !== "credit_card" && a.currency === s?.currency)
    .sort((a, b) => (ORDER[a.type] ?? 9) - (ORDER[b.type] ?? 9) || a.name.localeCompare(b.name));
  const [from, setFrom] = React.useState("");
  const [preset, setPreset] = React.useState<"full" | "minimum" | "custom">("full");
  const [amount, setAmount] = React.useState("");
  const [on, setOn] = React.useState(today());
  const [method, setMethod] = React.useState("bank_transfer");
  React.useEffect(() => {
    if (s) {
      setPreset("full");
      setAmount(String(Number(s.remaining_amount)));
      setOn(today());
    }
  }, [s]);
  React.useEffect(() => {
    if (!from && sources[0]) setFrom(sources[0].id);
  }, [sources, from]);
  const choose = (p: typeof preset) => {
    setPreset(p);
    if (s && p === "full") setAmount(String(Number(s.remaining_amount)));
    if (s && p === "minimum") setAmount(String(Number(s.minimum_remaining)));
  };
  const pay = useMutation({
    mutationFn: () => api(`/credit-card-statements/${s!.id}/pay`, { idempotent: true, body: { from_account_id: from, amount, paid_on: on, payment_method: method } }),
    onSuccess: (r: Statement) => {
      qc.invalidateQueries();
      onClose();
      toast.success(r.status === "paid" ? "Bill paid in full" : `Payment recorded · ${money(r.remaining_amount, r.currency)} still due`);
    },
    onError: err,
  });
  return (
    <Dialog open={!!s} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title="Pay credit card bill" description="Records a transfer from your bank to the card. It is not counted as spending, because the card purchases already were.">
        {s && (
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              pay.mutate();
            }}
          >
            <div role="radiogroup" aria-label="Quick amount" className="grid grid-cols-3 gap-2">
              {(
                [
                  ["full", "Remaining", s.remaining_amount],
                  ["minimum", "Minimum", s.minimum_remaining],
                  ["custom", "Other", null],
                ] as const
              ).map(([k, l, v]) => (
                <button
                  type="button"
                  role="radio"
                  aria-checked={preset === k}
                  key={k}
                  onClick={() => choose(k)}
                  className={cn("rounded-md border p-2 text-left text-sm cursor-pointer", preset === k && "border-primary bg-accent")}
                >
                  <span className="block font-medium">{l}</span>
                  {v !== null && <span className="tabular text-muted-foreground">{money(v, s.currency)}</span>}
                </button>
              ))}
            </div>
            <Field label="Amount" htmlFor="pay-amt">
              <Input id="pay-amt" inputMode="decimal" required value={amount} onChange={(e) => {
                setAmount(e.target.value);
                setPreset("custom");
              }} />
            </Field>
            {preset === "minimum" && <p className="text-xs text-warning">Paying only the minimum usually means interest is charged on the rest.</p>}
            <div className="grid grid-cols-2 gap-3">
              <Field label="Pay from" htmlFor="pay-from">
                <Select id="pay-from" required value={from} onChange={(e) => setFrom(e.target.value)}>
                  {sources.length === 0 && <option value="">Add a bank account first</option>}
                  {sources.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Paid on" htmlFor="pay-on">
                <Input id="pay-on" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
              </Field>
            </div>
            <Field label="Method" htmlFor="pay-method">
              <Select id="pay-method" value={method} onChange={(e) => setMethod(e.target.value)}>
                {["bank_transfer", "net_banking", "upi", "debit_card", "cash", "wallet", "cheque", "other"].map((m) => (
                  <option key={m} value={m}>
                    {label(m)}
                  </option>
                ))}
              </Select>
            </Field>
            <Button type="submit" loading={pay.isPending} disabled={!from || !amount}>
              <Wallet /> Record payment
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function BillDetail({ id, onClose, onPay }: { id: string | null; onClose: () => void; onPay: (s: Statement) => void }) {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const [deleting, setDeleting] = React.useState(false);
  const bill = useQuery({ queryKey: ["bill", id], queryFn: () => api<Statement>(`/credit-card-statements/${id}`), enabled: !!id });
  const inv = () => qc.invalidateQueries();
  const link = useMutation({ mutationFn: (tid: string) => api(`/credit-card-statements/${id}/link`, { body: { transaction_id: tid } }), onSuccess: () => { inv(); toast.success("Payment linked to the bill"); }, onError: err });
  const unlink = useMutation({ mutationFn: (lid: string) => api(`/credit-card-statements/${id}/unlink`, { body: { link_id: lid } }), onSuccess: () => { inv(); toast.success("Payment unlinked"); }, onError: err });
  const del = useMutation({
    mutationFn: () => api(`/credit-card-statements/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      inv();
      setDeleting(false);
      onClose();
      toast.success("Bill deleted. Payments stay in your ledger.");
    },
    onError: err,
  });
  const s = bill.data;
  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={s ? `Bill of ${date(s.statement_date)}` : "Bill"} description={s ? `Cycle ${date(s.period_start)} – ${date(s.statement_date)}` : undefined}>
        {!s ? (
          <Skeleton className="h-40" />
        ) : (
          <div className="grid gap-5 text-sm">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">Total due</p>
                <p className="text-lg font-semibold tabular">{money(s.total_due, s.currency)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Paid</p>
                <p className="text-lg font-semibold tabular">{money(s.paid_amount, s.currency)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Remaining</p>
                <p className="text-lg font-semibold tabular">{money(s.remaining_amount, s.currency)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Status</p>
                <BillStatus s={s} />
                <p className="text-xs text-muted-foreground">{dueText(s)}</p>
              </div>
            </div>
            <p className="text-muted-foreground">
              Minimum due {money(s.minimum_due, s.currency)}
              {Number(s.minimum_remaining) > 0 ? ` (${money(s.minimum_remaining, s.currency)} still needed)` : " (met)"}
              {Number(s.interest_charged) > 0 && ` · interest ${money(s.interest_charged, s.currency)}`}
              {Number(s.fees_charged) > 0 && ` · fees ${money(s.fees_charged, s.currency)}`}
            </p>
            {s.interest_may_apply && s.status !== "paid" && <p className="flex items-center gap-2 rounded-md bg-amber-100/60 p-2 dark:bg-amber-950/40"><AlertTriangle className="size-4 text-warning" /> The full amount wasn't paid by the due date, so interest will probably appear on the next bill.</p>}
            <section>
              <h4 className="mb-2 font-medium">Payments</h4>
              {(s.payments ?? []).length === 0 ? (
                <p className="text-muted-foreground">No payments linked yet.</p>
              ) : (
                <ul className="grid gap-2">
                  {s.payments!.map((p) => (
                    <li key={p.link_id} className="flex flex-wrap items-center gap-2 rounded-md border p-2">
                      <span className="flex-1">
                        {date(p.occurred_on)} · {p.description}
                        {p.amount !== p.transaction_amount && <span className="text-muted-foreground"> ({money(p.amount, s.currency)} of {money(p.transaction_amount, s.currency)})</span>}
                      </span>
                      <Badge tone={p.on_time ? "success" : "danger"}>{p.on_time ? "On time" : "Late"}</Badge>
                      <span className="tabular font-medium">{money(p.amount, s.currency)}</span>
                      {canWrite && (
                        <Button size="sm" variant="ghost" onClick={() => unlink.mutate(p.link_id)} aria-label="Unlink payment">
                          <Unlink />
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
            {canWrite && (s.payment_suggestions ?? []).length > 0 && s.status !== "paid" && (
              <section>
                <h4 className="mb-2 font-medium">Payments found in your records</h4>
                <ul className="grid gap-2">
                  {s.payment_suggestions!.map((p) => (
                    <li key={p.transaction_id} className="flex flex-wrap items-center gap-2 rounded-md border border-dashed p-2">
                      <span className="flex-1">
                        {date(p.occurred_on)} · {p.description}
                        <span className="block text-xs text-muted-foreground">{p.reasons.join(" · ")}</span>
                      </span>
                      <span className="tabular">{money(p.available, s.currency)}</span>
                      <Button size="sm" variant="outline" loading={link.isPending} onClick={() => link.mutate(p.transaction_id)}>
                        <Link2 /> Link
                      </Button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {s.cycle && (
              <section>
                <h4 className="mb-2 font-medium">This cycle in your records</h4>
                <p className="text-muted-foreground">
                  Purchases {money(s.cycle.purchases, s.currency)} · credits {money(s.cycle.credits, s.currency)} · payments {money(s.cycle.payments, s.currency)} · calculated balance {money(s.cycle.computed_total_due, s.currency)}
                  {s.cycle.computed_total_due !== s.total_due && <span className="text-warning"> (statement says {money(s.total_due, s.currency)})</span>}
                </p>
                <Link className="text-xs text-primary hover:underline" to={`/transactions?account_id=${s.account_id}&date_from=${s.period_start}&date_to=${s.statement_date}`} onClick={onClose}>
                  View the cycle's transactions
                </Link>
              </section>
            )}
            {canWrite && (
              <div className="flex flex-wrap justify-end gap-2 border-t pt-3">
                <Button variant="ghost" onClick={() => setDeleting(true)}>
                  <Trash2 /> Delete bill
                </Button>
                {s.status !== "paid" && s.status !== "no_dues" && (
                  <Button onClick={() => onPay(s)}>
                    <Wallet /> Pay bill
                  </Button>
                )}
              </div>
            )}
          </div>
        )}
        <ConfirmDialog
          open={deleting}
          onOpenChange={setDeleting}
          destructive
          title="Delete this bill?"
          description="The bill and its payment links are removed. Payments stay in your ledger; interest/fee expenses created by this bill are voided."
          confirmLabel="Delete bill"
          loading={del.isPending}
          onConfirm={() => del.mutate()}
        />
      </DialogContent>
    </Dialog>
  );
}

function CardPanel({ c, onAddBill, onPay, onOpenBill }: { c: CardSummary; onAddBill: () => void; onPay: (s: Statement) => void; onOpenBill: (id: string) => void }) {
  const { canWrite } = useAuth();
  const detail = useQuery({ queryKey: ["card", c.account_id], queryFn: () => api<CardSummary>(`/credit-cards/${c.account_id}`) });
  const last = c.last_statement;
  const util = c.utilization_pct ?? 0;
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
          <CreditCard className="size-5" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{c.name}</p>
          <p className="text-xs text-muted-foreground">
            {[c.institution, c.masked_number && `•• ${c.masked_number}`, c.statement_day && `statement on the ${c.statement_day}`, c.due_day && `due on the ${c.due_day}`].filter(Boolean).join(" · ") || "Credit card"}
          </p>
        </div>
        {canWrite && (
          <Button variant="outline" size="sm" onClick={onAddBill}>
            <Plus /> Add bill
          </Button>
        )}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">Outstanding</p>
          <p className="text-xl font-semibold tabular">{money(c.outstanding, c.currency)}</p>
          {Number(c.credit_balance) > 0 && <p className="text-xs text-success">Credit balance {money(c.credit_balance, c.currency)}</p>}
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Available credit</p>
          <p className="text-xl font-semibold tabular">{c.available_credit === null ? "—" : money(c.available_credit, c.currency)}</p>
          {c.credit_limit && <p className="text-xs text-muted-foreground">of {money(c.credit_limit, c.currency)}</p>}
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Unbilled</p>
          <p className="text-xl font-semibold tabular">{money(c.unbilled_amount, c.currency)}</p>
          {c.next_statement_date && <p className="text-xs text-muted-foreground">next bill {date(c.next_statement_date)}</p>}
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Utilization</p>
          <p className="text-xl font-semibold tabular">{c.utilization_pct === null ? "—" : `${c.utilization_pct}%`}</p>
          {c.utilization_pct !== null && <Progress className="mt-1" value={util} tone={util >= 80 ? "danger" : util >= 30 ? "warning" : "primary"} />}
        </div>
      </div>
      {last ? (
        <div className={cn("mt-4 flex flex-wrap items-center gap-3 rounded-md border p-3", last.status === "overdue" && "border-destructive/50 bg-destructive/5")}>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              Latest bill · {money(last.total_due, last.currency)} <span className="font-normal text-muted-foreground">(minimum {money(last.minimum_due, last.currency)})</span>
            </p>
            <p className="text-xs text-muted-foreground">
              {dueText(last)} · paid {money(last.paid_amount, last.currency)} · remaining {money(last.remaining_amount, last.currency)}
            </p>
          </div>
          <BillStatus s={last} />
          <Button size="sm" variant="ghost" onClick={() => onOpenBill(last.id)}>
            <FileText /> Details
          </Button>
          {canWrite && last.status !== "paid" && last.status !== "no_dues" && (
            <Button size="sm" onClick={() => onPay(last)}>
              <Wallet /> Pay
            </Button>
          )}
        </div>
      ) : (
        <p className="mt-4 rounded-md border border-dashed p-3 text-sm text-muted-foreground">No bills yet. Add your latest statement to track the due date and payments.</p>
      )}
      {(detail.data?.statements ?? []).length > 1 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm text-muted-foreground">Bill history ({detail.data!.statements!.length})</summary>
          <Table className="mt-2">
            <THead>
              <tr>
                <TH>Statement</TH>
                <TH>Due</TH>
                <TH className="text-right">Total</TH>
                <TH className="text-right">Paid</TH>
                <TH>Status</TH>
              </tr>
            </THead>
            <TBody>
              {detail.data!.statements!.map((s) => (
                <TR key={s.id} className="cursor-pointer" onClick={() => onOpenBill(s.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpenBill(s.id)}>
                  <TD>{date(s.statement_date)}</TD>
                  <TD>{date(s.due_date)}</TD>
                  <TD className="text-right tabular">{money(s.total_due, s.currency)}</TD>
                  <TD className="text-right tabular">{money(s.paid_amount, s.currency)}</TD>
                  <TD>
                    <BillStatus s={s} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </details>
      )}
    </Card>
  );
}

export function CardsPage() {
  const { canWrite } = useAuth();
  const cards = useQuery({ queryKey: ["cards"], queryFn: () => api<CardSummary[]>("/credit-cards") });
  const [adding, setAdding] = React.useState(false);
  const [billFor, setBillFor] = React.useState<CardSummary | null>(null);
  const [paying, setPaying] = React.useState<Statement | null>(null);
  const [openBill, setOpenBill] = React.useState<string | null>(null);
  return (
    <>
      <PageHeader
        title="Credit Cards"
        description="Bills, due dates and payments. Card purchases count as spending when you make them; paying the bill is a transfer and is never counted twice."
        actions={
          canWrite && (
            <Button onClick={() => setAdding(true)}>
              <Plus /> Add card
            </Button>
          )
        }
      />
      {cards.isLoading ? (
        <Skeleton className="h-48" />
      ) : (cards.data ?? []).length === 0 ? (
        <EmptyState
          title="No credit cards yet"
          description="Add a card with its limit, statement day and due day. Record card purchases against it, then add each month's bill."
          icon={<CreditCard className="size-8" />}
          action={canWrite && <Button onClick={() => setAdding(true)}>Add card</Button>}
        />
      ) : (
        <div className="grid gap-4">
          {cards.data!.map((c) => (
            <CardPanel key={c.account_id} c={c} onAddBill={() => setBillFor(c)} onPay={setPaying} onOpenBill={setOpenBill} />
          ))}
        </div>
      )}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-sm">How card bills are counted</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-1 text-sm text-muted-foreground">
          <p>• Each purchase on the card is spending on the day you make it.</p>
          <p>• Paying the bill moves money from your bank to the card. It reduces what you owe, not your spending.</p>
          <p>• Interest and fees are the only bill charges counted as spending.</p>
          <p>• If the same bill payment appears on both your bank and card statements, it shows up in Duplicates &amp; Reconciliation so it is credited once.</p>
        </CardContent>
      </Card>
      <AccountDialog open={adding} onOpenChange={setAdding} defaultType="credit_card" />
      <StatementDialog card={billFor} open={!!billFor} onOpenChange={(o) => !o && setBillFor(null)} />
      <PayDialog s={paying} onClose={() => setPaying(null)} />
      <BillDetail
        id={openBill}
        onClose={() => setOpenBill(null)}
        onPay={(s) => {
          setOpenBill(null);
          setPaying(s);
        }}
      />
    </>
  );
}

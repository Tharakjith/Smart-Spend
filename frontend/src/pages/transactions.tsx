import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, ChevronLeft, ChevronRight, FileText, Link2, Pencil, Plus, Trash2 } from "lucide-react";
import * as React from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { AddTransactionDialog } from "@/components/add-transaction";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, Skeleton, Table, TBody, TD, TH, THead, TR, Textarea } from "@/components/ui/primitives";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, currentMonth, date, dateTime, IN_TYPES, label, money, monthLabel, PAYMENT_METHODS, shiftMonth, today, TX_TYPES } from "@/lib/format";
import { categoryOptions, type Page, type Transaction, useAccounts, useCategories, useCounterparties } from "@/lib/queries";

export const RECON_TONE: Record<string, "default" | "success" | "warning" | "danger" | "info" | "primary"> = {
  unmatched: "default",
  suggested_match: "info",
  matched: "success",
  fully_paid: "success",
  partially_paid: "warning",
  partially_reconciled: "warning",
  needs_review: "danger",
  disputed: "danger",
  reversed: "default",
};

export function ReconBadge({ status }: { status: string }) {
  return <Badge tone={RECON_TONE[status] ?? "default"}>{label(status)}</Badge>;
}

const money2 = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,2})?$/, "Enter an amount like 450 or 450.50")
  .refine((v) => Number(v) > 0, "Must be greater than zero");
const optMoney = z.string().trim().regex(/^(\d+(\.\d{1,4})?)?$/, "Invalid number").optional();

const txSchema = z
  .object({
    type: z.enum(TX_TYPES),
    occurred_on: z.string().min(10, "Pick a date"),
    amount: money2,
    currency: z.string().length(3),
    description: z.string().max(500).optional(),
    merchant_name: z.string().max(200).optional(),
    category_id: z.string().optional(),
    counterparty_id: z.string().optional(),
    account_id: z.string().optional(),
    to_account_id: z.string().optional(),
    payment_method: z.string().optional(),
    record_as: z.enum(["payment", "bill"]),
    upi_txn_id: z.string().max(64).optional(),
    invoice_number: z.string().max(64).optional(),
    notes: z.string().max(4000).optional(),
    tags: z.string().optional(),
    line_items: z.array(z.object({ name: z.string().min(1, "Name required"), quantity: optMoney, unit: z.string().optional(), unit_price: optMoney, line_total: optMoney })),
  })
  .refine((v) => !["transfer", "credit_card_payment"].includes(v.type) || (v.account_id && v.to_account_id && v.account_id !== v.to_account_id), {
    path: ["to_account_id"],
    message: "Transfers need two different accounts",
  });
type TxForm = z.infer<typeof txSchema>;

const blank = (v?: string | null) => (v === "" || v === undefined ? null : v);

export function TransactionDialog({ open, onOpenChange, tx }: { open: boolean; onOpenChange: (o: boolean) => void; tx?: Transaction }) {
  const qc = useQueryClient();
  const { household } = useAuth();
  const cats = useCategories();
  const accounts = useAccounts();
  const people = useCounterparties();
  const editing = !!tx;
  const locked = editing && (tx.sources ?? []).some((s) => s.source_type !== "manual");
  const form = useForm<TxForm>({
    resolver: zodResolver(txSchema),
    values: tx
      ? {
          type: tx.type as TxForm["type"],
          occurred_on: tx.occurred_on,
          amount: tx.amount.replace(/(\.\d\d)0+$/, "$1"),
          currency: tx.currency,
          description: tx.description,
          merchant_name: tx.merchant_name ?? "",
          category_id: tx.category_id ?? "",
          counterparty_id: tx.counterparty_id ?? "",
          account_id: tx.account_id ?? "",
          to_account_id: tx.to_account_id ?? "",
          payment_method: tx.payment_method ?? "",
          record_as: "payment",
          notes: tx.notes,
          tags: tx.tags.join(", "),
          line_items: [],
        }
      : { type: "expense", occurred_on: today(), amount: "", currency: household?.base_currency ?? "INR", record_as: "payment", line_items: [], payment_method: "" },
  });
  const items = useFieldArray({ control: form.control, name: "line_items" });
  const type = form.watch("type");
  const errors = form.formState.errors;

  const save = useMutation({
    mutationFn: async (v: TxForm) => {
      const tags = (v.tags ?? "").split(",").map((t) => t.trim()).filter(Boolean);
      if (editing) {
        const patch: Record<string, unknown> = {
          version: tx.version,
          description: v.description ?? "",
          category_id: blank(v.category_id),
          counterparty_id: blank(v.counterparty_id),
          account_id: blank(v.account_id),
          to_account_id: blank(v.to_account_id),
          payment_method: blank(v.payment_method),
          notes: v.notes ?? "",
          tags,
        };
        if ((v.merchant_name ?? "") !== (tx.merchant_name ?? "")) patch.merchant_name = v.merchant_name;
        if (!locked) Object.assign(patch, { amount: v.amount, occurred_on: v.occurred_on, type: v.type });
        return api(`/transactions/${tx.id}`, { method: "PATCH", body: patch });
      }
      return api("/transactions", {
        idempotent: true,
        body: {
          type: v.type,
          occurred_on: v.occurred_on,
          amount: v.amount,
          currency: v.currency,
          description: v.description ?? "",
          merchant_name: blank(v.merchant_name),
          category_id: blank(v.category_id),
          counterparty_id: blank(v.counterparty_id),
          account_id: blank(v.account_id),
          to_account_id: blank(v.to_account_id),
          payment_method: blank(v.payment_method),
          record_as: v.record_as,
          upi_txn_id: blank(v.upi_txn_id),
          invoice_number: blank(v.invoice_number),
          notes: v.notes ?? "",
          tags,
          line_items: v.line_items.map((li) => ({ name: li.name, quantity: blank(li.quantity), unit: blank(li.unit), unit_price: blank(li.unit_price), line_total: blank(li.line_total) })),
        },
      });
    },
    onSuccess: (r: Transaction) => {
      qc.invalidateQueries();
      onOpenChange(false);
      form.reset();
      if (!editing && r.reconciliation_status === "suggested_match") toast.info("Saved. This looks like it may match another record — check Duplicates & Reconciliation.");
      else toast.success(editing ? "Transaction updated" : "Transaction saved");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Save failed"),
  });

  const catKind = type === "income" ? "income" : "expense";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={editing ? "Edit transaction" : "Add transaction"} description="Record cash, UPI, card, transfers, loans and more. Amounts are exact decimals." wide>
        <form onSubmit={form.handleSubmit((v) => save.mutate(v))} className="grid gap-4" noValidate>
          {locked && <p className="rounded-md bg-muted p-2 text-xs text-muted-foreground">Amount, date and type come from an uploaded document or imported statement and can't be edited here.</p>}
          <div className="grid gap-3 sm:grid-cols-4">
            <Field label="Type" htmlFor="type">
              <Select id="type" disabled={locked} {...form.register("type")}>
                {TX_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {label(t)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Date" htmlFor="occurred_on" error={errors.occurred_on?.message}>
              <Input id="occurred_on" type="date" disabled={locked} max={today()} {...form.register("occurred_on")} />
            </Field>
            <Field label="Amount" htmlFor="amount" error={errors.amount?.message}>
              <Input id="amount" inputMode="decimal" placeholder="0.00" disabled={locked} aria-invalid={!!errors.amount} {...form.register("amount")} />
            </Field>
            <Field label="Currency" htmlFor="currency" error={errors.currency?.message}>
              <Input id="currency" maxLength={3} disabled={editing} {...form.register("currency", { setValueAs: (v: string) => v.toUpperCase() })} />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Description" htmlFor="description">
              <Input id="description" {...form.register("description")} />
            </Field>
            <Field label={type === "expense" || type === "refund" ? "Merchant / payee" : "Merchant (optional)"} htmlFor="merchant_name">
              <Input id="merchant_name" placeholder="e.g. Fresh Mart Supermarket" {...form.register("merchant_name")} />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Category" htmlFor="category_id" hint={!editing ? "Leave blank to auto-categorise" : undefined}>
              <Select id="category_id" {...form.register("category_id")}>
                <option value="">{editing ? "None" : "Auto"}</option>
                {categoryOptions(cats.data, catKind).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Payment method" htmlFor="payment_method">
              <Select id="payment_method" {...form.register("payment_method")}>
                <option value="">—</option>
                {PAYMENT_METHODS.map((p) => (
                  <option key={p} value={p}>
                    {label(p)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Person (counterparty)" htmlFor="counterparty_id">
              <Select id="counterparty_id" {...form.register("counterparty_id")}>
                <option value="">—</option>
                {(people.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={["transfer", "credit_card_payment"].includes(type) ? "From account" : "Account"} htmlFor="account_id">
              <Select id="account_id" {...form.register("account_id")}>
                <option value="">—</option>
                {(accounts.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.currency})
                  </option>
                ))}
              </Select>
            </Field>
            {["transfer", "credit_card_payment"].includes(type) && (
              <Field label="To account" htmlFor="to_account_id" error={errors.to_account_id?.message}>
                <Select id="to_account_id" {...form.register("to_account_id")}>
                  <option value="">—</option>
                  {(accounts.data ?? []).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
          </div>
          {!editing && type === "expense" && (
            <div className="grid gap-3 rounded-md border p-3 sm:grid-cols-3">
              <Field label="Record as" htmlFor="record_as" hint="A bill is evidence of a purchase; a payment is money that moved.">
                <Select id="record_as" {...form.register("record_as")}>
                  <option value="payment">Payment (cash/UPI/card)</option>
                  <option value="bill">Bill / invoice</option>
                </Select>
              </Field>
              <Field label="UPI / UTR reference" htmlFor="upi_txn_id" hint="Helps exact matching">
                <Input id="upi_txn_id" {...form.register("upi_txn_id")} />
              </Field>
              <Field label="Invoice number" htmlFor="invoice_number">
                <Input id="invoice_number" {...form.register("invoice_number")} />
              </Field>
            </div>
          )}
          {!editing && type === "expense" && (
            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Line items (optional)</span>
                <Button type="button" variant="outline" size="sm" onClick={() => items.append({ name: "", quantity: "", unit: "", unit_price: "", line_total: "" })}>
                  <Plus /> Add item
                </Button>
              </div>
              {items.fields.map((f, i) => (
                <div key={f.id} className="grid grid-cols-12 gap-2">
                  <Input className="col-span-4" placeholder="Item" aria-label="Item name" {...form.register(`line_items.${i}.name`)} />
                  <Input className="col-span-2" placeholder="Qty" aria-label="Quantity" {...form.register(`line_items.${i}.quantity`)} />
                  <Input className="col-span-1" placeholder="Unit" aria-label="Unit" {...form.register(`line_items.${i}.unit`)} />
                  <Input className="col-span-2" placeholder="Unit price" aria-label="Unit price" {...form.register(`line_items.${i}.unit_price`)} />
                  <Input className="col-span-2" placeholder="Total" aria-label="Line total" {...form.register(`line_items.${i}.line_total`)} />
                  <Button type="button" variant="ghost" size="icon" onClick={() => items.remove(i)} aria-label="Remove item">
                    <Trash2 />
                  </Button>
                </div>
              ))}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Tags" htmlFor="tags" hint="Comma separated">
              <Input id="tags" {...form.register("tags")} />
            </Field>
            <Field label="Notes" htmlFor="notes">
              <Textarea id="notes" rows={2} {...form.register("notes")} />
            </Field>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              {editing ? "Save changes" : "Save transaction"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function TransactionDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const [editing, setEditing] = React.useState(false);
  const [voiding, setVoiding] = React.useState(false);
  const tx = useQuery({ queryKey: ["tx", id], queryFn: () => api<Transaction>(`/transactions/${id}`), enabled: !!id });
  const history = useQuery({ queryKey: ["tx-audit", id], queryFn: () => api<any[]>(`/transactions/${id}/audit`), enabled: !!id });
  const voidM = useMutation({
    mutationFn: () => api(`/transactions/${id}/void`, { body: { reason: "Voided by user" } }),
    onSuccess: () => {
      qc.invalidateQueries();
      setVoiding(false);
      toast.success("Transaction voided. It no longer counts toward totals.");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const unlink = useMutation({
    mutationFn: (allocation_id: string) => api("/reconciliation/unlink", { body: { allocation_id } }),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.success("Allocation removed");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const t = tx.data;
  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={t ? t.description || label(t.type) : "Transaction"} description={t ? `${label(t.type)} · ${date(t.occurred_on)}` : undefined} wide>
        {!t ? (
          <Skeleton className="h-48" />
        ) : (
          <div className="grid gap-5 text-sm">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Info k="Amount" v={money(t.amount, t.currency)} />
              <Info k="Counted in spending" v={money(t.effective_amount, t.currency)} hint={t.effective_amount !== t.amount ? "Part of this payment is counted through the bill it settles" : undefined} />
              <Info
                k="Category"
                v={t.category_name ?? "—"}
                hint={
                  t.category_source === "manual"
                    ? undefined
                    : t.category_source === "confirmed"
                      ? "Confirmed on the bill"
                      : (t.category_reasons ?? []).length
                        ? `Auto — found ${t.category_reasons!.slice(0, 3).join(", ")}`
                        : `Auto (${label(t.category_source)})`
                }
              />
              <Info k="Status" v={<span className="flex flex-wrap gap-1"><Badge>{label(t.status)}</Badge><ReconBadge status={t.reconciliation_status} /></span>} />
              <Info k="Merchant" v={t.merchant_name ?? "—"} />
              <Info k="Account" v={t.account_name ?? "—"} />
              <Info k="Payment method" v={label(t.payment_method)} />
              <Info k="Person" v={t.counterparty_name ?? "—"} />
            </div>
            {t.merged_into_id && (
              <p className="rounded-md bg-muted p-2">
                This record was merged as a duplicate into{" "}
                <Link className="text-primary hover:underline" to={`/transactions?open=${t.merged_into_id}`} onClick={onClose}>
                  another transaction
                </Link>{" "}
                and does not count toward totals.
              </p>
            )}
            {t.settlement && (
              <div className="rounded-md border p-3">
                <p className="font-medium">Bill settlement</p>
                <p className="text-muted-foreground">
                  Paid {money(t.settlement.paid_amount, t.currency)} of {money(t.settlement.bill_total, t.currency)} · Remaining {money(t.settlement.remaining_amount, t.currency)} · {label(t.settlement.settlement_status)}
                </p>
              </div>
            )}
            <section>
              <h4 className="mb-2 font-medium">Source records (evidence)</h4>
              <ul className="grid gap-2">
                {(t.sources ?? []).map((s) => (
                  <li key={s.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2">
                    <FileText className="size-4 text-muted-foreground" aria-hidden />
                    <Badge tone="primary">{label(s.source_type)}</Badge>
                    <Badge>{s.role}</Badge>
                    <span className="tabular">{money(s.amount, s.currency)}</span>
                    {s.allocated_amount !== "0.0000" && Number(s.allocated_amount) > 0 && <span className="text-muted-foreground">allocated {money(s.allocated_amount, s.currency)}</span>}
                    {(s.upi_txn_id || s.utr || s.bank_ref) && <span className="text-xs text-muted-foreground">ref {s.upi_txn_id || s.utr || s.bank_ref}</span>}
                    {s.invoice_number && <span className="text-xs text-muted-foreground">inv {s.invoice_number}</span>}
                    <ReconBadge status={s.reconciliation_status} />
                    {s.original_transaction_id !== s.transaction_id && <Badge tone="info">merged duplicate</Badge>}
                    {s.document_id && (
                      <Link className="ml-auto text-xs text-primary hover:underline" to={`/upload?doc=${s.document_id}`} onClick={onClose}>
                        View document
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </section>
            {(t.allocations ?? []).length > 0 && (
              <section>
                <h4 className="mb-2 font-medium">Payment allocations</h4>
                <ul className="grid gap-2">
                  {t.allocations!.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2">
                      <Link2 className="size-4 text-muted-foreground" aria-hidden />
                      <span>
                        {money(a.amount, t.currency)} of <em>{a.payment_description || "payment"}</em> → <em>{a.bill_description || "bill"}</em>
                      </span>
                      {canWrite && (
                        <Button className="ml-auto" variant="ghost" size="sm" loading={unlink.isPending} onClick={() => unlink.mutate(a.id)}>
                          Unlink
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {t.line_items && t.line_items.length > 0 && (
              <section>
                <h4 className="mb-2 font-medium">Line items</h4>
                <Table>
                  <THead>
                    <tr>
                      <TH>Item</TH>
                      <TH className="text-right">Qty</TH>
                      <TH className="text-right">Unit price</TH>
                      <TH className="text-right">Total</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {t.line_items.map((li) => (
                      <TR key={li.id}>
                        <TD>{li.name}</TD>
                        <TD className="text-right tabular">{li.quantity ? `${Number(li.quantity)} ${li.unit ?? ""}` : "—"}</TD>
                        <TD className="text-right tabular">{money(li.unit_price, t.currency)}</TD>
                        <TD className="text-right tabular">{money(li.line_total, t.currency)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </section>
            )}
            {t.notes && <p className="whitespace-pre-wrap rounded-md bg-muted p-2">{t.notes}</p>}
            <section>
              <h4 className="mb-2 font-medium">History</h4>
              <ol className="grid gap-1 text-xs text-muted-foreground">
                {(history.data ?? []).map((h, i) => (
                  <li key={i}>
                    {dateTime(h.at)} — {label(h.action)} {h.kind === "reconciliation" ? "(reconciliation)" : ""} {h.note ? `· ${h.note}` : ""}
                  </li>
                ))}
              </ol>
            </section>
            {canWrite && t.status === "active" && (
              <div className="flex flex-wrap justify-end gap-2">
                <Button variant="outline" onClick={() => setVoiding(true)}>
                  <Ban /> Void
                </Button>
                <Button onClick={() => setEditing(true)}>
                  <Pencil /> Edit
                </Button>
              </div>
            )}
          </div>
        )}
        {t && <TransactionDialog open={editing} onOpenChange={setEditing} tx={t} />}
        <ConfirmDialog
          open={voiding}
          onOpenChange={setVoiding}
          title="Void this transaction?"
          description="It will stop counting toward totals and any links to bills or payments will be removed. The record and its history are kept for auditing."
          confirmLabel="Void transaction"
          destructive
          loading={voidM.isPending}
          onConfirm={() => voidM.mutate()}
        />
      </DialogContent>
    </Dialog>
  );
}

function Info({ k, v, hint }: { k: string; v: React.ReactNode; hint?: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{k}</p>
      <div className="font-medium">{v}</div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function TransactionsPage() {
  const { household, canWrite } = useAuth();
  const [params, setParams] = useSearchParams();
  const [adding, setAdding] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const cats = useCategories();
  const accounts = useAccounts();
  const filters = {
    q: params.get("q") ?? "",
    month: params.get("month") ?? "",
    date_from: params.get("date_from") ?? "",
    date_to: params.get("date_to") ?? "",
    category_id: params.get("category_id") ?? "",
    type: params.get("type") ?? "",
    payment_method: params.get("payment_method") ?? "",
    account_id: params.get("account_id") ?? "",
    reconciliation_status: params.get("reconciliation_status") ?? "",
    min_amount: params.get("min_amount") ?? "",
    max_amount: params.get("max_amount") ?? "",
    tag: params.get("tag") ?? "",
    status: params.get("status") ?? "active",
  };
  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k === "open") {
      setParams(next, { replace: true });
      return; // opening or closing a transaction's details keeps the list where it is
    }
    next.delete("open");
    setParams(next, { replace: true });
    setPage(1);
  };
  const list = useQuery({
    queryKey: ["transactions", filters, page],
    queryFn: () => api<Page<Transaction>>(`/transactions${qs({ ...filters, page, page_size: 50 })}`),
    placeholderData: keepPreviousData,
  });
  const openId = params.get("open");
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;

  return (
    <>
      <PageHeader
        title="Transactions"
        description="Every expense, income and transfer. A bill and its payment appear as one transaction, so nothing is counted twice."
        actions={
          canWrite && (
            <>
              <Button variant="outline" asChild>
                <Link to="/upload?tab=statements">Import statement</Link>
              </Button>
              <Button onClick={() => setAdding(true)}>
                <Plus /> Add transaction
              </Button>
            </>
          )
        }
      />
      <Card className="mb-4 grid grid-cols-2 gap-2 p-3 sm:gap-3 sm:p-4 lg:grid-cols-6">
        <Input aria-label="Search" placeholder="Search description or notes" defaultValue={filters.q} onKeyDown={(e) => e.key === "Enter" && setFilter("q", (e.target as HTMLInputElement).value)} onBlur={(e) => setFilter("q", e.target.value)} className="col-span-2" />
        <Select aria-label="Month" value={filters.month} onChange={(e) => setFilter("month", e.target.value)}>
          <option value="">All months</option>
          {Array.from({ length: 24 }, (_, i) => shiftMonth(currentMonth(), -i))
            // A month older than the list (e.g. from a shared link) still shows as selected.
            .concat(filters.month && shiftMonth(currentMonth(), -23) > filters.month ? [filters.month] : [])
            .map((m) => (
              <option key={m} value={m}>
                {monthLabel(m)}
              </option>
            ))}
        </Select>
        <Select aria-label="Category" value={filters.category_id} onChange={(e) => setFilter("category_id", e.target.value)}>
          <option value="">All categories</option>
          {categoryOptions(cats.data).map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Type" value={filters.type} onChange={(e) => setFilter("type", e.target.value)}>
          <option value="">All types</option>
          {TX_TYPES.map((t) => (
            <option key={t} value={t}>
              {label(t)}
            </option>
          ))}
        </Select>
        <Select aria-label="Reconciliation status" value={filters.reconciliation_status} onChange={(e) => setFilter("reconciliation_status", e.target.value)}>
          <option value="">Any match status</option>
          {Object.keys(RECON_TONE).map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </Select>
        <details className="col-span-2 lg:col-span-6">
          <summary className="cursor-pointer text-sm text-muted-foreground">More filters</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
            <Input aria-label="From date" type="date" value={filters.date_from} onChange={(e) => setFilter("date_from", e.target.value)} />
            <Input aria-label="To date" type="date" value={filters.date_to} onChange={(e) => setFilter("date_to", e.target.value)} />
            <Select aria-label="Payment method" value={filters.payment_method} onChange={(e) => setFilter("payment_method", e.target.value)}>
              <option value="">Any payment method</option>
              {PAYMENT_METHODS.map((p) => (
                <option key={p} value={p}>
                  {label(p)}
                </option>
              ))}
            </Select>
            <Select aria-label="Account" value={filters.account_id} onChange={(e) => setFilter("account_id", e.target.value)}>
              <option value="">Any account</option>
              {(accounts.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
            <Input aria-label="Minimum amount" inputMode="decimal" placeholder="Min amount" defaultValue={filters.min_amount} onBlur={(e) => setFilter("min_amount", e.target.value)} />
            <Input aria-label="Maximum amount" inputMode="decimal" placeholder="Max amount" defaultValue={filters.max_amount} onBlur={(e) => setFilter("max_amount", e.target.value)} />
            <Input aria-label="Tag" placeholder="Tag" defaultValue={filters.tag} onBlur={(e) => setFilter("tag", e.target.value)} />
            <Select aria-label="Record status" value={filters.status} onChange={(e) => setFilter("status", e.target.value)}>
              <option value="active">Active</option>
              <option value="active,merged">Active + merged duplicates</option>
              <option value="voided">Voided</option>
              <option value="reversed">Reversed</option>
              <option value="all">All</option>
            </Select>
            <Button variant="ghost" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
              Clear filters
            </Button>
          </div>
        </details>
      </Card>
      {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      {list.isLoading ? (
        <div className="grid gap-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-11" />
          ))}
        </div>
      ) : list.data && list.data.items.length === 0 ? (
        <EmptyState title="No transactions found" description="Add a cash or UPI payment, upload a bill, or import a bank statement." action={canWrite && <Button onClick={() => setAdding(true)}>Add transaction</Button>} />
      ) : (
        list.data && (
          <Card>
            <Table>
              <THead>
                <tr>
                  <TH>Date</TH>
                  <TH>Description</TH>
                  <TH className="hidden md:table-cell">Category</TH>
                  <TH className="hidden lg:table-cell">Method</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Amount</TH>
                </tr>
              </THead>
              <TBody>
                {list.data.items.map((t) => (
                  <TR key={t.id} className={cn("cursor-pointer", t.status !== "active" && "opacity-60")} onClick={() => setFilter("open", t.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setFilter("open", t.id)}>
                    <TD className="whitespace-nowrap text-muted-foreground">{date(t.occurred_on)}</TD>
                    <TD>
                      <div className="font-medium">{t.description || t.merchant_name || label(t.type)}</div>
                      <div className="text-xs text-muted-foreground">
                        {label(t.type)}
                        {t.merchant_name && t.description !== t.merchant_name ? ` · ${t.merchant_name}` : ""}
                        {t.counterparty_name ? ` · ${t.counterparty_name}` : ""}
                      </div>
                    </TD>
                    <TD className="hidden md:table-cell">{t.category_name ?? "—"}</TD>
                    <TD className="hidden lg:table-cell">{label(t.payment_method)}</TD>
                    <TD>
                      {t.status !== "active" ? <Badge>{label(t.status)}</Badge> : <ReconBadge status={t.reconciliation_status} />}
                    </TD>
                    <TD className="text-right tabular whitespace-nowrap">
                      <div className={cn("font-medium", IN_TYPES.has(t.type) && "text-success")}>
                        {IN_TYPES.has(t.type) ? "+" : t.type === "transfer" || t.type === "credit_card_payment" ? "" : "−"}
                        {money(t.amount, t.currency)}
                      </div>
                      {t.effective_amount !== t.amount && t.status === "active" && <div className="text-xs text-muted-foreground">counted {money(t.effective_amount, t.currency)}</div>}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <div className="flex items-center justify-between border-t px-4 py-2 text-sm">
              <span className="text-muted-foreground">
                {list.data.total} transaction{list.data.total === 1 ? "" : "s"} · {household?.base_currency}
              </span>
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Previous page">
                  <ChevronLeft />
                </Button>
                <span>
                  {page} / {pages}
                </span>
                <Button variant="ghost" size="icon" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} aria-label="Next page">
                  <ChevronRight />
                </Button>
              </div>
            </div>
          </Card>
        )
      )}
      <AddTransactionDialog open={adding} onOpenChange={setAdding} />
      <TransactionDetail id={openId} onClose={() => setFilter("open", "")} />
    </>
  );
}

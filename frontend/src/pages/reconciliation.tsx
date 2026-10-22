import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, CircleSlash, Link2, Minus, Plus, RefreshCw, RotateCcw, Split, Unlink } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, Field, Input, PageHeader, Select, Skeleton, Stat, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { ReconBadge } from "@/pages/transactions";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, date, dateTime, label, money } from "@/lib/format";
import type { Match, Page, Source, Transaction } from "@/lib/queries";

const CONF_TONE = { high: "success", medium: "warning", low: "default" } as const;
const KIND_LABEL = { bill_payment: "Bill ↔ payment", duplicate: "Possible duplicate", refund: "Refund / reversal" };

function errMsg(e: unknown) {
  return e instanceof ApiError ? e.message : "Action failed";
}

function RecordPane({ title, s }: { title: string; s: Source }) {
  return (
    <div className="min-w-0 rounded-md border bg-muted/30 p-3 text-sm">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</span>
        <Badge tone="primary">{label(s.source_type)}</Badge>
        <ReconBadge status={s.reconciliation_status} />
      </div>
      <p className="truncate font-medium">{s.merchant || s.description || "—"}</p>
      {s.description && s.description !== s.merchant && <p className="truncate text-xs text-muted-foreground">{s.description}</p>}
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Amount</dt>
        <dd className="text-right font-semibold tabular">{money(s.amount, s.currency)}</dd>
        <dt className="text-muted-foreground">Date</dt>
        <dd className="text-right">
          {date(s.occurred_on)}
          {s.occurred_at ? ` ${new Date(s.occurred_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}` : ""}
        </dd>
        {Number(s.allocated_amount) > 0 && (
          <>
            <dt className="text-muted-foreground">{s.role === "bill" ? "Already paid" : "Already allocated"}</dt>
            <dd className="text-right tabular">{money(s.allocated_amount, s.currency)}</dd>
          </>
        )}
        {s.payment_method && (
          <>
            <dt className="text-muted-foreground">Method</dt>
            <dd className="text-right">{label(s.payment_method)}</dd>
          </>
        )}
        {(s.upi_txn_id || s.utr || s.bank_ref) && (
          <>
            <dt className="text-muted-foreground">Reference</dt>
            <dd className="truncate text-right font-mono">{s.upi_txn_id || s.utr || s.bank_ref}</dd>
          </>
        )}
        {s.invoice_number && (
          <>
            <dt className="text-muted-foreground">Invoice</dt>
            <dd className="truncate text-right font-mono">{s.invoice_number}</dd>
          </>
        )}
      </dl>
      <div className="mt-2 flex gap-3 text-xs">
        <Link className="text-primary hover:underline" to={`/transactions?open=${s.transaction_id}`}>
          Open transaction
        </Link>
        {s.document && (
          <Link className="text-primary hover:underline" to={`/upload?doc=${s.document.id}`}>
            {s.document.filename}
          </Link>
        )}
      </div>
    </div>
  );
}

export function MatchCard({ m, selectable, selected, onSelect }: { m: Match; selectable?: boolean; selected?: boolean; onSelect?: (v: boolean) => void }) {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const [amount, setAmount] = React.useState(m.suggested_amount ? String(Number(m.suggested_amount)) : "");
  const [confirming, setConfirming] = React.useState(false);
  const [unlinking, setUnlinking] = React.useState(false);
  const [showHistory, setShowHistory] = React.useState(false);
  const cur = m.a.currency;
  const done = () => qc.invalidateQueries();
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api(path, { body: body ?? {}, idempotent: path.endsWith("/confirm") }),
    onSuccess: (_d, v) => {
      done();
      setConfirming(false);
      setUnlinking(false);
      toast.success(
        v.path.endsWith("/confirm")
          ? m.kind === "bill_payment"
            ? "Linked. The payment now counts through the bill, so the purchase is counted once."
            : m.kind === "duplicate"
              ? "Merged. The duplicate no longer counts toward totals (it stays traceable)."
              : "Refund linked to the original purchase."
          : v.path.endsWith("/reject")
            ? "Kept as separate records."
            : v.path.endsWith("/unlink")
              ? "Unlinked. Both records count independently again."
              : "Reopened for review.",
      );
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const history = useQuery({ queryKey: ["match", m.id], queryFn: () => api<Match>(`/reconciliation/${m.id}`), enabled: showHistory });
  const diff = Number(m.amount_difference);

  return (
    <Card className={cn("p-4", m.conflict && "border-destructive/50")}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {selectable && <input type="checkbox" className="size-4 accent-[var(--primary)]" checked={selected} onChange={(e) => onSelect?.(e.target.checked)} aria-label="Select for bulk confirm" />}
        <span className="font-medium">{KIND_LABEL[m.kind]}</span>
        <Badge tone={CONF_TONE[m.confidence]}>
          {label(m.confidence)} confidence · {m.score}
        </Badge>
        {m.conflict && <Badge tone="danger">Conflict — needs review</Badge>}
        {m.status !== "suggested" && <Badge tone={m.status === "confirmed" ? "success" : "default"}>{label(m.status)}</Badge>}
        {m.origin === "manual" && <Badge>Manual</Badge>}
      </div>
      <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr] md:items-stretch">
        <RecordPane title={m.a_label} s={m.a} />
        <div className="flex flex-row items-center justify-center gap-4 text-center text-xs md:flex-col md:gap-2" aria-label="Comparison">
          <ArrowRight className="hidden size-4 text-muted-foreground md:block" aria-hidden />
          <div>
            <p className="text-muted-foreground">Amount diff</p>
            <p className={cn("font-semibold tabular", diff !== 0 && "text-warning")}>{diff === 0 ? "None" : money(m.amount_difference, cur)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Date diff</p>
            <p className="font-semibold">{m.date_difference_days === 0 ? "Same day" : `${m.date_difference_days} day${m.date_difference_days === 1 ? "" : "s"}`}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Merchant</p>
            <p className="font-semibold">{Math.round(m.merchant_similarity * 100)}% similar</p>
          </div>
        </div>
        <RecordPane title={m.b_label} s={m.b} />
      </div>
      <div className="mt-3">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Why these were matched</p>
        <ul className="grid gap-1 text-sm">
          {m.reasons.map((r, i) => (
            <li key={i} className="flex items-start gap-2">
              {r.points > 0 ? <Plus className="mt-0.5 size-3.5 text-success" aria-label="supports match" /> : r.points < 0 ? <Minus className="mt-0.5 size-3.5 text-destructive" aria-label="weakens match" /> : <span className="mt-0.5 size-3.5 text-center text-muted-foreground">·</span>}
              <span>{r.text}</span>
              {r.points !== 0 && <span className="ml-auto text-xs text-muted-foreground tabular">{r.points > 0 ? `+${r.points}` : r.points}</span>}
            </li>
          ))}
        </ul>
      </div>
      {canWrite && (
        <div className="mt-4 flex flex-wrap items-end gap-2 border-t pt-3">
          {m.status === "suggested" && (
            <>
              <Button size="sm" onClick={() => setConfirming(true)}>
                <CheckCircle2 /> {m.kind === "bill_payment" ? "Link payment to bill" : m.kind === "duplicate" ? "Same transaction — merge" : "Link refund"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                loading={act.isPending}
                title="These are different purchases: keep both, and don't suggest this pair again"
                onClick={() => act.mutate({ path: `/reconciliation/${m.id}/reject`, body: { separate_purchases: true } })}
              >
                <CircleSlash /> Not a match — keep separate
              </Button>
            </>
          )}
          {m.status === "confirmed" && (
            <Button size="sm" variant="outline" onClick={() => setUnlinking(true)}>
              <Unlink /> Unlink
            </Button>
          )}
          {m.status !== "suggested" && (
            <Button size="sm" variant="ghost" loading={act.isPending} onClick={() => act.mutate({ path: `/reconciliation/${m.id}/reopen` })}>
              <RotateCcw /> Reopen
            </Button>
          )}
          <Button size="sm" variant="link" className="ml-auto" onClick={() => setShowHistory((s) => !s)}>
            {showHistory ? "Hide history" : "History"}
          </Button>
        </div>
      )}
      {showHistory && (
        <ol className="mt-2 grid gap-1 text-xs text-muted-foreground">
          {(history.data?.history ?? []).length === 0 && <li>No decisions recorded yet.</li>}
          {(history.data?.history ?? []).map((h, i) => (
            <li key={i}>
              {dateTime(h.at)} — {label(h.action)}
              {h.note ? ` · ${h.note}` : ""}
            </li>
          ))}
        </ol>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={m.kind === "bill_payment" ? "Link this payment to the bill?" : m.kind === "duplicate" ? "Merge these duplicate records?" : "Link this refund?"}
        description={
          m.kind === "bill_payment" ? (
            <>The bill is counted once; the linked part of the payment stops counting separately. Both records stay visible and you can unlink later.</>
          ) : m.kind === "duplicate" ? (
            <>The second record is treated as another copy of the first and stops counting. Nothing is deleted; you can unlink later.</>
          ) : (
            <>The credit is recorded as a refund of the original purchase and reduces net spending.</>
          )
        }
        confirmLabel="Confirm"
        loading={act.isPending}
        onConfirm={() => act.mutate({ path: `/reconciliation/${m.id}/confirm`, body: m.kind === "bill_payment" && amount ? { amount } : {} })}
      >
        {m.kind === "bill_payment" && (
          <Field label="Amount to allocate" htmlFor={`amt-${m.id}`} hint={diff !== 0 ? `Records differ by ${money(m.amount_difference, cur)}. Any unallocated remainder of the payment keeps counting as spending (e.g. a tip).` : undefined}>
            <Input id={`amt-${m.id}`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
        )}
        {m.kind === "refund" && Number(m.a.amount) === Number(m.b.amount) && (
          <Button variant="outline" size="sm" onClick={() => act.mutate({ path: `/reconciliation/${m.id}/confirm`, body: { as_reversal: true } })}>
            It's a reversed (failed) payment instead
          </Button>
        )}
      </ConfirmDialog>
      <ConfirmDialog
        open={unlinking}
        onOpenChange={setUnlinking}
        title="Unlink these records?"
        description="Both records will count independently again. The decision is recorded in the audit history."
        confirmLabel="Unlink"
        destructive
        loading={act.isPending}
        onConfirm={() => act.mutate({ path: "/reconciliation/unlink", body: { match_id: m.id } })}
      />
    </Card>
  );
}

function SourceRow({ s, action }: { s: Source; action?: React.ReactNode }) {
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-md border bg-card p-3 text-sm">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{s.merchant || s.description || "—"}</p>
        <p className="text-xs text-muted-foreground">
          {date(s.occurred_on)} · {label(s.source_type)} · {s.role}
          {s.document ? ` · ${s.document.filename}` : ""}
        </p>
      </div>
      <div className="text-right">
        <p className="font-medium tabular">{money(s.amount, s.currency)}</p>
        {Number(s.allocated_amount) > 0 && (
          <p className="text-xs text-muted-foreground">
            {s.role === "bill" ? "paid" : "allocated"} {money(s.allocated_amount, s.currency)} · {s.role === "bill" ? "remaining" : "unallocated"} {money(s.available_amount, s.currency)}
          </p>
        )}
      </div>
      <ReconBadge status={s.reconciliation_status} />
      {action}
      <Link className="text-xs text-primary hover:underline" to={`/transactions?open=${s.transaction_id}`}>
        Open
      </Link>
    </li>
  );
}

/** Pick counterpart transactions and link them (manual match) or split a payment across bills. */
function LinkDialog({ source, onClose }: { source: Source | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [q, setQ] = React.useState("");
  const [rows, setRows] = React.useState<{ tx: Transaction; amount: string }[]>([]);
  const isPayment = source?.role === "payment";
  const candidates = useQuery({
    queryKey: ["link-candidates", source?.id, q],
    queryFn: () => api<Page<Transaction>>(`/transactions${qs({ q, type: "expense", page_size: 30, source_type: isPayment ? "receipt,invoice,manual" : "statement_row,manual,upi_screenshot" })}`),
    enabled: !!source,
  });
  React.useEffect(() => setRows([]), [source?.id]);
  const total = rows.reduce((acc, r) => acc + Math.round(Number(r.amount || 0) * 100), 0);
  const available = source ? Math.round(Number(source.available_amount) * 100) : 0;
  const save = useMutation({
    mutationFn: async () => {
      if (!source) return;
      if (isPayment && rows.length > 1) {
        return api("/reconciliation/allocate-payment", {
          idempotent: true,
          body: { payment_source_id: source.id, allocations: rows.map((r) => ({ bill_transaction_id: r.tx.id, amount: r.amount })) },
        });
      }
      const r = rows[0];
      return api("/reconciliation/manual-match", { idempotent: true, body: { a_source_id: source.id, b_transaction_id: r.tx.id, amount: r.amount || undefined } });
    },
    onSuccess: () => {
      qc.invalidateQueries();
      toast.success("Records linked");
      onClose();
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  return (
    <Dialog open={!!source} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        wide
        title={isPayment ? "Link payment to bill(s)" : "Link bill to a payment"}
        description={isPayment ? "Choose one bill, or several to split this payment (one payment covering multiple bills)." : "Choose the payment that settled this bill."}
      >
        {source && (
          <div className="grid gap-4">
            <SourceRow s={source} />
            <Input placeholder="Search transactions…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search transactions" />
            <ul className="grid max-h-64 gap-1 overflow-y-auto">
              {candidates.isLoading && <Skeleton className="h-10" />}
              {(candidates.data?.items ?? [])
                .filter((t) => t.id !== source.transaction_id && t.status === "active")
                .map((t) => {
                  const chosen = rows.some((r) => r.tx.id === t.id);
                  return (
                    <li key={t.id}>
                      <button
                        type="button"
                        className={cn("flex w-full items-center gap-2 rounded-md border p-2 text-left text-sm hover:bg-muted cursor-pointer", chosen && "border-primary bg-accent")}
                        onClick={() => setRows((rs) => (chosen ? rs.filter((r) => r.tx.id !== t.id) : isPayment ? [...rs, { tx: t, amount: "" }] : [{ tx: t, amount: "" }]))}
                        aria-pressed={chosen}
                      >
                        <span className="flex-1 truncate">
                          {t.description || t.merchant_name} <span className="text-muted-foreground">· {date(t.occurred_on)}</span>
                        </span>
                        <ReconBadge status={t.reconciliation_status} />
                        <span className="tabular">{money(t.amount, t.currency)}</span>
                      </button>
                    </li>
                  );
                })}
            </ul>
            {rows.length > 0 && (
              <div className="grid gap-2">
                <p className="text-sm font-medium">Allocation</p>
                {rows.map((r, i) => (
                  <div key={r.tx.id} className="flex items-center gap-2 text-sm">
                    <span className="flex-1 truncate">{r.tx.description || r.tx.merchant_name}</span>
                    <Input
                      className="w-36"
                      inputMode="decimal"
                      placeholder={rows.length === 1 ? "Auto" : "Amount"}
                      aria-label={`Amount for ${r.tx.description}`}
                      value={r.amount}
                      onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))}
                    />
                  </div>
                ))}
                {isPayment && (
                  <p className={cn("text-xs", total > available ? "text-destructive" : "text-muted-foreground")}>
                    Allocating {money((total / 100).toFixed(2), source.currency)} of {money(source.available_amount, source.currency)} available
                    {total > available ? " — exceeds the payment" : total < available && total > 0 ? ` · ${money(((available - total) / 100).toFixed(2), source.currency)} stays unallocated` : ""}
                  </p>
                )}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button disabled={rows.length === 0 || (isPayment && rows.length > 1 && (total <= 0 || total > available || rows.some((r) => !r.amount)))} loading={save.isPending} onClick={() => save.mutate()}>
                {rows.length > 1 ? <Split /> : <Link2 />} Link
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ReconciliationPage() {
  const qc = useQueryClient();
  const { household, canWrite } = useAuth();
  const cur = household?.base_currency ?? "INR";
  const [confidence, setConfidence] = React.useState("");
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [bulkOpen, setBulkOpen] = React.useState(false);
  const [linking, setLinking] = React.useState<Source | null>(null);
  const summary = useQuery({ queryKey: ["recon-summary"], queryFn: () => api("/reconciliation/summary") });
  const queues = useQuery({ queryKey: ["recon-queues"], queryFn: () => api("/reconciliation/queues") });
  const recalc = useMutation({
    mutationFn: () => api("/reconciliation/recalculate", { method: "POST" }),
    onSuccess: (r: any) => {
      qc.invalidateQueries();
      toast.success(`Recalculated ${r.transactions_recomputed} transactions${r.amount_drift_corrected.length ? `; corrected ${r.amount_drift_corrected.length}` : ""}.`);
    },
    onError: (e) => toast.error(errMsg(e)),
  });
  const bulk = useMutation({
    mutationFn: () => api("/reconciliation/bulk-confirm", { body: { match_ids: [...selected], confirm: true } }),
    onSuccess: (r: any) => {
      qc.invalidateQueries();
      setSelected(new Set());
      setBulkOpen(false);
      const failed = r.results.filter((x: any) => !x.ok);
      if (failed.length) toast.warning(`${r.confirmed} linked; ${failed.length} could not be linked: ${failed[0].error}`);
      else toast.success(`${r.confirmed} matches linked`);
    },
    onError: (e) => toast.error(errMsg(e)),
  });

  const s = summary.data;
  const qd = queues.data;
  const suggestions: Match[] = qd ? [...qd.conflicting_references, ...qd.suggested_bill_payments, ...qd.possible_duplicates, ...qd.possible_refunds] : [];
  const filtered = suggestions.filter((m) => !confidence || m.confidence === confidence);
  const highIds = filtered.filter((m) => m.confidence === "high" && !m.conflict).map((m) => m.id);

  const sourceList = (items: Source[], empty: string, linkable = true) =>
    items.length === 0 ? (
      <EmptyState title={empty} />
    ) : (
      <ul className="grid gap-2">
        {items.map((x) => (
          <SourceRow
            key={x.id}
            s={x}
            action={
              canWrite &&
              linkable && (
                <Button size="sm" variant="outline" onClick={() => setLinking(x)}>
                  <Link2 /> Link…
                </Button>
              )
            }
          />
        ))}
      </ul>
    );

  return (
    <>
      <PageHeader
        title="Duplicates & Reconciliation"
        description="Records that may describe the same purchase. Nothing is merged until you confirm, and every decision can be undone."
        actions={
          canWrite && (
            <Button variant="outline" loading={recalc.isPending} onClick={() => recalc.mutate()}>
              <RefreshCw /> Recalculate
            </Button>
          )
        }
      />
      <section className="stagger mb-6 grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-5" aria-label="Reconciliation summary">
        {!s ? (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24" />)
        ) : (
          <>
            <Stat label="To review" value={s.suggestions.high + s.suggestions.medium} sub={`${s.suggestions.high} high · ${s.suggestions.medium} medium · ${s.suggestions.low} low`} />
            <Stat label="Conflicts" value={s.conflicts} sub="Same reference, different details" tone={s.conflicts ? "negative" : undefined} />
            <Stat label="Double counting prevented" value={money(s.double_counting_prevented, cur)} sub="Linked payments + merged duplicates" />
            <Stat label="Unallocated payments" value={money(s.unallocated_payment_balance, cur)} sub="Partially linked payment remainder" />
            <Stat label="Completion" value={`${Math.round(s.completion_rate * 100)}%`} sub={`${s.duplicate_uploads_blocked} duplicate upload(s) blocked`} />
          </>
        )}
      </section>
      {queues.isError && <ErrorState error={queues.error} onRetry={() => queues.refetch()} />}
      {!qd ? (
        <Skeleton className="h-64" />
      ) : (
        <Tabs defaultValue="suggested">
          <TabsList className="mb-4">
            <TabsTrigger value="suggested">Suggested ({suggestions.length})</TabsTrigger>
            <TabsTrigger value="linked">Linked ({qd.bills_with_payments.length})</TabsTrigger>
            <TabsTrigger value="no-receipt">Payments without receipts ({qd.payments_without_receipts.length})</TabsTrigger>
            <TabsTrigger value="no-payment">Receipts without payments ({qd.receipts_without_payments.length})</TabsTrigger>
            <TabsTrigger value="partial">Partially paid ({qd.partially_paid_bills.length})</TabsTrigger>
            <TabsTrigger value="unallocated">Unallocated ({qd.unallocated_payments.length})</TabsTrigger>
            <TabsTrigger value="statement">Unmatched statement ({qd.unmatched_statement_entries.length})</TabsTrigger>
            <TabsTrigger value="uploads">Duplicate uploads ({qd.duplicate_uploads.length})</TabsTrigger>
          </TabsList>
          <TabsContent value="suggested" className="grid gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Select aria-label="Confidence" className="w-48" value={confidence} onChange={(e) => setConfidence(e.target.value)}>
                <option value="">All confidence levels</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </Select>
              {canWrite && highIds.length > 0 && (
                <>
                  <Button variant="outline" size="sm" onClick={() => setSelected(new Set(highIds))}>
                    Select all high confidence ({highIds.length})
                  </Button>
                  <Button size="sm" disabled={selected.size === 0} onClick={() => setBulkOpen(true)}>
                    <CheckCircle2 /> Confirm selected ({selected.size})
                  </Button>
                </>
              )}
            </div>
            {filtered.length === 0 ? (
              <EmptyState title="Nothing to review" description="When a bill and a payment (or two copies of the same payment) look alike, they'll appear here with the reasons." />
            ) : (
              filtered.map((m) => (
                <MatchCard
                  key={m.id}
                  m={m}
                  selectable={canWrite && m.confidence === "high" && !m.conflict}
                  selected={selected.has(m.id)}
                  onSelect={(v) =>
                    setSelected((prev) => {
                      const n = new Set(prev);
                      if (v) n.add(m.id);
                      else n.delete(m.id);
                      return n;
                    })
                  }
                />
              ))
            )}
          </TabsContent>
          <TabsContent value="linked" className="grid gap-3">
            {qd.bills_with_payments.length === 0 ? <EmptyState title="No linked bills yet" /> : qd.bills_with_payments.map((m: Match) => <MatchCard key={m.id} m={m} />)}
            {qd.over_or_underpaid.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Over- or under-paid links</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-2 text-sm">
                  {qd.over_or_underpaid.map((m: Match) => (
                    <p key={m.id}>
                      {m.a.merchant || m.a.description}: bill {money(m.a.amount, m.a.currency)}, payment {money(m.b.amount, m.b.currency)} (difference {money(m.amount_difference, m.a.currency)})
                    </p>
                  ))}
                </CardContent>
              </Card>
            )}
          </TabsContent>
          <TabsContent value="no-receipt">{sourceList(qd.payments_without_receipts, "Every payment has a receipt or is fine on its own")}</TabsContent>
          <TabsContent value="no-payment">{sourceList(qd.receipts_without_payments, "No receipts waiting for a payment")}</TabsContent>
          <TabsContent value="partial">{sourceList(qd.partially_paid_bills, "No partially paid bills")}</TabsContent>
          <TabsContent value="unallocated">{sourceList(qd.unallocated_payments, "No payments with unallocated balances")}</TabsContent>
          <TabsContent value="statement">{sourceList(qd.unmatched_statement_entries, "All imported statement entries are matched")}</TabsContent>
          <TabsContent value="uploads">
            {qd.duplicate_uploads.length === 0 ? (
              <EmptyState title="No duplicate uploads" description="Uploading the same file twice is detected by its SHA-256 hash and blocked." />
            ) : (
              <ul className="grid gap-2">
                {qd.duplicate_uploads.map((d: any) => (
                  <li key={d.id} className="flex flex-wrap items-center gap-2 rounded-md border bg-card p-3 text-sm">
                    <span className="flex-1">
                      <strong>{d.attempted_filename || "Statement row"}</strong> — {d.kind === "document_hash" ? "identical to an already uploaded file" : "row already imported"} · {dateTime(d.created_at)}
                    </span>
                    {d.existing_document_id && (
                      <Link className="text-primary hover:underline" to={`/upload?doc=${d.existing_document_id}`}>
                        View original
                      </Link>
                    )}
                    {canWrite && (
                      <Button size="sm" variant="ghost" onClick={() => api(`/reconciliation/duplicate-uploads/${d.id}/dismiss`, { method: "POST" }).then(() => qc.invalidateQueries())}>
                        Dismiss
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>
        </Tabs>
      )}
      <ConfirmDialog
        open={bulkOpen}
        onOpenChange={setBulkOpen}
        title={`Confirm ${selected.size} high-confidence matches?`}
        description="Each pair will be linked so the purchase is counted once. Each decision is recorded and can be unlinked individually."
        confirmLabel="Link all"
        loading={bulk.isPending}
        onConfirm={() => bulk.mutate()}
      />
      <LinkDialog source={linking} onClose={() => setLinking(null)} />
    </>
  );
}

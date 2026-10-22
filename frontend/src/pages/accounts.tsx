import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Pencil, Plus, ShieldCheck } from "lucide-react";
import * as React from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, Card, EmptyState, Field, Input, PageHeader, Select, Skeleton } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ACCOUNT_TYPES, label, money, today } from "@/lib/format";
import { type Account, useAccounts } from "@/lib/queries";

export function AccountDialog({ open, onOpenChange, account, defaultType = "bank" }: { open: boolean; onOpenChange: (o: boolean) => void; account?: Account; defaultType?: string }) {
  const qc = useQueryClient();
  const { household } = useAuth();
  const [form, setForm] = React.useState<Record<string, string>>({});
  React.useEffect(() => {
    setForm(
      account
        ? {
            name: account.name,
            type: account.type,
            currency: account.currency,
            opening_balance: String(Number(account.opening_balance)),
            opening_balance_date: account.opening_balance_date ?? "",
            institution: account.institution,
            masked_number: account.masked_number,
            upi_handle: account.upi_handle,
            credit_limit: account.credit_limit ? String(Number(account.credit_limit)) : "",
            statement_day: account.statement_day ? String(account.statement_day) : "",
            due_day: account.due_day ? String(account.due_day) : "",
          }
        : { name: "", type: defaultType, currency: household?.base_currency ?? "INR", opening_balance: "0", opening_balance_date: today(), institution: "", masked_number: "", upi_handle: "", credit_limit: "", statement_day: "", due_day: "" },
    );
  }, [account, open, household, defaultType]);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const isCard = form.type === "credit_card";
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { ...form, opening_balance_date: form.opening_balance_date || null };
      if (isCard) {
        body.credit_limit = form.credit_limit || null;
        body.statement_day = form.statement_day ? Number(form.statement_day) : null;
        body.due_day = form.due_day ? Number(form.due_day) : null;
      } else {
        delete body.credit_limit;
        delete body.statement_day;
        delete body.due_day;
      }
      if (account) {
        delete body.type;
        delete body.currency;
        return api(`/accounts/${account.id}`, { method: "PATCH", body });
      }
      return api("/accounts", { body });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["balances"] });
      qc.invalidateQueries({ queryKey: ["cards"] });
      onOpenChange(false);
      toast.success("Account saved");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Save failed"),
  });
  const lastFourError = form.masked_number && !/^\d{0,4}$/.test(form.masked_number) ? "Only the last 4 digits" : undefined;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={account ? "Edit account" : "Add account"} description="Never enter PINs, passwords, CVV or full card numbers — SmartSpend doesn't need them.">
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!lastFourError) save.mutate();
          }}
        >
          <Field label="Name" htmlFor="acc-name">
            <Input id="acc-name" required value={form.name ?? ""} onChange={set("name")} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type" htmlFor="acc-type">
              <Select id="acc-type" value={form.type} onChange={set("type")} disabled={!!account}>
                {ACCOUNT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {label(t)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Currency" htmlFor="acc-cur">
              <Input id="acc-cur" maxLength={3} value={form.currency ?? ""} disabled={!!account} onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value.toUpperCase() }))} />
            </Field>
            <Field label="Opening balance" htmlFor="acc-ob" hint={form.type === "credit_card" ? "Use a negative number for an amount owed" : undefined}>
              <Input id="acc-ob" inputMode="decimal" value={form.opening_balance ?? ""} onChange={set("opening_balance")} />
            </Field>
            <Field label="As of" htmlFor="acc-obd">
              <Input id="acc-obd" type="date" value={form.opening_balance_date ?? ""} onChange={set("opening_balance_date")} />
            </Field>
            <Field label="Institution" htmlFor="acc-inst">
              <Input id="acc-inst" value={form.institution ?? ""} onChange={set("institution")} />
            </Field>
            <Field label="Last 4 digits" htmlFor="acc-last4" error={lastFourError}>
              <Input id="acc-last4" inputMode="numeric" maxLength={4} value={form.masked_number ?? ""} onChange={set("masked_number")} />
            </Field>
          </div>
          {isCard && (
            <div className="grid grid-cols-3 gap-3 rounded-md border p-3">
              <Field label="Credit limit" htmlFor="acc-limit">
                <Input id="acc-limit" inputMode="decimal" value={form.credit_limit ?? ""} onChange={set("credit_limit")} />
              </Field>
              <Field label="Statement day" htmlFor="acc-sday" hint="Day of month">
                <Input id="acc-sday" inputMode="numeric" value={form.statement_day ?? ""} onChange={set("statement_day")} />
              </Field>
              <Field label="Due day" htmlFor="acc-dday" hint="Day of month">
                <Input id="acc-dday" inputMode="numeric" value={form.due_day ?? ""} onChange={set("due_day")} />
              </Field>
            </div>
          )}
          {(form.type === "upi" || form.type === "bank") && (
            <Field label="UPI ID (optional)" htmlFor="acc-upi">
              <Input id="acc-upi" placeholder="name@bank" value={form.upi_handle ?? ""} onChange={set("upi_handle")} />
            </Field>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              Save
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AccountsPage() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const accounts = useAccounts();
  const balances = useQuery({ queryKey: ["balances"], queryFn: () => api<{ account_id: string; balance: string; currency: string }[]>("/accounts-balances") });
  const [editing, setEditing] = React.useState<Account | undefined>();
  const [open, setOpen] = React.useState(false);
  const [archiving, setArchiving] = React.useState<Account | null>(null);
  const archive = useMutation({
    mutationFn: (a: Account) => api(`/accounts/${a.id}`, { method: "DELETE" }),
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setArchiving(null);
      toast.success(r.archived ? "Account archived (it has history)" : "Account deleted");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });
  const bal = new Map((balances.data ?? []).map((b) => [b.account_id, b]));
  return (
    <>
      <PageHeader
        title="Accounts"
        description="Balances are the opening balance plus reconciled money movements. Linked receipts don't double-debit an account."
        actions={
          canWrite && (
            <Button
              onClick={() => {
                setEditing(undefined);
                setOpen(true);
              }}
            >
              <Plus /> Add account
            </Button>
          )
        }
      />
      <p className="mb-4 flex items-center gap-2 text-sm text-muted-foreground">
        <ShieldCheck className="size-4" aria-hidden /> SmartSpend never stores UPI PINs, banking passwords or card security codes.
      </p>
      {accounts.isLoading ? (
        <Skeleton className="h-40" />
      ) : (accounts.data ?? []).length === 0 ? (
        <EmptyState title="No accounts" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {accounts.data!.map((a) => (
            <Card key={a.id} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{a.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {label(a.type)}
                    {a.institution ? ` · ${a.institution}` : ""}
                    {a.masked_number ? ` · ••${a.masked_number}` : ""}
                  </p>
                </div>
                <Badge>{a.currency}</Badge>
              </div>
              <div className="mt-3 text-2xl font-semibold tabular">{bal.get(a.id) ? money(bal.get(a.id)!.balance, a.currency) : <Skeleton className="h-7 w-28" />}</div>
              <p className="text-xs text-muted-foreground">Opening {money(a.opening_balance, a.currency)}</p>
              <div className="mt-3 flex gap-1">
                <Button variant="ghost" size="sm" asChild>
                  <Link to={`/transactions?account_id=${a.id}`}>Transactions</Link>
                </Button>
                {canWrite && (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditing(a);
                        setOpen(true);
                      }}
                    >
                      <Pencil /> Edit
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setArchiving(a)}>
                      <Archive /> Remove
                    </Button>
                  </>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      <AccountDialog open={open} onOpenChange={setOpen} account={editing} />
      <ConfirmDialog
        open={!!archiving}
        onOpenChange={(o) => !o && setArchiving(null)}
        title={`Remove ${archiving?.name}?`}
        description="Accounts with transactions are archived (history is kept). Empty accounts are deleted."
        confirmLabel="Remove"
        destructive
        loading={archive.isPending}
        onConfirm={() => archiving && archive.mutate(archiving)}
      />
    </>
  );
}

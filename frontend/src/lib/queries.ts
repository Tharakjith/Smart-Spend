import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type Category = { id: string; name: string; parent_id: string | null; kind: string; is_system: boolean; is_fixed: boolean; color: string; icon: string; is_archived: boolean };
export type Account = {
  id: string;
  name: string;
  type: string;
  currency: string;
  opening_balance: string;
  opening_balance_date: string | null;
  institution: string;
  masked_number: string;
  upi_handle: string;
  is_archived: boolean;
  credit_limit: string | null;
  statement_day: number | null;
  due_day: number | null;
};
export type Counterparty = { id: string; name: string; email: string; phone: string; upi_id: string; notes: string };

export type Source = {
  id: string;
  transaction_id: string;
  original_transaction_id: string;
  source_type: string;
  role: "bill" | "payment";
  direction: string;
  amount: string;
  allocated_amount: string;
  available_amount: string;
  currency: string;
  occurred_on: string;
  occurred_at: string | null;
  merchant: string;
  description: string;
  payment_method: string | null;
  upi_txn_id: string | null;
  utr: string | null;
  bank_ref: string | null;
  invoice_number: string | null;
  order_id: string | null;
  document_id: string | null;
  statement_row_id: string | null;
  status: string;
  reconciliation_status: string;
  item_names: string[];
  transaction?: { id: string; type: string; description: string; amount: string; effective_amount: string; status: string; reconciliation_status: string };
  document?: { id: string; filename: string; status: string } | null;
};

export type Transaction = {
  id: string;
  type: string;
  occurred_on: string;
  occurred_at: string | null;
  description: string;
  amount: string;
  effective_amount: string;
  cash_amount: string;
  currency: string;
  category_id: string | null;
  category_name: string | null;
  category_source: string;
  category_reasons?: string[];
  merchant_id: string | null;
  merchant_name: string | null;
  counterparty_id: string | null;
  counterparty_name: string | null;
  account_id: string | null;
  account_name: string | null;
  to_account_id: string | null;
  payment_method: string | null;
  notes: string;
  tags: string[];
  status: string;
  merged_into_id: string | null;
  related_transaction_id: string | null;
  reconciliation_status: string;
  review_status: string;
  is_recurring: boolean;
  version: number;
  sources?: Source[];
  line_items?: { id: string; name: string; quantity: string | null; unit: string | null; unit_price: string | null; line_total: string | null; category_id: string | null }[];
  settlement?: { bill_total: string; paid_amount: string; remaining_amount: string; settlement_status: string } | null;
  allocations?: Allocation[];
  merged_duplicates?: string[];
};

export type Allocation = {
  id: string;
  match_id: string | null;
  payment_source_id: string;
  payment_transaction_id: string;
  payment_description: string;
  bill_source_id: string;
  bill_transaction_id: string;
  bill_description: string;
  amount: string;
  status: string;
};

export type Match = {
  id: string;
  kind: "bill_payment" | "duplicate" | "refund";
  status: string;
  origin: string;
  score: number;
  confidence: "high" | "medium" | "low";
  conflict: boolean;
  reasons: { code: string; points: number; text: string }[];
  amount_difference: string;
  date_difference_days: number;
  merchant_similarity: number;
  suggested_amount: string | null;
  a_label: string;
  b_label: string;
  a: Source;
  b: Source;
  note: string;
  decided_at: string | null;
  available_actions: string[];
  allocations?: Allocation[];
  history?: { action: string; at: string; note: string; after: Record<string, unknown> | null }[];
};

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export const useCategories = () => useQuery({ queryKey: ["categories"], queryFn: () => api<Category[]>("/categories"), staleTime: 60_000 });
export const useAccounts = () => useQuery({ queryKey: ["accounts"], queryFn: () => api<Account[]>("/accounts"), staleTime: 60_000 });
export const useCounterparties = () => useQuery({ queryKey: ["counterparties"], queryFn: () => api<Counterparty[]>("/counterparties"), staleTime: 60_000 });

export function categoryOptions(cats: Category[] | undefined, kind?: string) {
  if (!cats) return [];
  const active = cats.filter((c) => !c.is_archived && (!kind || c.kind === kind));
  const parents = active.filter((c) => !c.parent_id).sort((a, b) => a.name.localeCompare(b.name));
  const out: { id: string; label: string }[] = [];
  for (const p of parents) {
    out.push({ id: p.id, label: p.name });
    for (const c of active.filter((x) => x.parent_id === p.id).sort((a, b) => a.name.localeCompare(b.name))) out.push({ id: c.id, label: `   ${c.name}` });
  }
  return out;
}

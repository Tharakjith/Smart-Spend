import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const fmtCache = new Map<string, Intl.NumberFormat>();

/** Formats a decimal string exactly (Intl accepts numeric strings without converting through floats). */
export function money(value: string | number | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined || value === "") return "—";
  const key = currency;
  let f = fmtCache.get(key);
  if (!f) {
    f = new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: currency === "JPY" ? 0 : 2 });
    fmtCache.set(key, f);
  }
  return f.format(value as unknown as number);
}

/** Numbers for charts only. Never used for arithmetic that is displayed as a total. */
export const chartNum = (v: string | number | null | undefined) => (v === null || v === undefined ? 0 : Number(v));

export function date(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function currentMonth(): string {
  return today().slice(0, 7);
}

export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

const ACRONYMS: Record<string, string> = { upi: "UPI", utr: "UTR", pdf: "PDF", csv: "CSV", xlsx: "XLSX", gst: "GST", ocr: "OCR" };

export const label = (s: string | null | undefined) =>
  s
    ? s
        .replace(/_/g, " ")
        .replace(/\b[a-z]+\b/g, (w) => ACRONYMS[w] ?? w)
        .replace(/^\w/, (c) => c.toUpperCase())
    : "—";

export const TX_TYPES = [
  "expense",
  "income",
  "transfer",
  "refund",
  "loan_given",
  "loan_received",
  "loan_repayment_paid",
  "loan_repayment_received",
  "reimbursement_paid",
  "reimbursement_received",
  "credit_card_payment",
] as const;

export const PAYMENT_METHODS = ["cash", "upi", "debit_card", "credit_card", "bank_transfer", "net_banking", "wallet", "cheque", "other"] as const;

export const ACCOUNT_TYPES = ["cash", "bank", "upi", "debit_card", "credit_card", "wallet", "other"] as const;

export const IN_TYPES = new Set(["income", "refund", "loan_received", "loan_repayment_received", "reimbursement_received"]);

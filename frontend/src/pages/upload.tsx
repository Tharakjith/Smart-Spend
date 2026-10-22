import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileText, Info, Loader2, Plus, RefreshCw, Trash2, Upload, XCircle } from "lucide-react";
import * as React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Field, Input, PageHeader, Select, Skeleton, Table, TBody, TD, TH, THead, TR, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, date, dateTime, label, money, PAYMENT_METHODS } from "@/lib/format";
import { categoryOptions, useAccounts, useCategories } from "@/lib/queries";

type FieldVal = { value: string | null; confidence: number; edited?: boolean };
type Item = { name: string; quantity: string | null; unit: string | null; unit_price: string | null; line_total: string | null; confidence?: number };
type Doc = {
  id: string;
  filename: string;
  content_type: string;
  status: string;
  doc_kind: string;
  error_message: string;
  created_at: string;
  overall_confidence?: number;
  merchant?: string | null;
  total?: string | null;
  date?: string | null;
  transaction_id?: string | null;
  extraction?: {
    method: string;
    fields: Record<string, FieldVal>;
    line_items: Item[];
    validation: { level: string; code: string; message: string; transaction_id?: string }[];
    suggested_category_id: string | null;
    category_reasons?: string[];
    raw_text: string;
  };
};

const STATUS_TONE: Record<string, "default" | "success" | "warning" | "danger" | "info"> = {
  uploaded: "default",
  queued: "info",
  processing: "info",
  needs_review: "warning",
  confirmed: "success",
  failed: "danger",
  archived: "default",
};

const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong");

function Dropzone({ onFiles, accept, label: text, busy }: { onFiles: (f: File[]) => void; accept: string; label: string; busy?: boolean }) {
  const [over, setOver] = React.useState(false);
  const ref = React.useRef<HTMLInputElement>(null);
  return (
    <div
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && ref.current?.click()}
      onClick={() => ref.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        onFiles(Array.from(e.dataTransfer.files));
      }}
      className={cn("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors", over ? "border-primary bg-accent" : "hover:bg-muted/50")}
    >
      {busy ? <Loader2 className="size-8 animate-spin text-muted-foreground" /> : <Upload className="size-8 text-muted-foreground" aria-hidden />}
      <p className="font-medium">{text}</p>
      <p className="text-xs text-muted-foreground">Drag and drop, or click to choose. Files are stored privately and checked before processing.</p>
      <input
        ref={ref}
        type="file"
        multiple
        accept={accept}
        className="sr-only"
        onChange={(e) => {
          onFiles(Array.from(e.target.files ?? []));
          e.target.value = ""; // so choosing the same file again still triggers an upload (and the duplicate warning)
        }}
      />
    </div>
  );
}

function Preview({ doc }: { doc: Doc }) {
  const link = useQuery({ queryKey: ["doc-link", doc.id], queryFn: () => api<{ url: string }>(`/documents/${doc.id}/download-link`), staleTime: 240_000 });
  if (!link.data) return <Skeleton className="h-96" />;
  return doc.content_type === "application/pdf" ? (
    <iframe title={`Preview of ${doc.filename}`} src={link.data.url} className="h-[70vh] w-full rounded-md border bg-white" />
  ) : (
    <img src={link.data.url} alt={`Uploaded document ${doc.filename}`} className="max-h-[70vh] w-full rounded-md border object-contain bg-white" />
  );
}

function Conf({ f }: { f?: FieldVal }) {
  if (!f || f.value === null || f.value === undefined) return <Badge tone="danger">not found</Badge>;
  if (f.edited) return <Badge tone="info">edited</Badge>;
  const c = f.confidence;
  return <Badge tone={c >= 0.85 ? "success" : c >= 0.6 ? "warning" : "danger"}>{Math.round(c * 100)}%</Badge>;
}

function ReviewDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { household, canWrite } = useAuth();
  const cats = useCategories();
  const accounts = useAccounts();
  const doc = useQuery({ queryKey: ["document", id], queryFn: () => api<Doc>(`/documents/${id}`), enabled: !!id, refetchInterval: (q) => (["queued", "processing"].includes(q.state.data?.status ?? "") ? 1500 : false) });
  const d = doc.data;
  const [form, setForm] = React.useState<Record<string, string>>({});
  const [items, setItems] = React.useState<Item[]>([]);
  React.useEffect(() => {
    if (!d?.extraction) return;
    const f = d.extraction.fields;
    const v = (k: string) => f[k]?.value ?? "";
    setForm({
      merchant_name: v("merchant_name"),
      occurred_on: v("date"),
      occurred_time: (v("time") || "").slice(0, 5),
      amount: v("total"),
      currency: v("currency") || household?.base_currency || "INR",
      invoice_number: v("invoice_number"),
      payment_reference: v("payment_reference"),
      payment_method: v("payment_method"),
      discount: v("discount"),
      tax: v("tax"),
      // "Auto" by default: the backend categorises with the final merchant and items the user confirms.
      category_id: "",
      account_id: "",
      doc_kind: d.doc_kind,
      notes: "",
    });
    setItems(d.extraction.line_items ?? []);
  }, [d?.id, d?.extraction, d?.doc_kind, household]);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm((x) => ({ ...x, [k]: e.target.value }));
  const blank = (s?: string) => (s ? s : null);

  const saveDraft = useMutation({
    mutationFn: () =>
      api(`/documents/${id}/extraction`, {
        method: "PUT",
        body: {
          fields: { merchant_name: form.merchant_name, date: form.occurred_on, time: form.occurred_time, total: form.amount, currency: form.currency, invoice_number: form.invoice_number, payment_reference: form.payment_reference, payment_method: form.payment_method, discount: form.discount, tax: form.tax },
          line_items: items,
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["document", id] });
      toast.success("Corrections saved and re-validated");
    },
    onError: err,
  });
  const confirm = useMutation({
    mutationFn: () =>
      api(`/documents/${id}/confirm`, {
        body: {
          merchant_name: form.merchant_name,
          occurred_on: form.occurred_on,
          occurred_time: form.occurred_time ? `${form.occurred_time}:00` : null,
          amount: form.amount,
          currency: form.currency,
          category_id: blank(form.category_id),
          payment_method: blank(form.payment_method),
          account_id: blank(form.account_id),
          invoice_number: blank(form.invoice_number),
          payment_reference: blank(form.payment_reference),
          doc_kind: form.doc_kind,
          discount: blank(form.discount),
          tax: blank(form.tax),
          notes: form.notes,
          line_items: items.filter((i) => i.name.trim()).map((i) => ({ name: i.name, quantity: blank(i.quantity ?? ""), unit: blank(i.unit ?? ""), unit_price: blank(i.unit_price ?? ""), line_total: blank(i.line_total ?? "") })),
        },
      }),
    onSuccess: (r: any) => {
      qc.invalidateQueries();
      onClose();
      if (r.transaction.reconciliation_status === "suggested_match") toast.info("Saved. A matching payment was found — review it in Duplicates & Reconciliation so it's counted once.");
      else toast.success("Saved to your ledger");
    },
    onError: err,
  });
  const reprocess = useMutation({ mutationFn: () => api(`/documents/${id}/reprocess`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["document", id] }), onError: err });

  const itemsTotal = items.reduce((a, i) => a + Math.round(Number(i.line_total || 0) * 100), 0);
  const editable = canWrite && d && ["needs_review", "failed"].includes(d.status);
  const missing = !form.merchant_name || !form.occurred_on || !form.amount;

  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide className="max-w-6xl" title={d ? d.filename : "Document"} description={d ? `${label(d.status)} · uploaded ${dateTime(d.created_at)}` : undefined}>
        {!d ? (
          <Skeleton className="h-96" />
        ) : ["queued", "processing"].includes(d.status) ? (
          <div className="flex items-center gap-3 p-10 text-sm" role="status">
            <Loader2 className="size-5 animate-spin" /> Extracting text and details…
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-2">
            <div className="grid gap-2">
              <Preview doc={d} />
              {d.extraction?.raw_text && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-muted-foreground">Extracted text ({d.extraction.method === "pdf_text" ? "embedded PDF text" : d.extraction.method})</summary>
                  <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2">{d.extraction.raw_text}</pre>
                </details>
              )}
            </div>
            <div className="grid content-start gap-4">
              {d.status === "confirmed" && d.transaction_id && (
                <p className="rounded-md bg-accent p-3 text-sm">
                  Confirmed.{" "}
                  <Link className="text-primary underline" to={`/transactions?open=${d.transaction_id}`} onClick={onClose}>
                    Open the transaction
                  </Link>
                </p>
              )}
              {d.error_message && <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{d.error_message}</p>}
              {(d.extraction?.validation ?? []).length > 0 && (
                <ul className="grid gap-1.5 text-sm" aria-label="Validation results">
                  {d.extraction!.validation.map((v, i) => (
                    <li key={i} className={cn("flex items-start gap-2 rounded-md p-2", v.level === "error" ? "bg-destructive/10" : v.level === "warning" ? "bg-amber-100/60 dark:bg-amber-950/40" : "bg-muted")}>
                      {v.level === "error" ? <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="Error" /> : v.level === "warning" ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-label="Warning" /> : <Info className="mt-0.5 size-4 shrink-0" aria-label="Info" />}
                      <span>{v.message}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="grid grid-cols-2 gap-3">
                <Field label="Document type" htmlFor="dk" hint={form.doc_kind === "upi_screenshot" ? "Recorded as a payment" : "Recorded as a bill"}>
                  <Select id="dk" value={form.doc_kind} onChange={set("doc_kind")} disabled={!editable}>
                    <option value="receipt">Receipt</option>
                    <option value="invoice">Invoice</option>
                    <option value="upi_screenshot">UPI / payment screenshot</option>
                  </Select>
                </Field>
                <Field
                  label="Category"
                  htmlFor="cat"
                  hint={(() => {
                    if (form.category_id) return undefined;
                    const name = (cats.data ?? []).find((c) => c.id === d.extraction?.suggested_category_id)?.name;
                    const why = d.extraction?.category_reasons ?? [];
                    if (name && why.length) return `Auto: ${name} — found ${why.slice(0, 3).join(", ")}`;
                    return "Auto: no clear category in this bill yet; pick one, or it will use the merchant you confirm";
                  })()}
                >
                  <Select id="cat" value={form.category_id} onChange={set("category_id")} disabled={!editable}>
                    <option value="">Auto</option>
                    {categoryOptions(cats.data, "expense").map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {(
                  [
                    ["merchant_name", "Merchant", "merchant_name"],
                    ["occurred_on", "Date", "date"],
                    ["occurred_time", "Time", "time"],
                    ["amount", "Total amount", "total"],
                    ["currency", "Currency", "currency"],
                    ["invoice_number", "Invoice / receipt no.", "invoice_number"],
                    ["payment_reference", "UPI / transaction ref", "payment_reference"],
                    ["discount", "Discount", "discount"],
                    ["tax", "Tax (GST)", "tax"],
                  ] as const
                ).map(([k, l, fk]) => (
                  <div key={k} className="grid gap-1.5">
                    <div className="flex items-center justify-between">
                      <label htmlFor={`f-${k}`} className="text-sm font-medium">
                        {l}
                      </label>
                      <Conf f={d.extraction?.fields[fk]} />
                    </div>
                    <Input id={`f-${k}`} type={k === "occurred_on" ? "date" : k === "occurred_time" ? "time" : "text"} value={form[k] ?? ""} onChange={set(k)} disabled={!editable} aria-invalid={["merchant_name", "occurred_on", "amount"].includes(k) && !form[k]} />
                  </div>
                ))}
                <Field label="Payment method" htmlFor="pm">
                  <Select id="pm" value={form.payment_method} onChange={set("payment_method")} disabled={!editable}>
                    <option value="">Not stated</option>
                    {PAYMENT_METHODS.map((p) => (
                      <option key={p} value={p}>
                        {label(p)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Account (optional)" htmlFor="acc">
                  <Select id="acc" value={form.account_id} onChange={set("account_id")} disabled={!editable}>
                    <option value="">—</option>
                    {(accounts.data ?? []).map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <div className="grid gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">Line items ({items.length})</span>
                  {editable && (
                    <Button type="button" variant="outline" size="sm" onClick={() => setItems((x) => [...x, { name: "", quantity: null, unit: null, unit_price: null, line_total: null }])}>
                      <Plus /> Add
                    </Button>
                  )}
                </div>
                {items.length > 0 && (
                  <div className="max-h-64 overflow-auto rounded-md border">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-muted">
                        <tr>
                          <th className="p-1.5 text-left">Item</th>
                          <th className="p-1.5">Qty</th>
                          <th className="p-1.5">Unit</th>
                          <th className="p-1.5">Price</th>
                          <th className="p-1.5">Total</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((it, i) => (
                          <tr key={i} className="border-t">
                            {(["name", "quantity", "unit", "unit_price", "line_total"] as const).map((k) => (
                              <td key={k} className="p-1">
                                <Input
                                  className="h-7 text-xs"
                                  aria-label={`${k} for line ${i + 1}`}
                                  value={it[k] ?? ""}
                                  disabled={!editable}
                                  onChange={(e) => setItems((x) => x.map((y, j) => (j === i ? { ...y, [k]: e.target.value } : y)))}
                                />
                              </td>
                            ))}
                            <td className="p-1">
                              {editable && (
                                <Button variant="ghost" size="icon" className="size-7" aria-label={`Remove line ${i + 1}`} onClick={() => setItems((x) => x.filter((_, j) => j !== i))}>
                                  <Trash2 />
                                </Button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {items.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    Items add up to {money((itemsTotal / 100).toFixed(2), form.currency)}
                    {form.amount && Math.round(Number(form.amount) * 100) !== itemsTotal ? ` · bill total ${money(form.amount, form.currency)} (difference from tax, discounts or charges)` : ""}
                  </p>
                )}
              </div>
              {editable && (
                <div className="flex flex-wrap justify-end gap-2 border-t pt-3">
                  <Button variant="ghost" loading={reprocess.isPending} onClick={() => reprocess.mutate()}>
                    <RefreshCw /> Re-run extraction
                  </Button>
                  <Button variant="outline" loading={saveDraft.isPending} onClick={() => saveDraft.mutate()}>
                    Save &amp; re-validate
                  </Button>
                  <Button loading={confirm.isPending} disabled={missing} onClick={() => confirm.mutate()}>
                    <CheckCircle2 /> Confirm &amp; save
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Documents() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const [params, setParams] = useSearchParams();
  const [kind, setKind] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [filter, setFilter] = React.useState("");
  const docs = useQuery({
    queryKey: ["documents", filter],
    queryFn: () => api<{ items: Doc[]; total: number }>(`/documents?page_size=100${filter ? `&status=${filter}` : ""}`),
    refetchInterval: (q) => (q.state.data?.items.some((d) => ["queued", "processing"].includes(d.status)) ? 2000 : false),
  });
  const open = params.get("doc");
  const setOpen = (id: string | null) => {
    const n = new URLSearchParams(params);
    if (id) n.set("doc", id);
    else n.delete("doc");
    setParams(n, { replace: true });
  };
  const upload = async (files: File[]) => {
    setBusy(true);
    for (const f of files) {
      const fd = new FormData();
      fd.append("file", f);
      if (kind) fd.append("doc_kind", kind);
      try {
        const d = await api<Doc>("/documents", { form: fd });
        toast.success(`${f.name} uploaded`);
        if (files.length === 1) setOpen(d.id);
      } catch (e) {
        if (e instanceof ApiError && e.code === "duplicate_document") {
          toast.warning(`${f.name}: ${e.message}`, { action: { label: "View original", onClick: () => setOpen(String(e.details.existing_document_id)) } });
        } else err(e);
      }
    }
    setBusy(false);
    qc.invalidateQueries({ queryKey: ["documents"] });
  };
  const remove = useMutation({ mutationFn: (id: string) => api(`/documents/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["documents"] }), onError: err });

  return (
    <div className="grid gap-4">
      {canWrite && (
        <Card className="p-4">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <label htmlFor="kind" className="text-sm font-medium">
              Type
            </label>
            <Select id="kind" className="w-64" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">Detect automatically</option>
              <option value="receipt">Receipt / bill</option>
              <option value="invoice">Invoice</option>
              <option value="upi_screenshot">UPI / payment screenshot</option>
            </Select>
          </div>
          <Dropzone onFiles={upload} busy={busy} accept=".pdf,.jpg,.jpeg,.png,.webp" label="Upload bills, invoices, receipts or payment screenshots (PDF, JPG, PNG, WebP · max 15 MB)" />
        </Card>
      )}
      <div className="flex items-center gap-2">
        <Select aria-label="Filter by status" className="w-56" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All documents</option>
          <option value="needs_review">Needs review</option>
          <option value="queued,processing">Processing</option>
          <option value="confirmed">Confirmed</option>
          <option value="failed">Failed</option>
          <option value="archived">Archived</option>
        </Select>
      </div>
      {docs.isLoading ? (
        <Skeleton className="h-40" />
      ) : (docs.data?.items ?? []).length === 0 ? (
        <EmptyState title="No documents yet" description="Upload a bill or receipt to extract its details automatically." icon={<FileText className="size-8" />} />
      ) : (
        <Card>
          <Table>
            <THead>
              <tr>
                <TH>File</TH>
                <TH>Merchant</TH>
                <TH className="hidden sm:table-cell">Date</TH>
                <TH className="text-right">Total</TH>
                <TH>Status</TH>
                <TH />
              </tr>
            </THead>
            <TBody>
              {docs.data!.items.map((d) => (
                <TR key={d.id} className="cursor-pointer" onClick={() => setOpen(d.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setOpen(d.id)}>
                  <TD>
                    <div className="font-medium">{d.filename}</div>
                    <div className="text-xs text-muted-foreground">
                      {label(d.doc_kind)} · {dateTime(d.created_at)}
                    </div>
                  </TD>
                  <TD>{d.merchant ?? "—"}</TD>
                  <TD className="hidden sm:table-cell">{date(d.date)}</TD>
                  <TD className="text-right tabular">{d.total ? money(d.total) : "—"}</TD>
                  <TD>
                    <Badge tone={STATUS_TONE[d.status]}>
                      {["queued", "processing"].includes(d.status) && <Loader2 className="size-3 animate-spin" />}
                      {label(d.status)}
                    </Badge>
                  </TD>
                  <TD className="text-right">
                    {canWrite && d.status !== "confirmed" && (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${d.filename}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          remove.mutate(d.id);
                        }}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </Card>
      )}
      <ReviewDialog id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

const MAP_FIELDS = [
  ["date", "Date", true],
  ["description", "Description / narration", true],
  ["debit", "Debit / withdrawal", false],
  ["credit", "Credit / deposit", false],
  ["amount", "Signed amount", false],
  ["direction", "Dr/Cr indicator", false],
  ["reference", "Reference / UTR", false],
  ["balance", "Balance", false],
] as const;

function Statements() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const accounts = useAccounts();
  const [accountId, setAccountId] = React.useState("");
  const [sourceKind, setSourceKind] = React.useState("bank");
  const [busy, setBusy] = React.useState(false);
  const [imp, setImp] = React.useState<any>(null);
  const [mapping, setMapping] = React.useState<Record<string, string | null>>({});
  const history = useQuery({ queryKey: ["imports"], queryFn: () => api("/imports") });
  const preview = useQuery({ queryKey: ["import-preview", imp?.id, imp?.column_mapping], queryFn: () => api(`/imports/${imp.id}/preview`), enabled: !!imp && imp.status !== "confirmed" });
  const upload = async (files: File[]) => {
    if (!files[0]) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", files[0]);
    if (accountId) fd.append("account_id", accountId);
    fd.append("source_kind", sourceKind);
    try {
      const r = await api("/imports", { form: fd });
      setImp(r);
      setMapping(r.column_mapping);
      if (r.previously_imported) toast.warning("This exact file was imported before. Rows already imported will be skipped automatically.");
    } catch (e) {
      err(e);
    } finally {
      setBusy(false);
    }
  };
  const saveMapping = useMutation({
    mutationFn: () => api(`/imports/${imp.id}/mapping`, { method: "PUT", body: { column_mapping: mapping } }),
    onSuccess: (r) => {
      setImp(r);
      toast.success("Mapping updated");
    },
    onError: err,
  });
  const confirm = useMutation({
    mutationFn: () => api(`/imports/${imp.id}/confirm`, { method: "POST" }),
    onSuccess: (r: any) => {
      qc.invalidateQueries();
      setImp(null);
      toast.success(`Imported ${r.imported_count} transaction(s); skipped ${r.skipped_duplicates} already-imported row(s).`);
    },
    onError: err,
  });
  const p = preview.data;
  return (
    <div className="grid gap-4">
      {canWrite && !imp && (
        <Card className="p-4">
          <div className="mb-3 grid gap-3 sm:grid-cols-2">
            <Field label="Account" htmlFor="imp-acc" hint="Choose the account the statement belongs to">
              <Select id="imp-acc" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                <option value="">Not linked to an account</option>
                {(accounts.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Statement type" htmlFor="imp-kind">
              <Select id="imp-kind" value={sourceKind} onChange={(e) => setSourceKind(e.target.value)}>
                <option value="bank">Bank account</option>
                <option value="credit_card">Credit card</option>
                <option value="upi">UPI app export</option>
                <option value="wallet">Wallet</option>
              </Select>
            </Field>
          </div>
          <Dropzone onFiles={upload} busy={busy} accept=".csv,.xlsx,.pdf,.txt" label="Upload a statement (CSV, XLSX or PDF)" />
        </Card>
      )}
      {imp && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Map columns · {imp.filename}</CardTitle>
              <CardDescription>
                {imp.row_count} rows detected. Check that each field points at the right column, then review the preview.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-4">
              {MAP_FIELDS.map(([k, l, req]) => (
                <Field key={k} label={`${l}${req ? " *" : ""}`} htmlFor={`map-${k}`}>
                  <Select id={`map-${k}`} value={mapping[k] ?? ""} onChange={(e) => setMapping((m) => ({ ...m, [k]: e.target.value || null }))}>
                    <option value="">—</option>
                    {imp.headers.map((h: string) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </Select>
                </Field>
              ))}
              <div className="flex items-end gap-2 sm:col-span-4">
                <Button variant="outline" loading={saveMapping.isPending} onClick={() => saveMapping.mutate()}>
                  Apply mapping
                </Button>
                <Button variant="ghost" onClick={() => api(`/imports/${imp.id}`, { method: "DELETE" }).then(() => setImp(null))}>
                  Discard
                </Button>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Preview</CardTitle>
              {p && (
                <CardDescription>
                  {p.counts.new} new · {p.counts.duplicate_existing} already imported (will be skipped) · {p.counts.invalid} invalid · {p.possible_matches} may match existing receipts or entries · debits {money(p.new_debits_total, imp.currency)} · credits {money(p.new_credits_total, imp.currency)}
                </CardDescription>
              )}
            </CardHeader>
            <CardContent>
              {preview.isLoading ? (
                <Skeleton className="h-40" />
              ) : preview.isError ? (
                <p className="text-sm text-destructive">{(preview.error as Error).message}</p>
              ) : (
                p && (
                  <>
                    <div className="max-h-[50vh] overflow-auto rounded-md border">
                      <Table>
                        <THead>
                          <tr>
                            <TH>Date</TH>
                            <TH>Description</TH>
                            <TH>Type</TH>
                            <TH className="text-right">Amount</TH>
                            <TH>Status</TH>
                          </tr>
                        </THead>
                        <TBody>
                          {p.rows.map((r: any) => (
                            <TR key={r.row_index} className={cn(r.status !== "new" && "opacity-60")}>
                              <TD className="whitespace-nowrap">{r.occurred_on ? date(r.occurred_on) : "—"}</TD>
                              <TD>
                                <div className="max-w-md truncate">{r.description}</div>
                                {r.payee && <div className="text-xs text-muted-foreground">Payee: {r.payee}{r.reference ? ` · ref ${r.reference}` : ""}</div>}
                                {r.possible_match && (
                                  <div className="text-xs text-warning">
                                    May match: {r.possible_match.description} ({money(r.possible_match.amount)}, {date(r.possible_match.occurred_on)}) — you'll review it after import
                                  </div>
                                )}
                                {r.errors?.length > 0 && <div className="text-xs text-destructive">{r.errors.join("; ")}</div>}
                              </TD>
                              <TD>{label(r.suggested_type)}</TD>
                              <TD className={cn("text-right tabular", r.direction === "in" && "text-success")}>
                                {r.amount ? `${r.direction === "in" ? "+" : "−"}${money(r.amount, r.currency)}` : "—"}
                              </TD>
                              <TD>
                                <Badge tone={r.status === "new" ? "success" : r.status === "invalid" ? "danger" : "default"}>{r.status === "duplicate_existing" ? "Already imported" : label(r.status)}</Badge>
                              </TD>
                            </TR>
                          ))}
                        </TBody>
                      </Table>
                    </div>
                    <div className="mt-3 flex justify-end">
                      <Button loading={confirm.isPending} disabled={p.counts.new === 0} onClick={() => confirm.mutate()}>
                        <CheckCircle2 /> Import {p.counts.new} transaction(s)
                      </Button>
                    </div>
                  </>
                )
              )}
            </CardContent>
          </Card>
        </>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Import history</CardTitle>
        </CardHeader>
        <CardContent>
          {(history.data?.items ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">No statements imported yet.</p>
          ) : (
            <ul className="divide-y text-sm">
              {history.data.items.map((i: any) => (
                <li key={i.id} className="flex flex-wrap items-center gap-2 py-2">
                  <span className="flex-1 font-medium">{i.filename}</span>
                  <span className="text-muted-foreground">{dateTime(i.created_at)}</span>
                  <Badge tone={i.status === "confirmed" ? "success" : "warning"}>{label(i.status)}</Badge>
                  {i.status === "confirmed" ? (
                    <span className="text-xs text-muted-foreground">
                      {i.imported_count} imported · {i.skipped_duplicates} skipped · {i.invalid_count} invalid
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setImp(i);
                        setMapping(i.column_mapping);
                      }}
                    >
                      Continue
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function UploadPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "documents";
  return (
    <>
      <PageHeader title="Upload Bills" description="Bills, receipts and payment screenshots are extracted for review; statements are imported with duplicate protection." />
      <Tabs
        value={tab}
        onValueChange={(v) => {
          const n = new URLSearchParams(params);
          n.set("tab", v);
          setParams(n, { replace: true });
        }}
      >
        <TabsList className="mb-4">
          <TabsTrigger value="documents">Bills & receipts</TabsTrigger>
          <TabsTrigger value="statements">Statements</TabsTrigger>
        </TabsList>
        <TabsContent value="documents">
          <Documents />
        </TabsContent>
        <TabsContent value="statements">
          <Statements />
        </TabsContent>
      </Tabs>
    </>
  );
}

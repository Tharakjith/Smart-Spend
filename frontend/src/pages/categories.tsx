import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, FlaskConical, Plus, Trash2, Wand2, X } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Field, Input, PageHeader, Select, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { label, TX_TYPES } from "@/lib/format";
import { categoryOptions, useCategories } from "@/lib/queries";

const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Failed");

function CategoryTree() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const cats = useCategories();
  const [name, setName] = React.useState("");
  const [parent, setParent] = React.useState("");
  const [kind, setKind] = React.useState("expense");
  const add = useMutation({
    mutationFn: () => api("/categories", { body: { name, parent_id: parent || null, kind } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      setName("");
      toast.success("Category added");
    },
    onError: err,
  });
  const archive = useMutation({
    mutationFn: (id: string) => api(`/categories/${id}`, { method: "DELETE" }),
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      toast.success(r.archived ? "Archived (it is in use)" : "Deleted");
    },
    onError: err,
  });
  const toggleFixed = useMutation({
    mutationFn: ({ id, v }: { id: string; v: boolean }) => api(`/categories/${id}`, { method: "PATCH", body: { is_fixed: v } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["categories"] }),
    onError: err,
  });
  if (cats.isLoading) return <Skeleton className="h-64" />;
  const all = (cats.data ?? []).filter((c) => !c.is_archived);
  const parents = all.filter((c) => !c.parent_id).sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name));
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="grid gap-2 lg:col-span-2">
        {parents.map((p) => (
          <Card key={p.id} className="p-3">
            <div className="flex items-center gap-2">
              <span className="inline-block size-3 rounded-full" style={{ background: p.color || "var(--muted-foreground)" }} aria-hidden />
              <span className="font-medium">{p.name}</span>
              <Badge>{p.kind}</Badge>
              {p.is_fixed && <Badge tone="info">fixed</Badge>}
              {canWrite && (
                <div className="ml-auto flex gap-1">
                  {p.kind === "expense" && (
                    <Button variant="ghost" size="sm" onClick={() => toggleFixed.mutate({ id: p.id, v: !p.is_fixed })}>
                      {p.is_fixed ? "Mark variable" : "Mark fixed"}
                    </Button>
                  )}
                  {!p.is_system && (
                    <Button variant="ghost" size="icon" aria-label={`Archive ${p.name}`} onClick={() => archive.mutate(p.id)}>
                      <Archive />
                    </Button>
                  )}
                </div>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5 pl-5">
              {all
                .filter((c) => c.parent_id === p.id)
                .map((c) => (
                  <span key={c.id} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">
                    {c.name}
                    {canWrite && !c.is_system && (
                      <button className="text-muted-foreground hover:text-destructive cursor-pointer" aria-label={`Archive ${c.name}`} onClick={() => archive.mutate(c.id)}>
                        <X className="size-3" />
                      </button>
                    )}
                  </span>
                ))}
            </div>
          </Card>
        ))}
      </div>
      {canWrite && (
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Add a category</CardTitle>
            <CardDescription>Create custom categories or subcategories.</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="grid gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                add.mutate();
              }}
            >
              <Field label="Name" htmlFor="cat-name">
                <Input id="cat-name" required value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label="Parent" htmlFor="cat-parent">
                <Select id="cat-parent" value={parent} onChange={(e) => setParent(e.target.value)}>
                  <option value="">Top level</option>
                  {parents.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
              </Field>
              {!parent && (
                <Field label="Kind" htmlFor="cat-kind">
                  <Select id="cat-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
                    <option value="expense">Expense</option>
                    <option value="income">Income</option>
                  </Select>
                </Field>
              )}
              <Button type="submit" loading={add.isPending}>
                <Plus /> Add
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

type Rule = { id: string; name: string; priority: number; field: string; operator: string; pattern: string; category_id: string | null; set_type: string | null; is_active: boolean };

function Rules() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const cats = useCategories();
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api<Rule[]>("/rules") });
  const blank = { name: "", priority: "100", field: "description", operator: "contains", pattern: "", category_id: "", set_type: "" };
  const [f, setF] = React.useState(blank);
  const [test, setTest] = React.useState({ description: "", merchant: "" });
  const [result, setResult] = React.useState<any>(null);
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((x) => ({ ...x, [k]: e.target.value }));
  const add = useMutation({
    mutationFn: () => api("/rules", { body: { ...f, priority: Number(f.priority), category_id: f.category_id || null, set_type: f.set_type || null } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] });
      setF(blank);
      toast.success("Rule added. It applies to new transactions first, before any automatic categorisation.");
    },
    onError: err,
  });
  const del = useMutation({ mutationFn: (id: string) => api(`/rules/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }), onError: err });
  const catName = (id: string | null) => (cats.data ?? []).find((c) => c.id === id)?.name ?? "—";
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2">
        {rules.isLoading ? (
          <Skeleton className="h-40" />
        ) : (rules.data ?? []).length === 0 ? (
          <EmptyState title="No rules yet" description="Rules run first: e.g. description contains 'KSEB' → Electricity." />
        ) : (
          <ul className="grid gap-2">
            {rules.data!.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2 rounded-md border bg-card p-3 text-sm">
                <Badge>#{r.priority}</Badge>
                <span className="font-medium">{r.name}</span>
                <span className="text-muted-foreground">
                  {r.field} {label(r.operator).toLowerCase()} “{r.pattern}” → {r.category_id ? catName(r.category_id) : ""}
                  {r.set_type ? ` (type: ${label(r.set_type)})` : ""}
                </span>
                {canWrite && (
                  <Button className="ml-auto" variant="ghost" size="icon" aria-label={`Delete rule ${r.name}`} onClick={() => del.mutate(r.id)}>
                    <Trash2 />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FlaskConical className="size-4" /> Test categorisation
            </CardTitle>
            <CardDescription>Priority: your rules → confirmed merchant mappings → known merchants → keywords → uncategorised.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-3">
            <Input aria-label="Test description" placeholder="Description" value={test.description} onChange={(e) => setTest((t) => ({ ...t, description: e.target.value }))} />
            <Input aria-label="Test merchant" placeholder="Merchant" value={test.merchant} onChange={(e) => setTest((t) => ({ ...t, merchant: e.target.value }))} />
            <Button variant="outline" onClick={() => api("/rules/test", { body: test }).then(setResult).catch(err)}>
              Test
            </Button>
            {result && (
              <p className="text-sm sm:col-span-3">
                → <strong>{catName(result.category_id)}</strong> via {label(result.source)} (confidence {Math.round(result.confidence * 100)}%)
              </p>
            )}
          </CardContent>
        </Card>
      </div>
      {canWrite && (
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>New rule</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="grid gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                add.mutate();
              }}
            >
              <Field label="Name" htmlFor="r-name">
                <Input id="r-name" required value={f.name} onChange={set("name")} />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Field" htmlFor="r-field">
                  <Select id="r-field" value={f.field} onChange={set("field")}>
                    {["description", "merchant", "item", "counterparty"].map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </Select>
                </Field>
                <Field label="Operator" htmlFor="r-op">
                  <Select id="r-op" value={f.operator} onChange={set("operator")}>
                    {["contains", "equals", "starts_with", "regex"].map((x) => (
                      <option key={x} value={x}>
                        {label(x)}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <Field label="Pattern" htmlFor="r-pat">
                <Input id="r-pat" required value={f.pattern} onChange={set("pattern")} />
              </Field>
              <Field label="Set category" htmlFor="r-cat">
                <Select id="r-cat" value={f.category_id} onChange={set("category_id")}>
                  <option value="">—</option>
                  {categoryOptions(cats.data).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Set type (imports only)" htmlFor="r-type" hint="e.g. 'CC PAYMENT' → Credit card payment, so it isn't counted as spending">
                <Select id="r-type" value={f.set_type} onChange={set("set_type")}>
                  <option value="">—</option>
                  {TX_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {label(t)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Priority (lower runs first)" htmlFor="r-pri">
                <Input id="r-pri" inputMode="numeric" value={f.priority} onChange={set("priority")} />
              </Field>
              <Button type="submit" loading={add.isPending}>
                Add rule
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

type Merchant = { id: string; name: string; normalized_name: string; default_category_id: string | null; aliases: { id: string; alias: string; source: string }[] };

function Merchants() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const cats = useCategories();
  const [q, setQ] = React.useState("");
  const merchants = useQuery({ queryKey: ["merchants", q], queryFn: () => api<Merchant[]>(`/merchants?q=${encodeURIComponent(q)}`) });
  const [alias, setAlias] = React.useState<Record<string, string>>({});
  const addAlias = useMutation({
    mutationFn: (id: string) => api(`/merchants/${id}/aliases`, { body: { alias: alias[id] } }),
    onSuccess: (_r, id) => {
      qc.invalidateQueries({ queryKey: ["merchants"] });
      setAlias((a) => ({ ...a, [id]: "" }));
    },
    onError: err,
  });
  const delAlias = useMutation({ mutationFn: (id: string) => api(`/merchant-aliases/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["merchants"] }), onError: err });
  const setDefault = useMutation({
    mutationFn: ({ id, cid }: { id: string; cid: string }) => api(`/merchants/${id}`, { method: "PATCH", body: { default_category_id: cid || null } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["merchants"] }),
    onError: err,
  });
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">Aliases let different spellings (e.g. “FRESHMART TRIVANDRUM” on a UPI statement) resolve to one merchant. Confirmed matches add aliases automatically.</p>
      <Input aria-label="Search merchants" placeholder="Search merchants" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-sm" />
      {merchants.isLoading ? (
        <Skeleton className="h-40" />
      ) : (merchants.data ?? []).length === 0 ? (
        <EmptyState title="No merchants yet" description="Merchants are created as you record transactions." />
      ) : (
        merchants.data!.map((m) => (
          <Card key={m.id} className="p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{m.name}</span>
              <span className="text-xs text-muted-foreground">normalised: {m.normalized_name}</span>
              <Select aria-label={`Default category for ${m.name}`} className="ml-auto w-56" value={m.default_category_id ?? ""} disabled={!canWrite} onChange={(e) => setDefault.mutate({ id: m.id, cid: e.target.value })}>
                <option value="">No default category</option>
                {categoryOptions(cats.data, "expense").map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {m.aliases.map((a) => (
                <span key={a.id} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">
                  {a.alias}
                  {a.source === "confirmed_match" && <span className="text-muted-foreground">(learned)</span>}
                  {canWrite && (
                    <button aria-label={`Remove alias ${a.alias}`} className="text-muted-foreground hover:text-destructive cursor-pointer" onClick={() => delAlias.mutate(a.id)}>
                      <X className="size-3" />
                    </button>
                  )}
                </span>
              ))}
              {canWrite && (
                <form
                  className="flex gap-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (alias[m.id]) addAlias.mutate(m.id);
                  }}
                >
                  <Input aria-label={`New alias for ${m.name}`} className="h-7 w-48 text-xs" placeholder="Add alias" value={alias[m.id] ?? ""} onChange={(e) => setAlias((a) => ({ ...a, [m.id]: e.target.value }))} />
                  <Button size="sm" variant="ghost" type="submit">
                    <Plus />
                  </Button>
                </form>
              )}
            </div>
          </Card>
        ))
      )}
    </div>
  );
}

function ReapplyButton() {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const [result, setResult] = React.useState<{ checked: number; changed: { id: string; description: string; from: string | null; to: string | null; reasons: string[] }[] } | null>(null);
  const run = useMutation({
    mutationFn: () => api("/transactions/recategorize", { body: {} }),
    onSuccess: (r: any) => {
      qc.invalidateQueries();
      setResult(r);
      toast.success(r.changed.length ? `Updated ${r.changed.length} of ${r.checked} automatically categorised transactions` : `Checked ${r.checked} transactions; all categories are already up to date`);
    },
    onError: err,
  });
  if (!canWrite) return null;
  return (
    <>
      <Button variant="outline" loading={run.isPending} onClick={() => run.mutate()}>
        <Wand2 /> Re-apply automatic categorisation
      </Button>
      {result && result.changed.length > 0 && (
        <Card className="mb-4 w-full p-4 text-sm">
          <p className="mb-2 font-medium">Updated categories (categories you chose yourself were not touched)</p>
          <ul className="grid gap-1">
            {result.changed.slice(0, 20).map((c) => (
              <li key={c.id}>
                {c.description || "Transaction"}: {c.from ?? "—"} → <strong>{c.to}</strong>
                {c.reasons.length > 0 && <span className="text-muted-foreground"> ({c.reasons.slice(0, 2).join(", ")})</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

export function CategoriesPage() {
  return (
    <>
      <PageHeader
        title="Categories & Rules"
        description="Hierarchical categories, your own categorisation rules, and merchant aliases. Automatic categories weigh the merchant, description, line items and the bill's own text."
        actions={<ReapplyButton />}
      />
      <Tabs defaultValue="categories">
        <TabsList className="mb-4">
          <TabsTrigger value="categories">Categories</TabsTrigger>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="merchants">Merchants & aliases</TabsTrigger>
        </TabsList>
        <TabsContent value="categories">
          <CategoryTree />
        </TabsContent>
        <TabsContent value="rules">
          <Rules />
        </TabsContent>
        <TabsContent value="merchants">
          <Merchants />
        </TabsContent>
      </Tabs>
    </>
  );
}

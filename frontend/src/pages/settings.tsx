import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck, Download, KeyRound, LogOut, Plus, RefreshCw, ShieldCheck, Trash2, UserPlus } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Avatar } from "@/components/avatar";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, EmptyState, Field, Input, PageHeader, Select, Skeleton, Switch } from "@/components/ui/primitives";
import { api, ApiError, download, session } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, dateTime, label } from "@/lib/format";

const err = (e: unknown) => toast.error(e instanceof ApiError ? e.message : "Something went wrong");

export function NotificationsPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const list = useQuery({ queryKey: ["notifications"], queryFn: () => api<any>("/notifications?page_size=100") });
  const inv = () => {
    qc.invalidateQueries({ queryKey: ["notifications"] });
    qc.invalidateQueries({ queryKey: ["notif-count"] });
  };
  const readAll = useMutation({ mutationFn: () => api("/notifications/read-all", { method: "POST" }), onSuccess: inv });
  const check = useMutation({
    mutationFn: () => api("/notifications/run-checks", { method: "POST" }),
    onSuccess: (r: any) => {
      inv();
      toast.success(r.created ? `${r.created} new alert(s)` : "No new alerts");
    },
    onError: err,
  });
  const open = async (n: any) => {
    if (!n.read) await api(`/notifications/${n.id}/read`, { method: "POST" }).catch(() => undefined);
    inv();
    if (n.link) nav(n.link);
  };
  const tone = { info: "info", warning: "warning", critical: "danger" } as const;
  return (
    <>
      <PageHeader
        title="Notifications"
        description="Budget alerts, upcoming bills, duplicate-payment warnings, failed documents and unmatched receipts."
        actions={
          <>
            <Button variant="outline" loading={check.isPending} onClick={() => check.mutate()}>
              <RefreshCw /> Check now
            </Button>
            <Button variant="outline" onClick={() => readAll.mutate()}>
              <CheckCheck /> Mark all read
            </Button>
          </>
        }
      />
      {list.isLoading ? (
        <Skeleton className="h-40" />
      ) : (list.data?.items ?? []).length === 0 ? (
        <EmptyState title="You're all caught up" icon={<Bell className="size-8" />} />
      ) : (
        <ul className="grid gap-2">
          {list.data.items.map((n: any) => (
            <li key={n.id}>
              <button onClick={() => open(n)} className={cn("flex w-full items-start gap-3 rounded-lg border bg-card p-3 text-left hover:bg-muted cursor-pointer", !n.read && "border-primary/40")}>
                {!n.read && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" aria-label="Unread" />}
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{n.title}</p>
                  {n.body && <p className="text-sm text-muted-foreground">{n.body}</p>}
                  <p className="mt-1 text-xs text-muted-foreground">{dateTime(n.created_at)}</p>
                </div>
                <Badge tone={tone[n.severity as keyof typeof tone] ?? "default"}>{n.severity}</Badge>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Security() {
  const qc = useQueryClient();
  const { me, reload } = useAuth();
  const [setup, setSetup] = React.useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = React.useState("");
  const [disable, setDisable] = React.useState({ password: "", code: "" });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api<any[]>("/auth/sessions") });
  const start = useMutation({ mutationFn: () => api("/auth/mfa/setup", { method: "POST" }), onSuccess: setSetup, onError: err });
  const enable = useMutation({
    mutationFn: () => api("/auth/mfa/enable", { body: { code } }),
    onSuccess: () => {
      setSetup(null);
      reload();
      toast.success("Two-factor authentication enabled");
    },
    onError: err,
  });
  const off = useMutation({
    mutationFn: () => api("/auth/mfa/disable", { body: disable }),
    onSuccess: () => {
      reload();
      toast.success("Two-factor authentication disabled");
    },
    onError: err,
  });
  const revoke = useMutation({ mutationFn: (id: string) => api(`/auth/sessions/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }), onError: err });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-4" /> Two-factor authentication
          </CardTitle>
          <CardDescription>Use an authenticator app (TOTP) for a second sign-in step.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {me?.user.mfa_enabled ? (
            <>
              <Badge tone="success" className="w-fit">
                Enabled
              </Badge>
              <Field label="Password" htmlFor="mfa-pw">
                <Input id="mfa-pw" type="password" value={disable.password} onChange={(e) => setDisable((d) => ({ ...d, password: e.target.value }))} />
              </Field>
              <Field label="Current code" htmlFor="mfa-c2">
                <Input id="mfa-c2" inputMode="numeric" value={disable.code} onChange={(e) => setDisable((d) => ({ ...d, code: e.target.value }))} />
              </Field>
              <Button variant="outline" loading={off.isPending} onClick={() => off.mutate()}>
                Disable
              </Button>
            </>
          ) : setup ? (
            <>
              <p className="text-sm">Add this key to your authenticator app, then enter the 6-digit code.</p>
              <code className="break-all rounded-md bg-muted p-2 text-sm">{setup.secret}</code>
              <a className="text-xs text-primary underline" href={setup.otpauth_uri}>
                Open in authenticator app
              </a>
              <Field label="Code" htmlFor="mfa-c">
                <Input id="mfa-c" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.trim())} />
              </Field>
              <Button loading={enable.isPending} onClick={() => enable.mutate()}>
                Enable
              </Button>
            </>
          ) : (
            <Button className="w-fit" loading={start.isPending} onClick={() => start.mutate()}>
              <KeyRound /> Set up two-factor
            </Button>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Active sessions</CardTitle>
          <CardDescription>Sign out devices you don't recognise.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="divide-y text-sm">
            {(sessions.data ?? []).map((s) => (
              <li key={s.id} className="flex items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate">{s.user_agent || "Unknown device"}</p>
                  <p className="text-xs text-muted-foreground">
                    {s.ip} · last used {dateTime(s.last_used_at)}
                  </p>
                </div>
                {s.current ? (
                  <Badge tone="primary">This device</Badge>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => revoke.mutate(s.id)}>
                    <LogOut /> Sign out
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

const ROLE_HELP: Record<string, string> = {
  owner: "Full control, including sharing and deleting",
  admin: "Manages people and settings",
  member: "Adds and edits transactions and bills",
  viewer: "Can look, can't change anything",
};

function WorkspaceSettings() {
  const qc = useQueryClient();
  const { household, isAdmin, me, reload, switchHousehold } = useAuth();
  const [name, setName] = React.useState(household?.name ?? "");
  const [invite, setInvite] = React.useState({ email: "", role: "member" });
  const [newName, setNewName] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  React.useEffect(() => setName(household?.name ?? ""), [household?.id, household?.name]);
  const detail = useQuery({ queryKey: ["household", household?.id], queryFn: () => api<any>(`/households/${household!.id}`), enabled: !!household });
  const members = useQuery({ queryKey: ["members", household?.id], queryFn: () => api<any[]>(`/households/${household!.id}/members`), enabled: !!household });
  const patch = useMutation({
    mutationFn: (body: any) => api(`/households/${household!.id}`, { method: "PATCH", body }),
    onSuccess: () => {
      reload();
      qc.invalidateQueries({ queryKey: ["household"] });
      toast.success("Saved");
    },
    onError: err,
  });
  const add = useMutation({
    mutationFn: () => api(`/households/${household!.id}/members`, { body: invite }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["members"] });
      setInvite({ email: "", role: "member" });
      toast.success("Access granted");
    },
    onError: err,
  });
  const role = useMutation({ mutationFn: ({ uid, r }: { uid: string; r: string }) => api(`/households/${household!.id}/members/${uid}`, { method: "PATCH", body: { role: r } }), onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }), onError: err });
  const remove = useMutation({ mutationFn: (uid: string) => api(`/households/${household!.id}/members/${uid}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }), onError: err });
  const create = useMutation({
    mutationFn: () => api("/households", { body: { name: newName.trim(), base_currency: household?.base_currency ?? "INR" } }),
    onSuccess: async (h: any) => {
      await reload();
      switchHousehold(h.id);
      setNewName("");
      setCreating(false);
      toast.success(`Switched to "${h.name}"`);
    },
    onError: err,
  });
  const cfg = detail.data?.matching_config ?? {};
  const people = members.data ?? [];
  const solo = people.length <= 1;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Workspace</CardTitle>
          <CardDescription>Everything you track (transactions, bills, accounts, budgets) lives in this workspace.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <form
            className="flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              patch.mutate({ name: name.trim() });
            }}
          >
            <div className="flex-1">
              <Field label="Name" htmlFor="h-name">
                <Input id="h-name" value={name} disabled={!isAdmin} onChange={(e) => setName(e.target.value)} />
              </Field>
            </div>
            {isAdmin && (
              <Button type="submit" variant="outline" disabled={!name.trim() || name.trim() === household?.name}>
                Save
              </Button>
            )}
          </form>
          <dl className="grid grid-cols-2 gap-3 rounded-md bg-muted/60 p-3 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Currency</dt>
              <dd className="font-medium">{household?.base_currency}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Time zone</dt>
              <dd className="font-medium">{household?.timezone}</dd>
            </div>
          </dl>
          <div className="grid gap-2 rounded-md border p-3">
            <p className="text-sm font-medium">Matching window</p>
            <p className="text-xs text-muted-foreground">How many days apart a bill and its payment can be and still be suggested as a match.</p>
            <Select aria-label="Matching window" className="w-40" disabled={!isAdmin} value={String(cfg.date_window_days ?? 3)} onChange={(e) => patch.mutate({ matching_config: { ...cfg, date_window_days: Number(e.target.value) } })}>
              {[1, 2, 3, 5, 7, 10].map((d) => (
                <option key={d} value={d}>
                  ±{d} day{d > 1 ? "s" : ""}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex items-start justify-between gap-3 rounded-md border p-3">
            <div>
              <p className="text-sm font-medium">AI-assisted suggestions</p>
              <p className="text-xs text-muted-foreground">Off by default. When on (and set up by the server administrator), bill text may be sent to an AI provider for suggestions only. Matching and totals never depend on AI.</p>
            </div>
            <Switch checked={!!detail.data?.ai_opt_in} disabled={!isAdmin} onCheckedChange={(v) => patch.mutate({ ai_opt_in: v })} aria-label="AI-assisted suggestions" />
          </div>
        </CardContent>
      </Card>

      <div className="grid content-start gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Sharing</CardTitle>
            <CardDescription>
              {solo
                ? "Only you can see this workspace. Share it if someone else should see or add expenses, such as a partner, a family member or your accountant."
                : "People who can open this workspace."}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <ul className="divide-y text-sm">
              {people.map((m) => (
                <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-2">
                  <Avatar name={m.full_name || m.email} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">
                      {m.full_name} {m.user_id === me?.user.id && <span className="font-normal text-muted-foreground">(you)</span>}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{m.email}</p>
                  </div>
                  {isAdmin && !solo ? (
                    <Select aria-label={`Access for ${m.email}`} className="w-28" value={m.role} onChange={(e) => role.mutate({ uid: m.user_id, r: e.target.value })}>
                      {["owner", "admin", "member", "viewer"].map((r) => (
                        <option key={r} value={r}>
                          {label(r)}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Badge>{label(m.role)}</Badge>
                  )}
                  {!solo && (isAdmin || m.user_id === me?.user.id) && (
                    <Button size="icon" variant="ghost" aria-label={m.user_id === me?.user.id ? "Leave this workspace" : `Remove ${m.email}`} onClick={() => remove.mutate(m.user_id)}>
                      <Trash2 />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            {isAdmin && (
              <form
                className="grid gap-2 border-t pt-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  add.mutate();
                }}
              >
                <p className="text-sm font-medium">Give someone access</p>
                <div className="flex flex-wrap gap-2">
                  <Input aria-label="Their email" className="min-w-48 flex-1" type="email" required placeholder="Their SmartSpend email" value={invite.email} onChange={(e) => setInvite((x) => ({ ...x, email: e.target.value }))} />
                  <Select aria-label="Access level" className="w-28" value={invite.role} onChange={(e) => setInvite((x) => ({ ...x, role: e.target.value }))}>
                    <option value="admin">Admin</option>
                    <option value="member">Member</option>
                    <option value="viewer">Viewer</option>
                  </Select>
                  <Button type="submit" loading={add.isPending}>
                    <UserPlus /> Share
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  They need a SmartSpend account first. {label(invite.role)}: {ROLE_HELP[invite.role].toLowerCase()}.
                </p>
              </form>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Your workspaces</CardTitle>
            <CardDescription>Most people need just one. Add another to keep, say, business expenses completely separate.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <ul className="grid gap-2">
              {(me?.households ?? []).map((h) => (
                <li key={h.id} className={cn("flex items-center gap-3 rounded-md border p-2.5 text-sm", h.id === household?.id && "border-primary/50 bg-accent/40")}>
                  <Avatar name={h.name} square />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{h.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {label(h.role)} · {h.base_currency}
                    </p>
                  </div>
                  {h.id === household?.id ? (
                    <Badge tone="success">Current</Badge>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => switchHousehold(h.id)}>
                      Switch
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            {creating ? (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  create.mutate();
                }}
              >
                <Input autoFocus aria-label="New workspace name" placeholder="e.g. Business, Family" value={newName} onChange={(e) => setNewName(e.target.value)} />
                <Button type="submit" disabled={!newName.trim()} loading={create.isPending}>
                  Create
                </Button>
                <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                  Cancel
                </Button>
              </form>
            ) : (
              <Button variant="outline" className="w-fit" onClick={() => setCreating(true)}>
                <Plus /> New workspace
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Integrations() {
  const list = useQuery({ queryKey: ["integrations"], queryFn: () => api<any[]>("/integrations") });
  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle>Integrations</CardTitle>
        <CardDescription>Automatic data sources. None is connected yet — use statement imports and uploads in the meantime.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-2 sm:grid-cols-2">
          {(list.data ?? []).map((i) => (
            <li key={i.key} className="flex items-center justify-between rounded-md border p-3 text-sm">
              <span>{i.name}</span>
              <Badge tone={i.configured ? "success" : "default"}>{i.configured ? "Active" : "Not configured"}</Badge>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function Privacy() {
  const { isAdmin } = useAuth();
  const nav = useNavigate();
  const [busy, setBusy] = React.useState(false);
  const [del, setDel] = React.useState(false);
  const [pw, setPw] = React.useState("");
  const [confirmText, setConfirmText] = React.useState("");
  const remove = useMutation({
    mutationFn: () => api("/me", { method: "DELETE", body: { password: pw, confirm: confirmText } }),
    onSuccess: () => {
      session.setToken(null);
      toast.success("Your account and your unshared workspaces were deleted.");
      nav("/login");
      window.location.reload();
    },
    onError: err,
  });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Export your data</CardTitle>
          <CardDescription>A ZIP with every record in this workspace as JSON, plus the original uploaded documents.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            disabled={!isAdmin}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await download("/me/export", "smartspend-export.zip");
              } catch (e) {
                err(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Download /> Download export
          </Button>
          {!isAdmin && <p className="mt-2 text-xs text-muted-foreground">Only owners and admins can export a workspace's data.</p>}
        </CardContent>
      </Card>
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle>Delete account</CardTitle>
          <CardDescription>Deletes your login and every workspace only you use, including uploaded files. Workspaces shared with others stay with them. This can't be undone.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={() => setDel(true)}>
            <Trash2 /> Delete my account
          </Button>
        </CardContent>
      </Card>
      <Integrations />
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>How your data is handled</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-1 text-sm text-muted-foreground">
          <p>• Documents are stored privately and only reachable through short-lived signed links.</p>
          <p>• PINs, banking passwords and card security codes are never requested or stored.</p>
          <p>• Documents are never sent to third-party AI services unless an administrator configures it and the workspace turns on AI suggestions.</p>
          <p>
            • See the <Link className="text-primary underline" to="/reconciliation">reconciliation audit history</Link> for every link, merge and unlink decision.
          </p>
        </CardContent>
      </Card>
      <ConfirmDialog
        open={del}
        onOpenChange={setDel}
        destructive
        title="Delete your account permanently?"
        description="Enter your password and type DELETE to confirm."
        confirmLabel="Delete everything"
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
      >
        <div className="grid gap-2">
          <Input aria-label="Password" type="password" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
          <Input aria-label="Type DELETE" placeholder="Type DELETE" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
        </div>
      </ConfirmDialog>
    </div>
  );
}

export function SettingsPage() {
  const { me } = useAuth();
  const [tab, setTab] = React.useState<"security" | "workspace" | "privacy">("workspace");
  return (
    <>
      <PageHeader title="Settings" description={me ? `${me.user.full_name} · ${me.user.email}` : undefined} />
      <div className="mb-4 flex gap-1 rounded-lg bg-muted p-1 w-fit" role="tablist">
        {(["workspace", "security", "privacy"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("rounded-md px-3 py-1 text-sm font-medium cursor-pointer", tab === t ? "bg-card shadow-sm" : "text-muted-foreground")}>
            {label(t === "privacy" ? "Data & privacy" : t)}
          </button>
        ))}
      </div>
      {tab === "workspace" && <WorkspaceSettings />}
      {tab === "security" && <Security />}
      {tab === "privacy" && <Privacy />}
    </>
  );
}

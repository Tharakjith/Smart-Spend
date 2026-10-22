import * as Popover from "@radix-ui/react-popover";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCheck } from "lucide-react";
import * as React from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { cn, dateTime } from "@/lib/format";

type Notification = { id: string; title: string; body?: string; severity: string; read: boolean; link?: string; created_at: string };

const SEVERITY_DOT: Record<string, string> = { critical: "bg-destructive", warning: "bg-amber-500", info: "bg-primary" };

export function NotificationBell({ enabled, className }: { enabled: boolean; className?: string }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = React.useState(false);
  const count = useQuery({
    queryKey: ["notif-count"],
    queryFn: () => api<{ total: number }>("/notifications?unread=true&page_size=1").catch(() => ({ total: 0 })),
    refetchInterval: 60_000,
    enabled,
  });
  const recent = useQuery({
    queryKey: ["notifications", "bell"],
    queryFn: () => api<{ items: Notification[] }>("/notifications?page_size=8"),
    enabled: enabled && open,
  });
  const unread = count.data?.total ?? 0;
  // Ring once whenever the unread count goes up (not on first load).
  const prev = React.useRef<number | null>(null);
  const [rings, setRings] = React.useState(0);
  React.useEffect(() => {
    if (prev.current !== null && unread > prev.current) setRings((r) => r + 1);
    prev.current = unread;
  }, [unread]);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["notifications"] });
    qc.invalidateQueries({ queryKey: ["notif-count"] });
  };
  const openOne = async (n: Notification) => {
    if (!n.read) await api(`/notifications/${n.id}/read`, { method: "POST" }).catch(() => undefined);
    refresh();
    setOpen(false);
    if (n.link) nav(n.link);
  };
  const readAll = async () => {
    await api("/notifications/read-all", { method: "POST" }).catch(() => undefined);
    refresh();
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
          className={cn("relative inline-flex size-9 items-center justify-center rounded-md text-muted-foreground transition-[color,background-color,transform] hover:bg-muted hover:text-foreground active:scale-90 cursor-pointer", className)}
        >
          <Bell key={rings} className={cn("size-5", rings > 0 && "animate-ring")} aria-hidden />
          {unread > 0 && (
            <span key={unread} className="animate-badge absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-destructive px-1 text-center text-[11px] font-semibold leading-[18px] text-white">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="start" sideOffset={8} collisionPadding={12} className="popover-motion z-50 w-[min(22rem,calc(100vw-24px))] rounded-lg border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <p className="text-sm font-semibold">Notifications</p>
            {unread > 0 && (
              <button type="button" onClick={readAll} className="inline-flex items-center gap-1 text-xs text-primary hover:underline cursor-pointer">
                <CheckCheck className="size-3.5" /> Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {recent.isLoading ? (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">Loading…</p>
            ) : (recent.data?.items ?? []).length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">You're all caught up</p>
            ) : (
              <ul>
                {recent.data!.items.map((n) => (
                  <li key={n.id} className="border-b last:border-b-0">
                    <button type="button" onClick={() => openOne(n)} className="flex w-full items-start gap-2 px-3 py-2.5 text-left hover:bg-muted cursor-pointer">
                      <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.read ? "bg-transparent" : (SEVERITY_DOT[n.severity] ?? "bg-primary"))} aria-label={n.read ? undefined : "Unread"} />
                      <span className="min-w-0 flex-1">
                        <span className={cn("block text-sm", !n.read && "font-medium")}>{n.title}</span>
                        {n.body && <span className="block truncate text-xs text-muted-foreground">{n.body}</span>}
                        <span className="block text-[11px] text-muted-foreground">{dateTime(n.created_at)}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <Link to="/notifications" onClick={() => setOpen(false)} className="block border-t px-3 py-2 text-center text-sm font-medium text-primary hover:bg-muted">
            View all notifications
          </Link>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

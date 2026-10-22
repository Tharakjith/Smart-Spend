import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Bell,
  CalendarClock,
  ChartPie,
  CreditCard,
  GitCompareArrows,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  PiggyBank,
  Settings,
  Sun,
  Tags,
  Upload,
  Users,
  Wallet,
  X,
} from "lucide-react";
import * as React from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/format";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/transactions", label: "Transactions", icon: ArrowLeftRight },
  { to: "/upload", label: "Upload Bills", icon: Upload },
  { to: "/people", label: "People & Shared", icon: Users },
  { to: "/reconciliation", label: "Duplicates & Reconciliation", icon: GitCompareArrows, badge: "recon" },
  { to: "/budgets", label: "Budgets", icon: PiggyBank },
  { to: "/recurring", label: "Recurring Expenses", icon: CalendarClock },
  { to: "/accounts", label: "Accounts", icon: Wallet },
  { to: "/credit-cards", label: "Credit Cards", icon: CreditCard, badge: "cards" },
  { to: "/analytics", label: "Analytics & Reports", icon: ChartPie },
  { to: "/categories", label: "Categories & Rules", icon: Tags },
  { to: "/notifications", label: "Notifications", icon: Bell, badge: "notif" },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

function useTheme() {
  const [dark, setDark] = React.useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("ss-theme", next ? "dark" : "light");
    } catch {
      /* ignore */
    }
    setDark(next);
  };
  return { dark, toggle };
}

export function AppLayout() {
  const { me, household, switchHousehold, logout } = useAuth();
  const { dark, toggle } = useTheme();
  const [open, setOpen] = React.useState(false);
  const loc = useLocation();
  React.useEffect(() => setOpen(false), [loc.pathname]);

  const recon = useQuery({ queryKey: ["recon-summary"], queryFn: () => api("/reconciliation/summary"), refetchInterval: 60_000, enabled: !!household });
  const notif = useQuery({ queryKey: ["notif-count"], queryFn: () => api("/notifications?unread=true&page_size=1").catch(() => ({ total: 0 })), refetchInterval: 60_000, enabled: !!household });
  const cards = useQuery({ queryKey: ["cards"], queryFn: () => api<any[]>("/credit-cards"), refetchInterval: 300_000, enabled: !!household });
  const badges: Record<string, number> = {
    recon: (recon.data?.suggestions?.high ?? 0) + (recon.data?.suggestions?.medium ?? 0) + (recon.data?.conflicts ?? 0),
    notif: notif.data?.total ?? 0,
    // Card bills that are overdue or due within 5 days and not fully paid.
    cards: (cards.data ?? []).filter((c) => c.last_statement && !["paid", "no_dues"].includes(c.last_statement.status) && c.last_statement.days_until_due <= 5).length,
  };

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col gap-1 p-3">
      <div className="mb-3 flex items-center gap-2 px-2 py-1">
        <img src="/favicon.svg" alt="" className="size-7" />
        <span className="text-lg font-semibold">SmartSpend</span>
      </div>
      {me && me.households.length > 1 && (
        <Select aria-label="Household" value={household?.id} onChange={(e) => switchHousehold(e.target.value)} className="mb-2">
          {me.households.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </Select>
      )}
      {NAV.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={"end" in n ? n.end : false}
          className={({ isActive }) =>
            cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground", isActive && "bg-accent text-accent-foreground")
          }
        >
          <n.icon className="size-4 shrink-0" aria-hidden />
          <span className="flex-1 truncate">{n.label}</span>
          {"badge" in n && badges[n.badge] > 0 && <span className="rounded-full bg-primary px-1.5 text-[11px] font-semibold text-primary-foreground">{badges[n.badge]}</span>}
        </NavLink>
      ))}
      <div className="mt-auto border-t pt-3">
        <p className="truncate px-3 text-sm font-medium">{me?.user.full_name}</p>
        <p className="truncate px-3 text-xs text-muted-foreground">
          {household?.name} · {household?.role}
        </p>
        <div className="mt-2 flex gap-1 px-1">
          <Button variant="ghost" size="icon" onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
            {dark ? <Sun /> : <Moon />}
          </Button>
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut /> Sign out
          </Button>
        </div>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen">
      {(household?.is_demo || me?.demo_mode) && (
        <div className="bg-amber-500 px-4 py-1.5 text-center text-xs font-semibold text-amber-950" role="status">
          Demo environment — the data shown here is sample data, not real financial records.
        </div>
      )}
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-card focus:p-2">
        Skip to content
      </a>
      <div className="flex">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r bg-card lg:block">{sidebar}</aside>
        {open && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
            <aside className="absolute inset-y-0 left-0 w-72 overflow-y-auto bg-card shadow-xl">
              <Button variant="ghost" size="icon" className="absolute right-2 top-2" onClick={() => setOpen(false)} aria-label="Close menu">
                <X />
              </Button>
              {sidebar}
            </aside>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-card/90 px-4 py-2 backdrop-blur lg:hidden">
            <Button variant="ghost" size="icon" onClick={() => setOpen(true)} aria-label="Open menu">
              <Menu />
            </Button>
            <span className="font-semibold">SmartSpend</span>
          </header>
          <main id="main" className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}

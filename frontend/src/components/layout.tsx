import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeftRight,
  CalendarClock,
  ChartPie,
  CreditCard,
  GitCompareArrows,
  LayoutDashboard,
  LogOut,
  Menu,
  MoreHorizontal,
  Moon,
  PiggyBank,
  Plus,
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
import { AddTransactionDialog } from "@/components/add-transaction";
import { Avatar } from "@/components/avatar";
import { NotificationBell } from "@/components/notification-bell";
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
  const { me, household, switchHousehold, logout, canWrite } = useAuth();
  const { dark, toggle } = useTheme();
  const [open, setOpen] = React.useState(false);
  const [adding, setAdding] = React.useState(false);
  const loc = useLocation();
  React.useEffect(() => setOpen(false), [loc.pathname]);

  const recon = useQuery({ queryKey: ["recon-summary"], queryFn: () => api("/reconciliation/summary"), refetchInterval: 60_000, enabled: !!household });
  const cards = useQuery({ queryKey: ["cards"], queryFn: () => api<any[]>("/credit-cards"), refetchInterval: 300_000, enabled: !!household });
  const badges: Record<string, number> = {
    recon: (recon.data?.suggestions?.high ?? 0) + (recon.data?.suggestions?.medium ?? 0) + (recon.data?.conflicts ?? 0),
    // Card bills that are overdue or due within 5 days and not fully paid.
    cards: (cards.data ?? []).filter((c) => c.last_statement && !["paid", "no_dues"].includes(c.last_statement.status) && c.last_statement.days_until_due <= 5).length,
  };

  // The drawer copy has its own close button where the bell would sit; the mobile header carries the bell instead.
  const sidebar = (inDrawer: boolean) => (
    <nav aria-label="Main" className="flex h-full flex-col gap-1 p-3">
      <div className="mb-3 flex items-center gap-2 px-2 py-1">
        <img src="/favicon.svg" alt="" className="size-7" />
        <span className="text-lg font-semibold">SmartSpend</span>
        {!inDrawer && <NotificationBell enabled={!!household} className="ml-auto" />}
      </div>
      {me && me.households.length > 1 && (
        <Select aria-label="Workspace" title="Switch workspace" value={household?.id} onChange={(e) => switchHousehold(e.target.value)} className="mb-2">
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
            cn(
              "group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground",
              isActive && "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground",
            )
          }
        >
          <n.icon className="size-4 shrink-0 transition-transform duration-200 group-hover:scale-110" aria-hidden />
          <span className="flex-1 leading-tight">{n.label}</span>
          {"badge" in n && badges[n.badge] > 0 && (
            <span key={badges[n.badge]} className="animate-badge rounded-full bg-primary px-1.5 text-[11px] font-semibold text-primary-foreground">
              {badges[n.badge]}
            </span>
          )}
        </NavLink>
      ))}
      <div className="mt-auto border-t pt-3">
        <NavLink to="/settings" className="flex items-center gap-3 rounded-md px-2 py-1.5 transition-colors hover:bg-muted" title="Workspace and account settings">
          <Avatar name={me?.user.full_name || me?.user.email || ""} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{me?.user.full_name}</span>
            <span className="block truncate text-xs text-muted-foreground">
              {household?.name}
              {/* The role only matters in a shared workspace you don't own. */}
              {household && household.role !== "owner" && ` · ${household.role}`}
            </span>
          </span>
        </NavLink>
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
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r bg-card lg:block">{sidebar(false)}</aside>
        {/* Phone menu: stays mounted so it can slide in and out; inert while closed. */}
        <div className={cn("fixed inset-0 z-40 lg:hidden", !open && "pointer-events-none")} inert={!open} aria-hidden={!open}>
          <div className={cn("absolute inset-0 bg-black/50 transition-opacity duration-300", open ? "opacity-100" : "opacity-0")} onClick={() => setOpen(false)} />
          <aside
            className={cn(
              "absolute inset-y-0 left-0 w-[min(18rem,85vw)] overflow-y-auto bg-card shadow-xl transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
              open ? "translate-x-0" : "-translate-x-full",
            )}
          >
            <Button variant="ghost" size="icon" className="absolute right-2 top-2" onClick={() => setOpen(false)} aria-label="Close menu">
              <X />
            </Button>
            {sidebar(true)}
          </aside>
        </div>
        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-card/90 px-4 py-2 backdrop-blur lg:hidden">
            <Button variant="ghost" size="icon" onClick={() => setOpen(true)} aria-label="Open menu">
              <Menu />
            </Button>
            <img src="/favicon.svg" alt="" className="size-6" />
            <span className="font-semibold">SmartSpend</span>
            <NotificationBell enabled={!!household} className="ml-auto" />
          </header>
          <main id="main" className="mx-auto w-full max-w-7xl px-4 pb-28 pt-5 sm:px-6 sm:pt-6 lg:px-8 lg:pb-8">
            {/* Re-keyed per page so each page eases in. */}
            <div key={loc.pathname} className="animate-page">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
      <BottomNav onMore={() => setOpen(true)} onAdd={canWrite ? () => setAdding(true) : undefined} />
      <AddTransactionDialog open={adding} onOpenChange={setAdding} />
    </div>
  );
}

const TABS = [
  { to: "/", label: "Home", icon: LayoutDashboard, end: true },
  { to: "/transactions", label: "Activity", icon: ArrowLeftRight },
  { to: "/upload", label: "Bills", icon: Upload },
] as const;

/** Phones and tablets: the most used pages one tap away, with a big "add" button in the middle. */
function BottomNav({ onMore, onAdd }: { onMore: () => void; onAdd?: () => void }) {
  const item = "flex flex-1 flex-col items-center gap-0.5 py-1.5 text-[11px] font-medium transition-colors duration-150";
  const tab = (t: (typeof TABS)[number]) => (
    <NavLink key={t.to} to={t.to} end={"end" in t ? t.end : false} className={({ isActive }) => cn(item, isActive ? "text-primary" : "text-muted-foreground hover:text-foreground")}>
      {({ isActive }) => (
        <>
          <span className={cn("flex h-7 w-12 items-center justify-center rounded-full transition-all duration-300", isActive && "bg-accent")}>
            <t.icon className="size-5" aria-hidden />
          </span>
          {t.label}
        </>
      )}
    </NavLink>
  );
  return (
    <nav aria-label="Quick navigation" className="fixed inset-x-0 bottom-0 z-30 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
      <div className="mx-auto flex max-w-lg items-end px-2">
        {tab(TABS[0])}
        {tab(TABS[1])}
        {onAdd && (
          <div className="flex flex-1 justify-center">
            <button
              type="button"
              onClick={onAdd}
              aria-label="Add transaction"
              className="-mt-6 mb-1 inline-flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg shadow-primary/30 ring-4 ring-background transition-transform duration-150 hover:scale-105 active:scale-95 cursor-pointer"
            >
              <Plus className="size-6" aria-hidden />
            </button>
          </div>
        )}
        {tab(TABS[2])}
        <button type="button" onClick={onMore} className={cn(item, "text-muted-foreground hover:text-foreground cursor-pointer")}>
          <span className="flex h-7 w-12 items-center justify-center">
            <MoreHorizontal className="size-5" aria-hidden />
          </span>
          More
        </button>
      </div>
    </nav>
  );
}

import { Loader2 } from "lucide-react";
import * as React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "@/components/layout";
import { Skeleton } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { ForgotPasswordPage, LoginPage, RegisterPage, ResetPasswordPage, VerifyEmailPage } from "@/pages/auth";

// Each section is its own chunk so the first load stays small.
const page = <K extends string>(loader: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  React.lazy(() => loader().then((m) => ({ default: m[name] })));
const DashboardPage = page(() => import("@/pages/dashboard"), "DashboardPage");
const TransactionsPage = page(() => import("@/pages/transactions"), "TransactionsPage");
const UploadPage = page(() => import("@/pages/upload"), "UploadPage");
const PeoplePage = page(() => import("@/pages/people"), "PeoplePage");
const ReconciliationPage = page(() => import("@/pages/reconciliation"), "ReconciliationPage");
const BudgetsPage = page(() => import("@/pages/planning"), "BudgetsPage");
const RecurringPage = page(() => import("@/pages/planning"), "RecurringPage");
const AccountsPage = page(() => import("@/pages/accounts"), "AccountsPage");
const CardsPage = page(() => import("@/pages/cards"), "CardsPage");
const AnalyticsPage = page(() => import("@/pages/analytics"), "AnalyticsPage");
const CategoriesPage = page(() => import("@/pages/categories"), "CategoriesPage");
const NotificationsPage = page(() => import("@/pages/settings"), "NotificationsPage");
const SettingsPage = page(() => import("@/pages/settings"), "SettingsPage");

function Protected({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  if (status === "loading")
    return (
      <div className="flex min-h-screen items-center justify-center" role="status">
        <Loader2 className="size-6 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    );
  if (status === "anonymous") return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function PublicOnly({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  if (status === "authenticated") return <Navigate to="/" replace />;
  return <>{children}</>;
}

const Lazy = ({ children }: { children: React.ReactNode }) => (
  <React.Suspense
    fallback={
      <div className="grid gap-3" role="status" aria-label="Loading page">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40" />
      </div>
    }
  >
    {children}
  </React.Suspense>
);

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<PublicOnly><LoginPage /></PublicOnly>} />
      <Route path="/register" element={<PublicOnly><RegisterPage /></PublicOnly>} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route element={<Protected><AppLayout /></Protected>}>
        <Route index element={<Lazy><DashboardPage /></Lazy>} />
        <Route path="transactions" element={<Lazy><TransactionsPage /></Lazy>} />
        <Route path="upload" element={<Lazy><UploadPage /></Lazy>} />
        <Route path="people" element={<Lazy><PeoplePage /></Lazy>} />
        <Route path="reconciliation" element={<Lazy><ReconciliationPage /></Lazy>} />
        <Route path="budgets" element={<Lazy><BudgetsPage /></Lazy>} />
        <Route path="recurring" element={<Lazy><RecurringPage /></Lazy>} />
        <Route path="accounts" element={<Lazy><AccountsPage /></Lazy>} />
        <Route path="credit-cards" element={<Lazy><CardsPage /></Lazy>} />
        <Route path="analytics" element={<Lazy><AnalyticsPage /></Lazy>} />
        <Route path="categories" element={<Lazy><CategoriesPage /></Lazy>} />
        <Route path="notifications" element={<Lazy><NotificationsPage /></Lazy>} />
        <Route path="settings" element={<Lazy><SettingsPage /></Lazy>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { api, refreshSession, session } from "@/lib/api";

export type Household = { id: string; name: string; role: "owner" | "admin" | "member" | "viewer"; base_currency: string; timezone: string; is_demo: boolean };
export type Me = { user: { id: string; email: string; full_name: string; email_verified: boolean; mfa_enabled: boolean }; households: Household[]; demo_mode: boolean };

type AuthState = {
  status: "loading" | "anonymous" | "authenticated";
  me: Me | null;
  household: Household | null;
  login: (accessToken: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
  switchHousehold: (id: string) => void;
  canWrite: boolean;
  isAdmin: boolean;
};

const Ctx = React.createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = React.useState<AuthState["status"]>("loading");
  const [me, setMe] = React.useState<Me | null>(null);
  const [hid, setHid] = React.useState<string | null>(session.household());

  const loadMe = React.useCallback(async () => {
    const data = await api<Me>("/auth/me");
    setMe(data);
    const current = data.households.find((h) => h.id === session.household()) ?? data.households[0] ?? null;
    session.setHousehold(current?.id ?? null);
    setHid(current?.id ?? null);
    setStatus("authenticated");
  }, []);

  React.useEffect(() => {
    session.onAuthLost(() => {
      setStatus("anonymous");
      setMe(null);
      qc.clear();
    });
    (async () => {
      if (await refreshSession()) {
        try {
          await loadMe();
          return;
        } catch {
          /* fall through */
        }
      }
      setStatus("anonymous");
    })();
  }, [loadMe, qc]);

  const value: AuthState = React.useMemo(() => {
    const household = me?.households.find((h) => h.id === hid) ?? null;
    return {
      status,
      me,
      household,
      canWrite: !!household && household.role !== "viewer",
      isAdmin: !!household && (household.role === "owner" || household.role === "admin"),
      login: async (token: string) => {
        session.setToken(token);
        await loadMe();
      },
      logout: async () => {
        try {
          await api("/auth/logout", { method: "POST" });
        } finally {
          session.setToken(null);
          setMe(null);
          setStatus("anonymous");
          qc.clear();
        }
      },
      reload: loadMe,
      switchHousehold: (id: string) => {
        session.setHousehold(id);
        setHid(id);
        qc.clear();
      },
    };
  }, [status, me, hid, loadMe, qc]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = React.useContext(Ctx);
  if (!v) throw new Error("useAuth outside provider");
  return v;
}

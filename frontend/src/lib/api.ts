/** API client. Access token lives in memory only; the refresh token is an httpOnly cookie. */

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let accessToken: string | null = null;
let householdId: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onAuthLost: (() => void) | null = null;

try {
  householdId = localStorage.getItem("ss-household");
} catch {
  /* storage unavailable */
}

export const session = {
  setToken(t: string | null) {
    accessToken = t;
  },
  hasToken: () => accessToken !== null,
  setHousehold(id: string | null) {
    householdId = id;
    try {
      if (id) localStorage.setItem("ss-household", id);
      else localStorage.removeItem("ss-household");
    } catch {
      /* ignore */
    }
  },
  household: () => householdId,
  onAuthLost(cb: () => void) {
    onAuthLost = cb;
  },
};

function csrf(): string {
  const m = document.cookie.match(/(?:^|; )ss_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export async function refreshSession(): Promise<boolean> {
  // The CSRF cookie accompanies every refresh session; without it there is nothing to refresh.
  if (!csrf()) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include", headers: { "X-CSRF-Token": csrf() } });
        if (!r.ok) return false;
        const body = await r.json();
        accessToken = body.access_token;
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

type Opts = { method?: string; body?: unknown; form?: FormData; idempotent?: boolean; raw?: boolean; signal?: AbortSignal };

export async function api<T = any>(path: string, opts: Opts = {}, retried = false): Promise<T> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (householdId) headers["X-Household-ID"] = householdId;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.idempotent) headers["Idempotency-Key"] = crypto.randomUUID();
  if (path.startsWith("/auth/")) headers["X-CSRF-Token"] = csrf();
  const res = await fetch(`/api/v1${path}`, {
    method: opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET"),
    headers,
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    credentials: "include",
    signal: opts.signal,
  });
  if (res.status === 401 && !retried && !path.startsWith("/auth/login") && !path.startsWith("/auth/refresh")) {
    if (await refreshSession()) return api<T>(path, opts, true);
    accessToken = null;
    onAuthLost?.();
  }
  if (!res.ok) {
    let code = "http_error";
    let message = `Request failed (${res.status})`;
    let details = {};
    try {
      const body = await res.json();
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
      details = body.error?.details ?? {};
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code, message, details);
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function download(path: string, fallbackName: string) {
  const res = await api<Response>(path, { raw: true });
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^"]+)"?/.exec(cd)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

import { zodResolver } from "@hookform/resolvers/zod";
import * as React from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input, Select } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function Shell({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center justify-center gap-2">
          <img src="/favicon.svg" alt="" className="size-9" />
          <span className="text-2xl font-semibold">SmartSpend</span>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">{title}</CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </CardHeader>
          <CardContent>{children}</CardContent>
        </Card>
      </div>
    </div>
  );
}

const loginSchema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Enter your password") });

export function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [mfaToken, setMfaToken] = React.useState<string | null>(null);
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const form = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) });

  const onSubmit = form.handleSubmit(async (values) => {
    setBusy(true);
    try {
      const r = await api("/auth/login", { body: values });
      if (r.mfa_required) {
        setMfaToken(r.mfa_token);
        return;
      }
      await login(r.access_token);
      nav("/");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  });

  const verifyMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api("/auth/mfa/verify", { body: { mfa_token: mfaToken, code } });
      await login(r.access_token);
      nav("/");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Verification failed");
    } finally {
      setBusy(false);
    }
  };

  if (mfaToken)
    return (
      <Shell title="Two-factor verification" description="Enter the 6-digit code from your authenticator app.">
        <form onSubmit={verifyMfa} className="grid gap-4">
          <Field label="Verification code" htmlFor="code">
            <Input id="code" inputMode="numeric" autoComplete="one-time-code" autoFocus value={code} onChange={(e) => setCode(e.target.value.trim())} maxLength={8} />
          </Field>
          <Button type="submit" loading={busy}>
            Verify
          </Button>
        </form>
      </Shell>
    );

  return (
    <Shell title="Sign in" description="Track every expense once — receipts and payments reconciled.">
      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        <Field label="Email" htmlFor="email" error={form.formState.errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!form.formState.errors.email} {...form.register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={form.formState.errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!form.formState.errors.password} {...form.register("password")} />
        </Field>
        <Button type="submit" loading={busy}>
          Sign in
        </Button>
        <div className="flex justify-between text-sm">
          <Link to="/forgot-password" className="text-primary hover:underline">
            Forgot password?
          </Link>
          <Link to="/register" className="text-primary hover:underline">
            Create an account
          </Link>
        </div>
      </form>
    </Shell>
  );
}

const CURRENCIES = [
  ["INR", "Indian rupee"],
  ["USD", "US dollar"],
  ["EUR", "Euro"],
  ["GBP", "British pound"],
  ["AED", "UAE dirham"],
  ["SAR", "Saudi riyal"],
  ["SGD", "Singapore dollar"],
  ["AUD", "Australian dollar"],
  ["CAD", "Canadian dollar"],
  ["JPY", "Japanese yen"],
] as const;

const registerSchema = z
  .object({
    full_name: z.string().min(1, "Enter your name"),
    email: z.string().email("Enter a valid email"),
    password: z
      .string()
      .min(10, "At least 10 characters")
      .regex(/[a-z]/, "Include a lower-case letter")
      .regex(/[A-Z]/, "Include an upper-case letter")
      .regex(/\d/, "Include a digit"),
    confirm: z.string(),
    household_name: z.string().optional(),
    base_currency: z.string().length(3),
  })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords don't match" });

export function RegisterPage() {
  const nav = useNavigate();
  const { login } = useAuth();
  const [busy, setBusy] = React.useState(false);
  const form = useForm<z.infer<typeof registerSchema>>({ resolver: zodResolver(registerSchema), defaultValues: { base_currency: "INR" } });
  const errors = form.formState.errors;
  const onSubmit = form.handleSubmit(async ({ confirm: _c, ...values }) => {
    setBusy(true);
    try {
      const r = await api("/auth/register", { body: { ...values, household_name: values.household_name || undefined } });
      if (r.verification_required) {
        toast.success("Account created. Check your email for a verification link.");
        nav("/login");
        return;
      }
      const l = await api("/auth/login", { body: { email: values.email, password: values.password } });
      await login(l.access_token);
      nav("/");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  });
  return (
    <Shell title="Create your account" description="Track every expense once, with bills and payments matched automatically.">
      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        <Field label="Full name" htmlFor="full_name" error={errors.full_name?.message}>
          <Input id="full_name" autoComplete="name" {...form.register("full_name")} />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" {...form.register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message} hint="10+ characters with upper- and lower-case letters and a digit.">
          <Input id="password" type="password" autoComplete="new-password" {...form.register("password")} />
        </Field>
        <Field label="Confirm password" htmlFor="confirm" error={errors.confirm?.message}>
          <Input id="confirm" type="password" autoComplete="new-password" {...form.register("confirm")} />
        </Field>
        <Field label="Currency" htmlFor="base_currency" error={errors.base_currency?.message}>
          <Select id="base_currency" {...form.register("base_currency")}>
            {CURRENCIES.map(([code, name]) => (
              <option key={code} value={code}>
                {code} · {name}
              </option>
            ))}
          </Select>
        </Field>
        <details className="group rounded-md border px-3 py-2 text-sm">
          <summary className="cursor-pointer select-none text-muted-foreground">Name your workspace (optional)</summary>
          <div className="mt-3 pb-1">
            <Field label="Workspace name" htmlFor="household_name" hint="Defaults to your first name, e.g. “Asha's Workspace”. You can rename it or share it with family later.">
              <Input id="household_name" placeholder="e.g. Personal, Family, Business" {...form.register("household_name")} />
            </Field>
          </div>
        </details>
        <Button type="submit" loading={busy}>
          Create account
        </Button>
        <p className="text-center text-sm">
          Already registered?{" "}
          <Link to="/login" className="text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </Shell>
  );
}

type Delivery = "email" | "dev_mailbox" | "not_configured";
type DevMail = { subject: string; body: string };

export function ForgotPasswordPage() {
  const nav = useNavigate();
  const [email, setEmail] = React.useState("");
  const [delivery, setDelivery] = React.useState<Delivery | null>(null);
  const [devMail, setDevMail] = React.useState<DevMail | null>(null);
  const [code, setCode] = React.useState("");
  const [pw, setPw] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const send = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    try {
      const r = await api<{ ok: boolean; delivery: Delivery }>("/auth/forgot-password", { body: { email } });
      setDelivery(r.delivery);
      setCode("");
      setDevMail(null);
      if (r.delivery === "dev_mailbox") {
        // Local development without SMTP: show the email the server would have sent.
        const box = await api<{ items: DevMail[] }>(`/auth/dev-mailbox?email=${encodeURIComponent(email)}`);
        setDevMail(box.items[0] ?? null);
      } else if (e === undefined) {
        toast.success("A new code is on its way.");
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const reset = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/auth/reset-password", { body: { email, code, new_password: pw } });
      toast.success("Password updated. All sessions were signed out.");
      nav("/login");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  if (delivery === null) {
    return (
      <Shell title="Reset your password" description="We'll email a 6-digit code if the address is registered.">
        <form onSubmit={send} className="grid gap-4">
          <Field label="Email" htmlFor="email">
            <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" loading={busy}>
            Send code
          </Button>
        </form>
        <BackToSignIn />
      </Shell>
    );
  }

  return (
    <Shell title="Enter your code" description={`If an account exists for ${email}, we sent it a 6-digit code. It expires in 15 minutes.`}>
      {delivery === "dev_mailbox" && (
        <div className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          <p className="font-medium">Email sending isn't set up on this server</p>
          <p className="mt-1 text-muted-foreground">
            Development mode shows the message here instead. Configure SMTP (see docs/SETUP.md) to deliver real emails.
          </p>
          {devMail ? (
            <p className="mt-2">
              Your code: <span className="font-mono text-base font-semibold tracking-widest">{devMail.subject.split(" ")[0]}</span>
            </p>
          ) : (
            <p className="mt-2 text-muted-foreground">No account is registered with that address.</p>
          )}
        </div>
      )}
      {delivery === "not_configured" && (
        <p className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          This server can't send email yet, so no code was delivered. Ask the administrator to configure SMTP.
        </p>
      )}
      <form onSubmit={reset} className="grid gap-4">
        <Field label="6-digit code" htmlFor="code">
          <Input
            id="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            required
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            className="font-mono tracking-widest"
          />
        </Field>
        <Field label="New password" htmlFor="pw" hint="10+ characters with upper- and lower-case letters and a digit.">
          <Input id="pw" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} />
        </Field>
        <Button type="submit" loading={busy}>
          Update password
        </Button>
      </form>
      <div className="mt-4 flex items-center justify-between text-sm">
        <button type="button" className="text-primary hover:underline disabled:opacity-50" disabled={busy} onClick={() => send()}>
          Resend code
        </button>
        <button type="button" className="text-muted-foreground hover:underline" onClick={() => setDelivery(null)}>
          Use a different email
        </button>
      </div>
      <BackToSignIn />
    </Shell>
  );
}

function BackToSignIn() {
  return (
    <p className="mt-4 text-center text-sm">
      <Link to="/login" className="text-primary hover:underline">
        Back to sign in
      </Link>
    </p>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [pw, setPw] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/auth/reset-password", { body: { token: params.get("token"), new_password: pw } });
      toast.success("Password updated. All sessions were signed out.");
      nav("/login");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Shell title="Choose a new password">
      <form onSubmit={submit} className="grid gap-4">
        <Field label="New password" htmlFor="pw" hint="10+ characters with upper- and lower-case letters and a digit.">
          <Input id="pw" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} />
        </Field>
        <Button type="submit" loading={busy}>
          Update password
        </Button>
      </form>
    </Shell>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const [state, setState] = React.useState<"pending" | "ok" | "error">("pending");
  const [msg, setMsg] = React.useState("");
  React.useEffect(() => {
    api("/auth/verify-email", { body: { token: params.get("token") } })
      .then(() => setState("ok"))
      .catch((e) => {
        setState("error");
        setMsg(e.message);
      });
  }, [params]);
  return (
    <Shell title="Email verification">
      {state === "pending" && <p className="text-sm">Verifying…</p>}
      {state === "ok" && <p className="text-sm">Your email is verified. You can sign in now.</p>}
      {state === "error" && <p className="text-sm text-destructive">{msg}</p>}
      <p className="mt-4 text-sm">
        <Link to="/login" className="text-primary hover:underline">
          Go to sign in
        </Link>
      </p>
    </Shell>
  );
}

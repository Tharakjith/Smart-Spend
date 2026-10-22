import * as LabelPrimitive from "@radix-ui/react-label";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { AlertCircle, Inbox } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/format";

export function Card({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg border bg-card text-card-foreground shadow-sm", className)} {...p} />;
}
export function CardHeader({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 p-5 pb-3", className)} {...p} />;
}
export function CardTitle({ className, ...p }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-base font-semibold leading-tight", className)} {...p} />;
}
export function CardDescription({ className, ...p }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...p} />;
}
export function CardContent({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 pt-0", className)} {...p} />;
}

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input
    ref={ref}
    className={cn(
      "flex h-9 w-full rounded-md border border-input bg-card px-3 py-1 text-sm shadow-xs placeholder:text-muted-foreground disabled:opacity-50 aria-[invalid=true]:border-destructive",
      className,
    )}
    {...p}
  />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn("flex min-h-16 w-full rounded-md border border-input bg-card px-3 py-2 text-sm placeholder:text-muted-foreground", className)} {...p} />
));
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...p }, ref) => (
  <select ref={ref} className={cn("flex h-9 w-full rounded-md border border-input bg-card px-2 text-sm", className)} {...p} />
));
Select.displayName = "Select";

export const Label = React.forwardRef<React.ElementRef<typeof LabelPrimitive.Root>, React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>>(({ className, ...p }, ref) => (
  <LabelPrimitive.Root ref={ref} className={cn("text-sm font-medium leading-none", className)} {...p} />
));
Label.displayName = "Label";

export function Field({ label, htmlFor, error, hint, children, className }: { label: string; htmlFor?: string; error?: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid gap-1.5", className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && !error && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

const badgeTones = {
  default: "bg-secondary text-secondary-foreground",
  primary: "bg-accent text-accent-foreground",
  success: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  danger: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  info: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
};
export function Badge({ tone = "default", className, ...p }: React.HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof badgeTones }) {
  return <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", badgeTones[tone], className)} {...p} />;
}

export function Skeleton({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...p} />;
}

export function Switch(p: React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className="peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-input transition-colors data-[state=checked]:bg-primary"
      {...p}
    >
      <SwitchPrimitive.Thumb className="pointer-events-none block h-4 w-4 rounded-full bg-card shadow transition-transform data-[state=checked]:translate-x-4" />
    </SwitchPrimitive.Root>
  );
}

export function Progress({ value, tone = "primary", className }: { value: number; tone?: "primary" | "warning" | "danger"; className?: string }) {
  const color = tone === "danger" ? "bg-destructive" : tone === "warning" ? "bg-warning" : "bg-primary";
  return (
    <ProgressPrimitive.Root className={cn("relative h-2 w-full overflow-hidden rounded-full bg-muted", className)} value={Math.min(100, value)}>
      <ProgressPrimitive.Indicator className={cn("h-full transition-all", color)} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </ProgressPrimitive.Root>
  );
}

export const Tabs = TabsPrimitive.Root;
export function TabsList({ className, ...p }: React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("inline-flex h-9 items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground overflow-x-auto max-w-full", className)} {...p} />;
}
export function TabsTrigger({ className, ...p }: React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-sm font-medium whitespace-nowrap data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm cursor-pointer", className)}
      {...p}
    />
  );
}
export const TabsContent = TabsPrimitive.Content;

export function Table({ className, ...p }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full caption-bottom text-sm", className)} {...p} />
    </div>
  );
}
export const THead = (p: React.HTMLAttributes<HTMLTableSectionElement>) => <thead className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground" {...p} />;
export const TBody = (p: React.HTMLAttributes<HTMLTableSectionElement>) => <tbody className="divide-y" {...p} />;
export const TR = ({ className, ...p }: React.HTMLAttributes<HTMLTableRowElement>) => <tr className={cn("hover:bg-muted/50", className)} {...p} />;
export const TH = ({ className, ...p }: React.ThHTMLAttributes<HTMLTableCellElement>) => <th className={cn("h-9 px-3 font-medium", className)} {...p} />;
export const TD = ({ className, ...p }: React.TdHTMLAttributes<HTMLTableCellElement>) => <td className={cn("px-3 py-2.5 align-middle", className)} {...p} />;

export function EmptyState({ title, description, action, icon }: { title: string; description?: string; action?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-10 text-center">
      <div className="text-muted-foreground">{icon ?? <Inbox className="size-8" aria-hidden />}</div>
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : "Something went wrong";
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm">
      <AlertCircle className="mt-0.5 size-4 text-destructive" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">Couldn't load this data</p>
        <p className="text-muted-foreground">{msg}</p>
      </div>
      {onRetry && (
        <button className="text-sm font-medium text-primary underline-offset-4 hover:underline cursor-pointer" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "positive" | "negative" }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-xl font-semibold tabular", tone === "positive" && "text-success", tone === "negative" && "text-destructive")}>{value}</p>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}

import { cn } from "@/lib/format";

/** Initials badge for a person (round) or a workspace (square). */
export function Avatar({ name, square, className }: { name: string; square?: boolean; className?: string }) {
  const initials = name
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
  return (
    <span aria-hidden className={cn("inline-flex size-8 shrink-0 items-center justify-center bg-primary/10 text-xs font-semibold text-primary", square ? "rounded-md" : "rounded-full", className)}>
      {initials || "?"}
    </span>
  );
}

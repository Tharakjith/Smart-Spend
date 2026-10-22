import * as AlertPrimitive from "@radix-ui/react-alert-dialog";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/format";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({ className, children, title, description, wide, ...p }: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { title: string; description?: string; wide?: boolean }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[1px]" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 grid max-h-[92vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-lg border bg-card p-5 shadow-xl",
          wide ? "max-w-4xl" : "max-w-lg",
          className,
        )}
        {...p}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <DialogPrimitive.Title className="text-lg font-semibold">{title}</DialogPrimitive.Title>
            {description ? <DialogPrimitive.Description className="mt-1 text-sm text-muted-foreground">{description}</DialogPrimitive.Description> : <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>}
          </div>
          <DialogPrimitive.Close className="rounded-sm opacity-70 hover:opacity-100 cursor-pointer" aria-label="Close">
            <X className="size-4" />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  destructive,
  loading,
  onConfirm,
  children,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: React.ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  children?: React.ReactNode;
}) {
  return (
    <AlertPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <AlertPrimitive.Portal>
        <AlertPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <AlertPrimitive.Content className="fixed left-1/2 top-1/2 z-50 grid w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg border bg-card p-5 shadow-xl">
          <AlertPrimitive.Title className="text-lg font-semibold">{title}</AlertPrimitive.Title>
          <AlertPrimitive.Description asChild>
            <div className="text-sm text-muted-foreground">{description}</div>
          </AlertPrimitive.Description>
          {children}
          <div className="flex justify-end gap-2">
            <AlertPrimitive.Cancel asChild>
              <Button variant="outline">Cancel</Button>
            </AlertPrimitive.Cancel>
            <Button variant={destructive ? "destructive" : "default"} loading={loading} onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </AlertPrimitive.Content>
      </AlertPrimitive.Portal>
    </AlertPrimitive.Root>
  );
}

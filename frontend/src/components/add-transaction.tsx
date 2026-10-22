import { useQueryClient } from "@tanstack/react-query";
import { FileUp, Loader2, PencilLine } from "lucide-react";
import * as React from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/format";
import { TransactionDialog } from "@/pages/transactions";

/**
 * "Add transaction" entry point: upload a bill (OCR fills in the details, then the review screen opens)
 * or type the transaction in by hand.
 */
export function AddTransactionDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [manual, setManual] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [over, setOver] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const nav = useNavigate();
  const qc = useQueryClient();

  const review = (docId: string) => {
    onOpenChange(false);
    nav(`/upload?doc=${encodeURIComponent(docId)}`);
  };

  const upload = async (file: File | undefined) => {
    if (!file || busy) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const d = await api<{ id: string }>("/documents", { form: fd });
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast.success(`${file.name} uploaded. Check the details we read, then confirm to add the transaction.`);
      review(d.id);
    } catch (e) {
      if (e instanceof ApiError && e.code === "duplicate_document") {
        toast.warning(`${file.name}: ${e.message}`);
        review(String(e.details.existing_document_id));
      } else {
        toast.error(e instanceof ApiError ? e.message : "Upload failed");
      }
    } finally {
      setBusy(false);
    }
  };

  const option = "flex flex-col items-center gap-2 rounded-lg border-2 p-5 text-center lift cursor-pointer active:scale-[0.98]";
  return (
    <>
      <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
        <DialogContent title="Add transaction" description="Upload the bill and we'll read it for you, or enter the details yourself.">
          <div className="stagger grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(true);
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setOver(false);
                upload(e.dataTransfer.files[0]);
              }}
              className={cn(option, "border-dashed", over ? "border-primary bg-accent" : "hover:border-primary/60 hover:bg-muted/50")}
            >
              {busy ? <Loader2 className="size-8 animate-spin text-primary" /> : <FileUp className="size-8 text-primary" aria-hidden />}
              <span className="font-medium">{busy ? "Uploading…" : "Upload a bill"}</span>
              <span className="text-xs text-muted-foreground">Photo or PDF of a bill, receipt, invoice or UPI screenshot. Amount, date, merchant and category are filled in for you.</span>
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                onOpenChange(false);
                setManual(true);
              }}
              className={cn(option, "hover:border-primary/60 hover:bg-muted/50")}
            >
              <PencilLine className="size-8 text-primary" aria-hidden />
              <span className="font-medium">Enter manually</span>
              <span className="text-xs text-muted-foreground">Cash, UPI, card, transfers, loans and anything without a bill.</span>
            </button>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.webp"
            className="sr-only"
            aria-label="Bill file"
            onChange={(e) => {
              upload(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </DialogContent>
      </Dialog>
      <TransactionDialog open={manual} onOpenChange={setManual} />
    </>
  );
}

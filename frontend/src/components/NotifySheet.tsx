/**
 * Telling a customer something.
 *
 * Always a preview first. A WhatsApp message cannot be unsent, and the person
 * clicking is usually mid-conversation with someone at the counter — so the
 * exact words, the exact number, and whether it can be delivered at all are on
 * screen before the send button is reachable.
 */
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { TextArea } from "@/components/Field";
import { Sheet } from "@/components/Sheet";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

export type NotificationKind =
  | "order_confirmed"
  | "order_ready"
  | "order_delivered"
  | "invoice"
  | "payment_reminder"
  | "birthday"
  | "anniversary"
  | "custom";

interface Preview {
  body: string;
  customer_id: number | null;
  customer_name: string | null;
  to_phone: string | null;
  related_type: string | null;
  related_id: number | null;
  sendable: boolean;
  note: string | null;
}

interface Sent {
  id: number;
  status: "sent" | "failed" | "skipped";
  error: string | null;
}

const TITLES: Record<NotificationKind, string> = {
  order_confirmed: "Confirm the order",
  order_ready: "Tell them it's ready",
  order_delivered: "Thank them",
  invoice: "Send the invoice",
  payment_reminder: "Remind about the balance",
  birthday: "Wish them a happy birthday",
  anniversary: "Wish them a happy anniversary",
  custom: "Send a message",
};

export function NotifySheet({
  open,
  onClose,
  kind,
  customerId,
  relatedId,
  onSent,
}: {
  open: boolean;
  onClose: () => void;
  kind: NotificationKind;
  customerId?: number | null;
  relatedId?: number | null;
  onSent?: () => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [body, setBody] = useState("");
  const [edited, setEdited] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPreview(null);
    setError(null);
    setEdited(false);
    api
      .post<Preview>("/notifications/preview", {
        kind,
        customer_id: customerId ?? null,
        related_id: relatedId ?? null,
      })
      .then((r) => {
        setPreview(r.data);
        setBody(r.data.body);
      })
      .catch((e) => setError(apiError(e, "Could not prepare the message")));
  }, [open, kind, customerId, relatedId]);

  const send = async () => {
    setBusy(true);
    try {
      const r = await api.post<Sent>("/notifications", {
        kind,
        customer_id: customerId ?? null,
        related_id: relatedId ?? null,
        // Only sent when the counter actually changed it, so the shop's
        // standard wording stays standard.
        body: edited ? body : null,
      });
      if (r.data.status === "sent") {
        toast("success", `Message sent to ${preview?.customer_name ?? "the customer"}`);
      } else {
        // Not an error toast: the click worked and the attempt is on record.
        // What failed is the delivery, and the reason is worth reading.
        toast("info", r.data.error ?? "Nothing was sent — the attempt is logged.");
      }
      onSent?.();
      onClose();
    } catch (e) {
      toast("error", apiError(e, "Could not send"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={TITLES[kind]}
      subtitle={
        preview?.customer_name
          ? `${preview.customer_name}${preview.to_phone ? ` · ${preview.to_phone}` : ""}`
          : "Preparing…"
      }
      widthClass="max-w-xl"
      footer={
        <div className="flex items-center justify-between gap-3">
          <p className="min-w-0 flex-1 text-xs text-slate-500">
            {preview?.sendable
              ? "Read it back before you send — this can't be unsent."
              : preview?.note ?? ""}
          </p>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={!preview?.sendable || busy}
              onClick={send}
            >
              {busy ? "Sending…" : "Send on WhatsApp"}
            </button>
          </div>
        </div>
      }
    >
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!preview && !error && <p className="text-sm text-slate-500">Preparing…</p>}

      {preview && (
        <div className="space-y-4">
          {!preview.sendable && (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
              {preview.note}
            </p>
          )}

          {/* Shown as a message bubble rather than a form field, because the
              thing being checked is how it will read to the customer. */}
          <div className="rounded-2xl bg-emerald-50 p-4">
            <p className="eyebrow text-emerald-800">How it will arrive</p>
            <p className="mt-2 whitespace-pre-line rounded-xl rounded-tl-sm bg-white px-3 py-2 text-sm leading-relaxed text-slate-800 shadow-sm">
              {body}
            </p>
          </div>

          <details className="card" open={edited}>
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
              Change the wording
            </summary>
            <div className="mt-3">
              <TextArea
                label="Message"
                value={body}
                onChange={(e) => {
                  setBody(e.target.value);
                  setEdited(true);
                }}
                hint="Leave it alone unless this one needs saying differently — the standard wording keeps the shop consistent."
              />
              {edited && (
                <button
                  type="button"
                  className="mt-2 text-xs text-brand-700 hover:underline"
                  onClick={() => {
                    setBody(preview.body);
                    setEdited(false);
                  }}
                >
                  Back to the standard wording
                </button>
              )}
            </div>
          </details>
        </div>
      )}
    </Sheet>
  );
}

/**
 * Shared vocabulary for orders and repairs.
 *
 * The list and the detail page must describe a job identically — a status that
 * reads "on the bench" on one screen and "in progress" on the next is two
 * things as far as the person reading it is concerned.
 */

export type OrderKind = "custom" | "repair";
export type OrderStatusValue =
  | "draft"
  | "confirmed"
  | "in_progress"
  | "ready"
  | "delivered"
  | "cancelled";

export interface OrderEvent {
  id: number;
  created_at: string;
  from_status: OrderStatusValue | null;
  to_status: OrderStatusValue | null;
  note: string | null;
  user_id: number | null;
}

export interface Order {
  id: number;
  order_no: string;
  kind: OrderKind;
  status: OrderStatusValue;
  customer_id: number;
  customer_name: string | null;
  customer_phone: string | null;
  branch_id: number;
  branch_name: string | null;
  title: string;
  description: string | null;
  promised_date: string | null;
  days_overdue: number | null;
  estimate_amount: string;
  intake_weight_g: string | null;
  intake_purity: number | null;
  intake_notes: string | null;
  image_url: string | null;
  product_id: number | null;
  design_id: number | null;
  design_no: string | null;
  invoice_id: number | null;
  delivered_at: string | null;
  cancelled_reason: string | null;
  notes: string | null;
  allowed_transitions: OrderStatusValue[];
}

export interface OrderDetail extends Order {
  events: OrderEvent[];
}

export const ORDER_STATUSES = [
  { value: "", label: "All" },
  { value: "draft", label: "Draft" },
  { value: "confirmed", label: "Confirmed" },
  { value: "in_progress", label: "On the bench" },
  { value: "ready", label: "Ready" },
  { value: "delivered", label: "Delivered" },
  { value: "cancelled", label: "Cancelled" },
];

/** The shop's words for a status, not the enum's. */
export function statusLabel(s: OrderStatusValue): string {
  return ORDER_STATUSES.find((x) => x.value === s)?.label ?? s.replace(/_/g, " ");
}

/** The verb for moving *to* a status — what the button says. */
export function transitionLabel(s: OrderStatusValue): string {
  switch (s) {
    case "confirmed":
      return "Confirm";
    case "in_progress":
      return "Back to the bench";
    case "ready":
      return "Mark ready";
    case "delivered":
      return "Hand over";
    default:
      return statusLabel(s);
  }
}

export function OrderStatusChip({ status }: { status: OrderStatusValue }) {
  const map: Record<OrderStatusValue, [string, string]> = {
    draft: ["chip-idle", "bg-slate-400"],
    confirmed: ["chip-gold", "bg-brand-500"],
    in_progress: ["chip-out", "bg-amber-500"],
    ready: ["chip-back", "bg-emerald-500"],
    delivered: ["chip-idle", "bg-slate-400"],
    cancelled: ["chip-dead", "bg-slate-400"],
  };
  const [cls, dot] = map[status];
  return (
    <span className={cls}>
      <span className={`dot ${dot}`} aria-hidden />
      {statusLabel(status)}
    </span>
  );
}

export function OrderKindChip({ kind }: { kind: OrderKind }) {
  return (
    <span className={kind === "repair" ? "chip-out" : "chip-idle"}>
      {kind === "repair" ? "Repair" : "Commission"}
    </span>
  );
}

/**
 * When it's due, in the terms the counter uses.
 *
 * `days_overdue` is computed by the server so every client agrees on what late
 * means; this only turns it into a sentence.
 */
export function dueLabel(o: Order): { text: string; late: boolean } | null {
  if (o.days_overdue && o.days_overdue > 0) {
    return { text: `${o.days_overdue} day${o.days_overdue === 1 ? "" : "s"} overdue`, late: true };
  }
  if (!o.promised_date) return null;
  const due = new Date(o.promised_date);
  const text = due.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  return { text: `Due ${text}`, late: false };
}

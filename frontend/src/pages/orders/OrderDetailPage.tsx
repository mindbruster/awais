/**
 * One job, and everything that has happened to it.
 *
 * The action rail offers exactly the moves the server will accept — the API
 * returns `allowed_transitions` off the same table it enforces, so a button
 * the counter can press is a button that works. Guessing at that client-side
 * is how a workflow screen ends up offering actions that 409.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { NotifySheet, NotificationKind } from "@/components/NotifySheet";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { Sheet } from "@/components/Sheet";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney, fmtWeight } from "@/lib/money";
import {
  OrderDetail,
  OrderKindChip,
  OrderStatusChip,
  dueLabel,
  statusLabel,
  transitionLabel,
} from "@/pages/orders/parts";

interface Named {
  id: number;
  name: string;
  abbreviation?: string;
}

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function OrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const orderId = Number(id);
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [notify, setNotify] = useState<NotificationKind | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get<OrderDetail>(`/orders/${orderId}`);
      setOrder(r.data);
    } catch (e) {
      setError(apiError(e, "Could not load this order"));
    }
  }, [orderId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!order) return <div className="text-sm text-slate-500">Loading…</div>;

  const move = async (to: string) => {
    setBusy(true);
    try {
      await api.post(`/orders/${order.id}/status`, { to });
      toast("success", `${order.order_no} → ${statusLabel(to as never)}`);
      load();
    } catch (e) {
      toast("error", apiError(e, "Could not move the order"));
    } finally {
      setBusy(false);
    }
  };

  const confirmCancel = async (password: string) => {
    try {
      await api.post(
        `/orders/${order.id}/cancel`,
        { reason: cancelReason.trim() },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${order.order_no} cancelled`);
      setCancelling(false);
      setCancelReason("");
      load();
    } catch (e) {
      toast("error", apiError(e, "Could not cancel"));
    }
  };

  const due = dueLabel(order);
  const moves = order.allowed_transitions.filter((s) => s !== "cancelled");
  const closed = order.status === "delivered" || order.status === "cancelled";

  return (
    <div className="space-y-5">
      <div className="card-flush">
        <div className="border-b border-slate-100 px-5 pb-4 pt-4">
          <Link to="/orders" className="text-xs text-slate-500 hover:text-slate-700 hover:underline">
            ← Orders
          </Link>
          <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="num text-2xl font-semibold tracking-tight text-slate-900">
                {order.order_no}
              </h1>
              <p className="mt-1 text-base text-slate-900">{order.title}</p>
              <p className="mt-0.5 text-sm text-slate-600">
                {order.customer_name}
                {order.customer_phone ? ` · ${order.customer_phone}` : ""}
              </p>
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                <OrderKindChip kind={order.kind} />
                <OrderStatusChip status={order.status} />
                {due && (
                  <span className={due.late ? "chip-owed" : "chip-idle"}>{due.text}</span>
                )}
                {order.branch_name && <span className="chip-idle">{order.branch_name}</span>}
              </div>
            </div>
            {order.design_no && (
              <Link className="btn-outline flex-none" to={`/designs/${order.design_id}`}>
                Open {order.design_no} →
              </Link>
            )}
          </div>
        </div>

        <dl className="grid grid-cols-2 divide-x divide-slate-100 sm:grid-cols-4">
          <Stat label="Estimate" value={Number(order.estimate_amount) > 0 ? fmtMoney(order.estimate_amount) : "—"} />
          <Stat
            label="Promised"
            value={
              order.promised_date
                ? new Date(order.promised_date).toLocaleDateString(undefined, {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                  })
                : "—"
            }
          />
          <Stat
            label="Taken in"
            value={order.intake_weight_g ? `${fmtWeight(order.intake_weight_g, 3)} g` : "—"}
            sub={order.intake_purity ? `${order.intake_purity}k` : undefined}
          />
          <Stat label="Delivered" value={order.delivered_at ? when(order.delivered_at) : "—"} />
        </dl>

        {order.description && (
          <p className="whitespace-pre-line border-t border-slate-100 px-5 py-3 text-sm leading-relaxed text-slate-600">
            {order.description}
          </p>
        )}
      </div>

      {order.kind === "repair" && order.intake_weight_g && (
        <div className="card border-amber-200 ring-1 ring-amber-100">
          <h3 className="text-sm font-semibold text-slate-900">The customer's own metal</h3>
          <p className="num mt-1 text-lg text-slate-900">
            {fmtWeight(order.intake_weight_g, 3)} g
            {order.intake_purity ? ` · ${order.intake_purity}k` : ""}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-slate-600">
            Weighed in at intake. This metal belongs to the customer and goes back out in the
            finished job — it is not the shop's to sell.
          </p>
          {order.intake_notes && (
            <p className="mt-3 whitespace-pre-line border-t border-amber-100 pt-3 text-xs text-slate-600">
              <span className="eyebrow block">Condition on arrival</span>
              {order.intake_notes}
            </p>
          )}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div>
          <h2 className="mb-2 text-sm font-semibold text-slate-900">History</h2>
          <ol className="space-y-2">
            {order.events.length === 0 && (
              <li className="card text-sm text-slate-500">Nothing recorded yet.</li>
            )}
            {order.events.map((e) => (
              <li key={e.id} className="card p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm text-slate-900">
                    {e.to_status ? (
                      <>
                        {e.from_status ? `${statusLabel(e.from_status)} → ` : ""}
                        <span className="font-medium">{statusLabel(e.to_status)}</span>
                      </>
                    ) : (
                      "Note"
                    )}
                  </span>
                  <span className="num text-xs text-slate-400">{when(e.created_at)}</span>
                </div>
                {e.note && (
                  <p className="mt-1 whitespace-pre-line text-xs leading-relaxed text-slate-600">
                    {e.note}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </div>

        <div className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          {closed ? (
            <div className="card text-sm text-slate-500">
              {order.order_no} is {statusLabel(order.status).toLowerCase()}.
              {order.cancelled_reason && (
                <span className="mt-2 block text-xs">Reason: {order.cancelled_reason}</span>
              )}
            </div>
          ) : (
            <div className="card">
              <h3 className="text-sm font-semibold text-slate-900">What's next</h3>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                {order.design_id
                  ? "The workshop is tracking the piece itself — costs and wastage live on the design."
                  : "Putting it on the bench mints a design, and the workshop tracks it from there."}
              </p>
              <div className="mt-4 space-y-2">
                {!order.design_id && (
                  <button className="btn-primary w-full" onClick={() => setStarting(true)}>
                    Start work
                  </button>
                )}
                {moves.map((s, i) => (
                  <button
                    key={s}
                    className={i === 0 && order.design_id ? "btn-primary w-full" : "btn-outline w-full"}
                    disabled={busy}
                    onClick={() => move(s)}
                  >
                    {transitionLabel(s)}
                  </button>
                ))}
              </div>
              <div className="mt-4 border-t border-slate-100 pt-3">
                <p className="eyebrow">Tell the customer</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {order.status === "ready" && (
                    <button className="btn-outline flex-1" onClick={() => setNotify("order_ready")}>
                      It's ready
                    </button>
                  )}
                  {order.status === "confirmed" && (
                    <button className="btn-outline flex-1" onClick={() => setNotify("order_confirmed")}>
                      Confirm it
                    </button>
                  )}
                  <button
                    className="btn-outline flex-1"
                    onClick={() => setNotify("payment_reminder")}
                  >
                    Balance due
                  </button>
                </div>
              </div>
              <div className="mt-4 border-t border-slate-100 pt-3 text-center">
                <button
                  className="text-xs text-slate-500 hover:text-red-600 hover:underline"
                  onClick={() => setCancelling(true)}
                >
                  Cancel this order
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <NotifySheet
        open={notify !== null}
        onClose={() => setNotify(null)}
        kind={notify ?? "order_ready"}
        customerId={order.customer_id}
        relatedId={order.id}
        onSent={load}
      />

      <StartWork
        open={starting}
        order={order}
        onClose={() => setStarting(false)}
        onStarted={() => {
          setStarting(false);
          load();
        }}
      />

      <PasswordConfirm
        open={cancelling}
        onClose={() => setCancelling(false)}
        title={`Cancel ${order.order_no}?`}
        description={
          order.design_id
            ? "This withdraws the promise to the customer. The workshop job is left alone — if metal is already out with a karigar, cancel that leg from the design so the metal comes back."
            : "This withdraws the promise to the customer. Nothing has been made yet, so nothing else changes."
        }
        confirmLabel="Cancel order"
        extraValid={cancelReason.trim().length > 0}
        extra={
          <TextField
            label="Reason"
            required
            placeholder="e.g. customer changed their mind"
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
          />
        }
        onConfirm={confirmCancel}
      />
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="px-5 py-3">
      <dt className="eyebrow">{label}</dt>
      <dd className="num mt-0.5 text-sm text-slate-900">
        {value}
        {sub && <span className="ml-1.5 text-xs font-normal text-slate-400">{sub}</span>}
      </dd>
    </div>
  );
}

function StartWork({
  open,
  order,
  onClose,
  onStarted,
}: {
  open: boolean;
  order: OrderDetail;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [items, setItems] = useState<Named[]>([]);
  const [itemId, setItemId] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api
      .get<Named[]>("/items", { params: { is_active: true } })
      .then((r) => {
        setItems(r.data);
        setItemId((p) => p || String(r.data[0]?.id ?? ""));
      })
      .catch((e) => toast("error", apiError(e, "Could not load items")));
  }, [open]);

  const item = items.find((i) => String(i.id) === itemId);

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ design_no: string }>(`/orders/${order.id}/start-work`, {
        item_id: Number(itemId),
        notes: notes || null,
      });
      toast("success", `On the bench as ${r.data.design_no ?? "a new design"}`);
      onStarted();
    } catch (e) {
      toast("error", apiError(e, "Could not start work"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Start work"
      subtitle={`${order.order_no} · ${order.title}`}
      widthClass="max-w-xl"
      footer={
        <div className="flex items-center justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" disabled={!itemId || busy} onClick={submit}>
            {busy ? "Starting…" : "Put it on the bench"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="card">
          <p className="text-sm leading-relaxed text-slate-600">
            This mints a design for the job. From then on the piece is tracked like any other —
            issued to departments, wastage settled against each karigar, labour accrued per leg —
            and this order simply holds the customer's side of it.
          </p>
        </div>
        <div className="card space-y-3">
          <SelectField
            label="What kind of piece"
            required
            value={itemId}
            onChange={(e) => setItemId(e.target.value)}
            options={items.map((i) => ({ value: i.id, label: i.name }))}
            hint={
              item?.abbreviation
                ? `The design number will start with ${item.abbreviation.toUpperCase()}-`
                : "The item's abbreviation becomes the design number prefix"
            }
          />
          <TextArea
            label="Notes for the workshop"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={`${order.order_no}: ${order.title}`}
          />
        </div>
      </div>
    </Sheet>
  );
}

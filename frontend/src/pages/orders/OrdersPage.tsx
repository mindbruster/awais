/**
 * The workbench: everything the shop has promised someone.
 *
 * Built as a worklist, not a table. The two questions a counter asks all day
 * are "what's ready to hand over" and "what's late", so both are counted at the
 * top and reachable in one click — and every row leads with the customer,
 * because that is who is standing there asking.
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { Sheet } from "@/components/Sheet";
import { toast } from "@/components/Toast";
import { SearchBox } from "@/components/Toolbar";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";
import { ORDER_STATUSES, OrderKindChip, OrderStatusChip, Order, dueLabel } from "@/pages/orders/parts";

interface Named {
  id: number;
  name: string;
}

interface Board {
  draft: number;
  confirmed: number;
  in_progress: number;
  ready: number;
  overdue: number;
}

export function OrdersPage() {
  const [rows, setRows] = useState<Order[]>([]);
  const [board, setBoard] = useState<Board | null>(null);
  const [status, setStatus] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [taking, setTaking] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (status) params.status = status;
    if (overdue) params.overdue = "true";
    if (q) params.q = q;
    api
      .get<Order[]>("/orders", { params })
      .then((r) => setRows(r.data))
      .catch((e) => setError(apiError(e, "Could not load orders")))
      .finally(() => setLoading(false));
    api
      .get<Board>("/orders/board")
      .then((r) => setBoard(r.data))
      .catch(() => setBoard(null));
  }, [status, overdue, q]);

  useEffect(load, [load]);

  const pick = (s: string, od: boolean) => {
    setStatus(s);
    setOverdue(od);
  };

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Orders &amp; repairs</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Work you've promised a customer — a piece to be made, or one handed across the counter
            to be mended. Starting work puts it on the bench as a design, and everything the
            workshop already tracks follows from there.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setTaking(true)}>
          Take an order
        </button>
      </div>

      {board && (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Count label="Ready to collect" value={board.ready} tone="good"
                 active={status === "ready"} onClick={() => pick("ready", false)} />
          <Count label="Overdue" value={board.overdue} tone="bad"
                 active={overdue} onClick={() => pick("", true)} />
          <Count label="On the bench" value={board.in_progress}
                 active={status === "in_progress"} onClick={() => pick("in_progress", false)} />
          <Count label="Confirmed" value={board.confirmed}
                 active={status === "confirmed"} onClick={() => pick("confirmed", false)} />
          <Count label="Drafts" value={board.draft}
                 active={status === "draft"} onClick={() => pick("draft", false)} />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-1 border-b border-slate-200">
        {ORDER_STATUSES.map((s) => {
          const active = !overdue && status === s.value;
          return (
            <button
              key={s.value || "all"}
              onClick={() => pick(s.value, false)}
              aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
                active
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"
              }`}
            >
              {s.label}
            </button>
          );
        })}
      </div>

      <div className="mt-4">
        <SearchBox value={q} onChange={setQ} placeholder="Search order number or title…" className="w-full sm:w-80" />
      </div>

      {loading && <div className="card mt-4 text-sm text-slate-500">Loading…</div>}
      {error && <div className="card mt-4 text-sm text-red-600">{error}</div>}

      {!loading && !error && rows.length === 0 && (
        <div className="card mt-4 py-12 text-center">
          <p className="text-sm font-medium text-slate-700">
            {status || overdue || q ? "Nothing here." : "No orders yet."}
          </p>
          <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
            {status || overdue || q
              ? "Try another tab, or clear the search."
              : "When a customer asks for a piece to be made, or hands one over to be repaired, take it in here so nothing lives on a slip of paper."}
          </p>
          {!(status || overdue || q) && (
            <button className="btn-primary mt-4" onClick={() => setTaking(true)}>
              Take an order
            </button>
          )}
        </div>
      )}

      <div className="mt-4 space-y-2">
        {rows.map((o) => {
          const due = dueLabel(o);
          return (
            <Link
              key={o.id}
              to={`/orders/${o.id}`}
              className="card-flush block p-4 transition hover:border-brand-300 hover:shadow-md"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="num text-sm font-medium text-slate-900">{o.order_no}</span>
                    <OrderKindChip kind={o.kind} />
                    <OrderStatusChip status={o.status} />
                  </div>
                  <p className="mt-1 truncate text-sm text-slate-900">{o.title}</p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {o.customer_name}
                    {o.customer_phone ? ` · ${o.customer_phone}` : ""}
                    {o.design_no ? (
                      <>
                        {" · "}
                        <span className="num text-brand-700">{o.design_no}</span>
                      </>
                    ) : null}
                  </p>
                </div>
                <div className="flex-none text-right">
                  {Number(o.estimate_amount) > 0 && (
                    <p className="num text-sm font-medium text-slate-900">
                      {fmtMoney(o.estimate_amount)}
                    </p>
                  )}
                  {due && (
                    <p className={`mt-0.5 text-xs ${due.late ? "font-medium text-red-600" : "text-slate-500"}`}>
                      {due.text}
                    </p>
                  )}
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      <TakeOrder
        open={taking}
        onClose={() => setTaking(false)}
        onTaken={() => {
          setTaking(false);
          load();
        }}
      />
    </div>
  );
}

function Count({
  label,
  value,
  tone,
  active,
  onClick,
}: {
  label: string;
  value: number;
  tone?: "good" | "bad";
  active: boolean;
  onClick: () => void;
}) {
  const colour =
    value === 0
      ? "text-slate-300"
      : tone === "bad"
      ? "text-red-600"
      : tone === "good"
      ? "text-emerald-700"
      : "text-slate-900";
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`card p-4 text-left transition hover:border-brand-300 ${
        active ? "border-brand-400 ring-1 ring-brand-200" : ""
      }`}
    >
      <p className="eyebrow">{label}</p>
      <p className={`num mt-1 text-2xl font-semibold ${colour}`}>{value}</p>
    </button>
  );
}

function TakeOrder({
  open,
  onClose,
  onTaken,
}: {
  open: boolean;
  onClose: () => void;
  onTaken: () => void;
}) {
  const [kind, setKind] = useState<"custom" | "repair">("custom");
  const [customers, setCustomers] = useState<Named[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [promised, setPromised] = useState("");
  const [estimate, setEstimate] = useState("");
  const [weight, setWeight] = useState("");
  const [purity, setPurity] = useState("22");
  const [intakeNotes, setIntakeNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTitle("");
    setDescription("");
    setWeight("");
    setIntakeNotes("");
    api
      .get<Named[]>("/customers", { params: { limit: 500 } })
      .then((r) => {
        setCustomers(r.data);
        setCustomerId((p) => p || String(r.data[0]?.id ?? ""));
      })
      .catch((e) => toast("error", apiError(e, "Could not load customers")));
  }, [open]);

  const isRepair = kind === "repair";
  const ready = Boolean(customerId && title.trim() && (!isRepair || Number(weight) > 0));

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    try {
      await api.post("/orders", {
        kind,
        customer_id: Number(customerId),
        title: title.trim(),
        description: description || null,
        promised_date: promised || null,
        estimate_amount: estimate || "0",
        // Only a repair arrives with the customer's own metal. Sending a weight
        // on a commission is refused by the API, and rightly — it would be a
        // measurement of nothing.
        intake_weight_g: isRepair ? weight : null,
        intake_purity: isRepair && purity ? Number(purity) : null,
        intake_notes: isRepair ? intakeNotes || null : null,
      });
      toast("success", "Order taken");
      onTaken();
    } catch (err) {
      toast("error", apiError(err, "Could not take the order"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Take an order"
      subtitle="Nothing is promised to the workshop yet — this records what the customer asked for"
      widthClass="max-w-2xl"
      footer={
        <div className="flex items-center justify-between gap-3">
          <p className="min-w-0 flex-1 text-xs text-slate-500">
            {ready
              ? "Saved as a draft. Confirm it once the customer agrees."
              : isRepair && !(Number(weight) > 0)
              ? "Weigh the customer's piece — that weight is what settles a later dispute."
              : "Pick a customer and say what the job is."}
          </p>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="btn-primary" disabled={!ready || busy} onClick={() => submit()}>
              {busy ? "Saving…" : "Take order"}
            </button>
          </div>
        </div>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="card">
          <p className="eyebrow">What kind of job</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {([
              ["custom", "Commission", "A new piece, made from the shop's metal."],
              ["repair", "Repair", "The customer's own piece, taken in across the counter."],
            ] as const).map(([v, label, hint]) => (
              <button
                key={v}
                type="button"
                onClick={() => setKind(v)}
                aria-pressed={kind === v}
                className={`rounded-xl border p-3 text-left transition ${
                  kind === v
                    ? "border-brand-400 bg-brand-50 ring-1 ring-brand-200"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <span className="block text-sm font-medium text-slate-900">{label}</span>
                <span className="mt-0.5 block text-xs leading-snug text-slate-500">{hint}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="card space-y-3">
          <SelectField
            label="Customer"
            required
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            options={customers.map((c) => ({ value: c.id, label: c.name }))}
          />
          <TextField
            label="What's the job"
            required
            placeholder={isRepair ? "e.g. resize ring to 16" : "e.g. taka set, 12 tola"}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <TextArea
            label="Details"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField
              label="Promised for"
              type="date"
              value={promised}
              onChange={(e) => setPromised(e.target.value)}
              hint="What you told the customer"
            />
            <TextField
              label="Estimate"
              type="number"
              step="0.01"
              min={0}
              value={estimate}
              onChange={(e) => setEstimate(e.target.value)}
              hint="Quoted, not billed"
            />
          </div>
        </div>

        {isRepair && (
          <div className="card space-y-3 border-amber-200 ring-1 ring-amber-100">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">The customer's piece</h3>
              <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
                This metal is not the shop's. Weigh it in front of the customer — this line is
                what settles it if the finished weight is ever questioned.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField
                label="Weight taken in (g)"
                type="number"
                step="0.0001"
                min={0.0001}
                required
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
              />
              <TextField
                label="Purity (k)"
                type="number"
                min={1}
                max={24}
                value={purity}
                onChange={(e) => setPurity(e.target.value)}
              />
            </div>
            <TextArea
              label="Condition on arrival"
              placeholder="e.g. one stone missing, clasp bent"
              value={intakeNotes}
              onChange={(e) => setIntakeNotes(e.target.value)}
            />
          </div>
        )}
      </form>
    </Sheet>
  );
}

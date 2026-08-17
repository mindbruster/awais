/**
 * Memos — pieces let out on approval.
 *
 * The screen answers the question a shelf cannot: which pieces are out of the
 * building, with whom, and since when. Overdue memos lead, because a piece
 * nobody is chasing is a piece the shop discovers missing at stock-take months
 * later with no idea who had it.
 */
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { Sheet } from "@/components/Sheet";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtWeight } from "@/lib/money";

type Status = "out" | "partly_returned" | "closed" | "cancelled";
type LineStatus = "out" | "returned" | "sold";

interface Line {
  id: number;
  product_id: number;
  product_serial: string | null;
  product_name: string | null;
  gold_weight_g: string | null;
  status: LineStatus;
  returned_at: string | null;
}

interface Approval {
  id: number;
  approval_no: string;
  customer_id: number;
  customer_name: string | null;
  customer_phone: string | null;
  branch_name: string | null;
  status: Status;
  issued_at: string | null;
  due_date: string | null;
  days_overdue: number | null;
  out_count: number;
  total_count: number;
  notes: string | null;
  cancelled_reason: string | null;
  items: Line[];
}

interface Board {
  out: number;
  partly_returned: number;
  overdue: number;
  pieces_out: number;
}

interface Named {
  id: number;
  name: string;
}

interface StockPiece {
  id: number;
  serial_no: string;
  name: string;
  gold_weight_g: string;
}

const TABS = [
  { value: "", label: "All" },
  { value: "out", label: "Out" },
  { value: "partly_returned", label: "Partly back" },
  { value: "closed", label: "Closed" },
  { value: "cancelled", label: "Cancelled" },
];

function StatusChip({ a }: { a: Approval }) {
  if (a.status === "cancelled") return <span className="chip-dead">Cancelled</span>;
  if (a.status === "closed")
    return (
      <span className="chip-back">
        <span className="dot bg-emerald-500" aria-hidden />
        All back
      </span>
    );
  if (a.status === "partly_returned")
    return (
      <span className="chip-out">
        <span className="dot bg-amber-500" aria-hidden />
        {a.out_count} still out
      </span>
    );
  return (
    <span className="chip-out">
      <span className="dot bg-amber-500" aria-hidden />
      {a.out_count} out
    </span>
  );
}

function LineChip({ status }: { status: LineStatus }) {
  if (status === "returned") return <span className="chip-back">Back</span>;
  if (status === "sold") return <span className="chip-gold">Kept</span>;
  return <span className="chip-out">Out</span>;
}

export function ApprovalsPage() {
  const [rows, setRows] = useState<Approval[]>([]);
  const [board, setBoard] = useState<Board | null>(null);
  const [status, setStatus] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState<Approval | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [picked, setPicked] = useState<Record<number, Set<number>>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (status) params.status = status;
    if (overdue) params.overdue = "true";
    api
      .get<Approval[]>("/approvals", { params })
      .then((r) => setRows(r.data))
      .catch((e) => setError(apiError(e, "Could not load memos")))
      .finally(() => setLoading(false));
    api
      .get<Board>("/approvals/board")
      .then((r) => setBoard(r.data))
      .catch(() => setBoard(null));
  }, [status, overdue]);

  useEffect(load, [load]);

  const toggleLine = (aid: number, lid: number) =>
    setPicked((p) => {
      const set = new Set(p[aid] ?? []);
      set.has(lid) ? set.delete(lid) : set.add(lid);
      return { ...p, [aid]: set };
    });

  const act = async (a: Approval, what: "return" | "sold") => {
    const ids = Array.from(picked[a.id] ?? []);
    if (ids.length === 0) return;
    setBusy(true);
    try {
      await api.post(`/approvals/${a.id}/${what}`, { line_ids: ids });
      toast(
        "success",
        what === "return"
          ? `${ids.length} piece(s) back on the shelf`
          : `${ids.length} piece(s) marked as kept`,
      );
      setPicked((p) => ({ ...p, [a.id]: new Set() }));
      load();
    } catch (e) {
      toast("error", apiError(e, "Could not update the memo"));
    } finally {
      setBusy(false);
    }
  };

  const confirmCancel = async (password: string) => {
    if (!cancelling) return;
    try {
      await api.post(
        `/approvals/${cancelling.id}/cancel`,
        { reason: cancelReason.trim() },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${cancelling.approval_no} cancelled`);
      setCancelling(null);
      setCancelReason("");
      load();
    } catch (e) {
      toast("error", apiError(e, "Could not cancel"));
    }
  };

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">On approval</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Pieces let out for a customer to consider. They're still yours until one is kept — but
            they're not on the shelf either, which is exactly how stock goes missing without
            anyone noticing.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          Let pieces out
        </button>
      </div>

      {board && (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Count label="Pieces out" value={board.pieces_out} />
          <Count
            label="Overdue"
            value={board.overdue}
            tone="bad"
            active={overdue}
            onClick={() => {
              setOverdue(!overdue);
              setStatus("");
            }}
          />
          <Count label="Memos out" value={board.out} />
          <Count label="Partly back" value={board.partly_returned} />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-1 border-b border-slate-200">
        {TABS.map((t) => {
          const active = !overdue && status === t.value;
          return (
            <button
              key={t.value || "all"}
              onClick={() => {
                setStatus(t.value);
                setOverdue(false);
              }}
              aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
                active
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {loading && <div className="card mt-4 text-sm text-slate-500">Loading…</div>}
      {error && <div className="card mt-4 text-sm text-red-600">{error}</div>}

      {!loading && !error && rows.length === 0 && (
        <div className="mt-4">
          {status || overdue ? (
            <EmptyState
              title=""
              filtered
              onClear={() => {
                setStatus("");
                setOverdue(false);
              }}
            />
          ) : (
            <EmptyState
              title="Nothing is out on approval."
              action={{ label: "Let pieces out", onClick: () => setCreating(true) }}
            >
              When a customer wants to take pieces home to decide, record them here. They stay off
              the shelf but stay yours — and you get a list of who has what.
            </EmptyState>
          )}
        </div>
      )}

      <div className="mt-4 space-y-2">
        {rows.map((a) => {
          const chosen = picked[a.id] ?? new Set<number>();
          const open = a.status === "out" || a.status === "partly_returned";
          return (
            <div
              key={a.id}
              className={`card-flush p-4 ${a.days_overdue ? "ring-1 ring-red-200" : ""}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="num text-sm font-medium text-slate-900">
                      {a.approval_no}
                    </span>
                    <StatusChip a={a} />
                    {a.days_overdue ? (
                      <span className="chip-owed">
                        {a.days_overdue} day{a.days_overdue === 1 ? "" : "s"} overdue
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-sm text-slate-700">
                    {a.customer_name}
                    {a.customer_phone ? ` · ${a.customer_phone}` : ""}
                  </p>
                  {a.due_date && (
                    <p className="num mt-0.5 text-xs text-slate-500">
                      Due back{" "}
                      {new Date(a.due_date).toLocaleDateString(undefined, {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </p>
                  )}
                </div>
                {open && (
                  <button className="btn-outline flex-none" onClick={() => setCancelling(a)}>
                    Cancel memo
                  </button>
                )}
              </div>

              <ul className="mt-3 divide-y divide-slate-100 border-t border-slate-100">
                {a.items.map((l) => (
                  <li key={l.id} className="flex items-center gap-3 py-2">
                    {open && l.status === "out" ? (
                      <input
                        type="checkbox"
                        className="h-4 w-4 flex-none rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                        checked={chosen.has(l.id)}
                        onChange={() => toggleLine(a.id, l.id)}
                        aria-label={`Select ${l.product_serial}`}
                      />
                    ) : (
                      <span className="w-4 flex-none" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="num text-sm text-slate-900">{l.product_serial}</span>
                      <span className="ml-2 text-xs text-slate-500">{l.product_name}</span>
                    </span>
                    <span className="num flex-none text-xs text-slate-500">
                      {l.gold_weight_g ? `${fmtWeight(l.gold_weight_g)} g` : ""}
                    </span>
                    <LineChip status={l.status} />
                  </li>
                ))}
              </ul>

              {open && chosen.size > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
                  <span className="text-xs text-slate-500">
                    {chosen.size} selected —
                  </span>
                  <button
                    className="btn-primary"
                    disabled={busy}
                    onClick={() => act(a, "return")}
                  >
                    Back on the shelf
                  </button>
                  <button className="btn-outline" disabled={busy} onClick={() => act(a, "sold")}>
                    Customer is keeping them
                  </button>
                </div>
              )}

              {a.cancelled_reason && (
                <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-500">
                  Cancelled: {a.cancelled_reason}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <LetOut
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => {
          setCreating(false);
          load();
        }}
      />

      <PasswordConfirm
        open={cancelling !== null}
        onClose={() => setCancelling(null)}
        title={`Cancel ${cancelling?.approval_no ?? ""}?`}
        description={
          `Every piece still out on this memo goes straight back onto the shelf as in-stock. ` +
          `Only do this if they are physically back — otherwise the system will say you have ` +
          `stock you cannot see.`
        }
        confirmLabel="Cancel memo"
        extraValid={cancelReason.trim().length > 0}
        extra={
          <TextField
            label="Reason"
            required
            placeholder="e.g. all pieces returned in person"
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
          />
        }
        onConfirm={confirmCancel}
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
  tone?: "bad";
  active?: boolean;
  onClick?: () => void;
}) {
  const colour = value === 0 ? "text-slate-300" : tone === "bad" ? "text-red-600" : "text-slate-900";
  const cls = `card p-4 text-left ${onClick ? "transition hover:border-brand-300" : ""} ${
    active ? "border-brand-400 ring-1 ring-brand-200" : ""
  }`;
  const inner = (
    <>
      <p className="eyebrow">{label}</p>
      <p className={`num mt-1 text-2xl font-semibold ${colour}`}>{value}</p>
    </>
  );
  return onClick ? (
    <button className={cls} onClick={onClick} aria-pressed={active}>
      {inner}
    </button>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

function LetOut({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [customers, setCustomers] = useState<Named[]>([]);
  const [stock, setStock] = useState<StockPiece[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [due, setDue] = useState("");
  const [notes, setNotes] = useState("");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setChosen(new Set());
    setNotes("");
    Promise.all([
      api.get<Named[]>("/customers", { params: { limit: 500 } }),
      // Only what is genuinely on the shelf can go out — the API refuses
      // anything else, so it is never offered.
      api.get<StockPiece[]>("/products", { params: { status: "in_stock", limit: 300 } }),
    ])
      .then(([c, p]) => {
        setCustomers(c.data);
        setStock(p.data);
        setCustomerId((prev) => prev || String(c.data[0]?.id ?? ""));
      })
      .catch((e) => toast("error", apiError(e, "Could not load pieces")));
  }, [open]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return stock;
    return stock.filter(
      (p) =>
        p.serial_no.toLowerCase().includes(needle) || p.name.toLowerCase().includes(needle),
    );
  }, [stock, q]);

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    try {
      await api.post("/approvals", {
        customer_id: Number(customerId),
        product_ids: Array.from(chosen),
        due_date: due || null,
        notes: notes || null,
      });
      toast("success", "Memo created — the pieces are marked as out");
      onCreated();
    } catch (err) {
      toast("error", apiError(err, "Could not create the memo"));
    } finally {
      setBusy(false);
    }
  };

  const ready = Boolean(customerId) && chosen.size > 0;

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Let pieces out on approval"
      subtitle="They come off the shelf but stay yours until one is kept"
      widthClass="max-w-2xl"
      footer={
        <div className="flex items-center justify-between gap-3">
          <p className="min-w-0 flex-1 text-xs text-slate-500">
            {ready
              ? `${chosen.size} piece${chosen.size === 1 ? "" : "s"} will be marked as out.`
              : "Pick a customer and at least one piece."}
          </p>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="btn-primary" disabled={!ready || busy} onClick={() => submit()}>
              {busy ? "Creating…" : "Create memo"}
            </button>
          </div>
        </div>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="card grid gap-3 sm:grid-cols-2">
          <SelectField
            label="Customer"
            required
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            options={customers.map((c) => ({ value: c.id, label: c.name }))}
          />
          <TextField
            label="Due back"
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
            hint="Without a date, nobody chases it"
          />
        </div>

        <div className="card">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-900">
              Which pieces{" "}
              <span className="font-normal text-slate-400">· {chosen.size} selected</span>
            </h3>
            <input
              className="input w-48"
              placeholder="Search stock…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          {shown.length === 0 ? (
            <p className="mt-3 rounded-xl border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-500">
              {stock.length === 0
                ? "Nothing is in stock to let out."
                : "No piece matches that search."}
            </p>
          ) : (
            <ul className="mt-3 max-h-80 divide-y divide-slate-100 overflow-y-auto">
              {shown.map((p) => (
                <li key={p.id}>
                  <label className="flex cursor-pointer items-center gap-3 py-2">
                    <input
                      type="checkbox"
                      className="h-4 w-4 flex-none rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                      checked={chosen.has(p.id)}
                      onChange={() =>
                        setChosen((s) => {
                          const next = new Set(s);
                          next.has(p.id) ? next.delete(p.id) : next.add(p.id);
                          return next;
                        })
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span className="num text-sm text-slate-900">{p.serial_no}</span>
                      <span className="ml-2 text-xs text-slate-500">{p.name}</span>
                    </span>
                    <span className="num flex-none text-xs text-slate-500">
                      {fmtWeight(p.gold_weight_g)} g
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </form>
    </Sheet>
  );
}

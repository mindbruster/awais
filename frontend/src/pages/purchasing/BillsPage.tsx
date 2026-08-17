/**
 * What the shop owes, when it is due, and what is left on each bill.
 *
 * Before this, a purchase on credit posted to 2110 Suppliers and stayed there:
 * nothing said when it was due, and nothing in the system could pay it. The
 * payables figure only ever grew, and "which bills are due this week" had no
 * answer at all.
 *
 * **The paid figure is derived, never stored.** Payments to a supplier are
 * spread across their bills oldest first, the way a running khata is settled.
 * That has a real cost and the page says so out loud rather than burying it:
 * money handed over for this week's bill will show as clearing the oldest one
 * still open. What it buys is that a bill's status cannot drift out of step
 * with the ledger, because there is no stored status to drift.
 *
 * Overdue leads. A list sorted by date with the late ones somewhere in the
 * middle is a list nobody reads to the end, and the whole point of the screen
 * is the two or three rows that need acting on today.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { FilterSelect, Toolbar } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Bill {
  kind: string;
  purchase_id: number;
  purchase_no: string;
  supplier_id: number;
  supplier_name: string | null;
  purchased_on: string;
  due_date: string | null;
  reference: string | null;
  total: string;
  paid: string;
  outstanding: string;
  status: string;
  days_overdue: number | null;
}

interface Report {
  as_of: string;
  rows: Bill[];
  total_billed: string;
  total_paid: string;
  total_outstanding: string;
  overdue_count: number;
  overdue_amount: string;
  due_today_count: number;
  undated_count: number;
}

interface Named {
  id: number;
  name: string;
}

interface Payment {
  id: number;
  payment_no: string;
  supplier_name: string | null;
  paid_at: string;
  method: string;
  amount: string;
  reference: string | null;
  journal_entry_no: string | null;
  is_reversed: boolean;
}

const STATUS: Record<string, { label: string; className: string }> = {
  overdue: { label: "Overdue", className: "bg-red-50 text-red-700 ring-red-200" },
  due_today: { label: "Due today", className: "bg-amber-50 text-amber-800 ring-amber-200" },
  part_paid: { label: "Part paid", className: "bg-sky-50 text-sky-700 ring-sky-200" },
  upcoming: { label: "Upcoming", className: "bg-slate-50 text-slate-600 ring-slate-200" },
  paid: { label: "Paid", className: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  undated: { label: "No date", className: "bg-slate-50 text-slate-500 ring-slate-200" },
};

// Overdue first, then what is about to be. `paid` last: it is history, and the
// page exists for what still has to happen.
const ORDER = ["overdue", "due_today", "part_paid", "upcoming", "undated", "paid"];

const KIND: Record<string, string> = { gold: "Gold", silver: "Silver", stone: "Stones" };

const n = (v: string) => Number(v) || 0;

export function BillsPage() {
  const [data, setData] = useState<Report | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [suppliers, setSuppliers] = useState<Named[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);
  const [reversing, setReversing] = useState<Payment | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (supplierId) params.supplier_id = supplierId;
    if (statusFilter) params.status = statusFilter;
    api
      .get<Report>("/purchasing/bills", { params })
      .then((r) => setData(r.data))
      .catch((e) => setError(apiError(e, "Could not load the bills")))
      .finally(() => setLoading(false));
    api
      .get<Payment[]>("/purchasing/supplier-payments", {
        params: supplierId ? { supplier_id: supplierId } : {},
      })
      .then((r) => setPayments(r.data))
      .catch(() => setPayments([]));
  }, [supplierId, statusFilter]);

  useEffect(load, [load]);

  useEffect(() => {
    api
      .get<Named[]>("/purchasing/suppliers", { params: { limit: 200 } })
      .then((r) => setSuppliers(r.data))
      .catch(() => setSuppliers([]));
  }, []);

  const rows = useMemo(
    () =>
      [...(data?.rows ?? [])].sort((a, b) => {
        const d = ORDER.indexOf(a.status) - ORDER.indexOf(b.status);
        if (d !== 0) return d;
        // Within a bucket, oldest debt first — which is also the order the
        // next payment will actually clear them in.
        return a.purchased_on.localeCompare(b.purchased_on);
      }),
    [data],
  );

  const reversePayment = async (password: string) => {
    if (!reversing) return;
    try {
      await api.post(
        `/purchasing/supplier-payments/${reversing.id}/reverse`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${reversing.payment_no} reversed`);
      setReversing(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Could not reverse the payment"));
    }
  };

  if (error) return <div className="card text-sm text-red-600">{error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Bills & due dates</h1>
          <p className="mt-1 text-sm text-slate-500">
            What the shop owes its dealers, and when. A payment is knocked off the
            oldest bill first.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setPaying(true)}>
          Pay a supplier
        </button>
      </div>

      {data && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Outstanding" value={fmtMoney(data.total_outstanding)} />
          <Stat
            label="Overdue"
            value={fmtMoney(data.overdue_amount)}
            hint={`${data.overdue_count} bill${data.overdue_count === 1 ? "" : "s"}`}
            tone={data.overdue_count ? "bad" : "good"}
          />
          <Stat
            label="Due today"
            value={String(data.due_today_count)}
            tone={data.due_today_count ? "warn" : "plain"}
          />
          <Stat
            label="No date agreed"
            value={String(data.undated_count)}
            hint={
              data.undated_count
                ? "These never appear as due — give them a date"
                : "Every open bill has a date"
            }
            tone={data.undated_count ? "warn" : "plain"}
          />
        </div>
      )}

      <Toolbar>
        <FilterSelect
          value={supplierId}
          onChange={setSupplierId}
          options={suppliers.map((s) => ({ value: String(s.id), label: s.name }))}
          allLabel="Every supplier"
        />
        <FilterSelect
          value={statusFilter}
          onChange={setStatusFilter}
          options={ORDER.map((k) => ({ value: k, label: STATUS[k].label }))}
          allLabel="Any status"
        />
        <a
          className="btn-ghost ml-auto ring-1 ring-slate-200"
          href={`/api/v1/purchasing/bills?format=csv${
            supplierId ? `&supplier_id=${supplierId}` : ""
          }`}
        >
          Export CSV
        </a>
      </Toolbar>

      <div className="card overflow-x-auto p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {!loading && rows.length === 0 && (
          <EmptyState title="Nothing is owed" filtered={!!supplierId || !!statusFilter}>
            Bills appear here when a purchase goes on a supplier's account. A bullion
            bill paid in cash at the counter was never a debt and is not listed.
          </EmptyState>
        )}
        {rows.length > 0 && (
          <table className="w-full min-w-[56rem] text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Bill</th>
                <th className="px-4 py-3">Supplier</th>
                <th className="px-4 py-3">Dated</th>
                <th className="px-4 py-3">Due</th>
                <th className="px-4 py-3 text-right">Total</th>
                <th className="px-4 py-3 text-right">Paid</th>
                <th className="px-4 py-3 text-right">Outstanding</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((b) => (
                <tr
                  key={`${b.kind}-${b.purchase_id}`}
                  className={b.status === "paid" ? "opacity-60" : ""}
                >
                  <td className="px-4 py-3">
                    <span className="font-mono text-xs">{b.purchase_no}</span>
                    <span className="ml-2 text-xs text-slate-400">
                      {KIND[b.kind] ?? b.kind}
                    </span>
                    {b.reference && (
                      <span className="block text-xs text-slate-400">
                        their {b.reference}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">{b.supplier_name ?? "—"}</td>
                  <td className="num px-4 py-3 text-xs text-slate-500">{b.purchased_on}</td>
                  <td className="num px-4 py-3 text-xs">
                    {b.due_date ?? <span className="text-slate-400">—</span>}
                    {b.days_overdue ? (
                      <span className="block font-medium text-red-600">
                        {b.days_overdue} day{b.days_overdue === 1 ? "" : "s"} late
                      </span>
                    ) : null}
                  </td>
                  <td className="num px-4 py-3 text-right">{fmtMoney(b.total)}</td>
                  <td className="num px-4 py-3 text-right text-slate-600">
                    {n(b.paid) ? fmtMoney(b.paid) : "—"}
                  </td>
                  <td className="num px-4 py-3 text-right font-medium">
                    {fmtMoney(b.outstanding)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${
                        STATUS[b.status]?.className ?? "bg-slate-50 ring-slate-200"
                      }`}
                    >
                      {STATUS[b.status]?.label ?? b.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
        Paid and outstanding are worked out at read time: a supplier's payments are
        applied to their bills oldest first, so a bill's status can never disagree with
        the ledger. The cost of that is worth knowing — <strong>money paid for this
        week's bill will show as clearing the oldest one still open</strong>, which is how
        a running account is settled and not how a per-invoice ledger would behave.
      </p>

      {payments.length > 0 && (
        <section>
          <h2 className="eyebrow">Payments made</h2>
          <div className="card mt-2 overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Payment</th>
                  <th className="px-4 py-3">Supplier</th>
                  <th className="px-4 py-3">Method</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {payments.map((p) => (
                  <tr key={p.id} className={p.is_reversed ? "opacity-60" : ""}>
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs">{p.payment_no}</span>
                      {p.is_reversed && <span className="ml-2 chip-dead">reversed</span>}
                      {p.reference && (
                        <span className="block text-xs text-slate-400">{p.reference}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">{p.supplier_name ?? "—"}</td>
                    <td className="px-4 py-3 capitalize text-slate-600">{p.method}</td>
                    <td className="num px-4 py-3 text-right">{fmtMoney(p.amount)}</td>
                    <td className="px-4 py-3 text-right">
                      {!p.is_reversed && (
                        <button
                          className="text-xs text-red-600 hover:underline"
                          onClick={() => setReversing(p)}
                        >
                          Reverse
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {paying && (
        <PayForm
          suppliers={suppliers}
          onClose={() => setPaying(false)}
          onSaved={() => {
            setPaying(false);
            load();
          }}
        />
      )}

      <PasswordConfirm
        open={!!reversing}
        onClose={() => setReversing(null)}
        title={`Reverse ${reversing?.payment_no ?? ""}?`}
        description={
          "The payment row stays and the ledger takes a contra entry. The bills this " +
          "was clearing go back to outstanding."
        }
        confirmLabel="Reverse payment"
        onConfirm={reversePayment}
      />
    </div>
  );
}

function PayForm({
  suppliers,
  onClose,
  onSaved,
}: {
  suppliers: Named[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [supplierId, setSupplierId] = useState("");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [owed, setOwed] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);

  // What this supplier is owed, so the amount can be typed against a figure
  // rather than from memory — and so the preview below can show which bills it
  // will actually clear.
  useEffect(() => {
    if (!supplierId) {
      setOwed(null);
      return;
    }
    api
      .get<Report>("/purchasing/bills", { params: { supplier_id: supplierId } })
      .then((r) => setOwed(r.data))
      .catch(() => setOwed(null));
  }, [supplierId]);

  // The same oldest-first rule the server applies, run on screen before the
  // money moves. Nobody should discover which bills a payment cleared after
  // committing it.
  const preview = useMemo(() => {
    let pool = Number(amount) || 0;
    const open = (owed?.rows ?? [])
      .filter((b) => n(b.outstanding) > 0)
      .sort((a, b) => a.purchased_on.localeCompare(b.purchased_on));
    return open.map((b) => {
      const applied = Math.min(pool, n(b.outstanding));
      pool -= applied;
      return { bill: b, applied, left: n(b.outstanding) - applied };
    });
  }, [amount, owed]);

  const submit = async () => {
    if (!supplierId || !(Number(amount) > 0)) {
      toast("error", "Pick a supplier and an amount");
      return;
    }
    setBusy(true);
    try {
      await api.post("/purchasing/supplier-payments", {
        supplier_id: Number(supplierId),
        amount,
        method,
        reference: reference || null,
        notes: notes || null,
      });
      toast("success", "Payment recorded");
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not record the payment"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="Pay a supplier">
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <SelectField
            label="Supplier"
            required
            options={[
              { value: "", label: "Select…" },
              ...suppliers.map((s) => ({ value: s.id, label: s.name })),
            ]}
            value={supplierId}
            onChange={(e) => setSupplierId(e.target.value)}
          />
          <TextField
            label="Amount"
            type="number"
            step="0.01"
            min="0"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            hint={owed ? `${fmtMoney(owed.total_outstanding)} outstanding` : undefined}
          />
          {/* "On credit" is absent on purpose — settling a bill on credit is
              not a payment, it is the bill. The server refuses it too. */}
          <SelectField
            label="Paid by"
            options={[
              { value: "cash", label: "Cash" },
              { value: "bank", label: "Bank transfer" },
            ]}
            value={method}
            onChange={(e) => setMethod(e.target.value)}
          />
          <TextField
            label="Reference"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="Cheque or receipt no."
          />
        </div>

        {preview.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
            <p className="eyebrow">What this clears</p>
            <ul className="mt-2 space-y-1 text-xs">
              {preview.map(({ bill, applied, left }) => (
                <li
                  key={bill.purchase_no}
                  className={`num flex items-baseline justify-between gap-3 ${
                    applied > 0 ? "text-slate-800" : "text-slate-400"
                  }`}
                >
                  <span>
                    {bill.purchase_no}
                    <span className="ml-2 text-slate-400">{bill.purchased_on}</span>
                  </span>
                  <span>
                    {applied > 0 ? fmtMoney(applied) : "—"}
                    {applied > 0 && left > 0 && (
                      <span className="ml-2 text-amber-700">
                        {fmtMoney(left)} left
                      </span>
                    )}
                    {applied > 0 && left === 0 && (
                      <span className="ml-2 text-emerald-700">settled</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
              Oldest first. This is worked out the same way the server does it, so what
              you see here is what will happen.
            </p>
          </div>
        )}

        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />

        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose} type="button">
            Cancel
          </button>
          <button className="btn-primary" onClick={submit} disabled={busy}>
            {busy ? "Recording…" : "Record payment"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

const TONE = {
  plain: "bg-slate-50 text-slate-900 ring-slate-200",
  good: "bg-emerald-50 text-emerald-900 ring-emerald-200",
  bad: "bg-red-50 text-red-900 ring-red-200",
  warn: "bg-amber-50 text-amber-900 ring-amber-200",
};

function Stat({
  label,
  value,
  hint,
  tone = "plain",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: keyof typeof TONE;
}) {
  return (
    <div className={`rounded-lg px-3 py-2 ring-1 ${TONE[tone]}`}>
      <div className="text-xs uppercase opacity-70">{label}</div>
      <div className="num mt-0.5 text-lg font-semibold">{value}</div>
      {hint && <div className="mt-0.5 text-xs opacity-70">{hint}</div>}
    </div>
  );
}

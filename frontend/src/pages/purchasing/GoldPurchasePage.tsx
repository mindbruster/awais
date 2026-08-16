/**
 * Buying raw gold from a dealer — the metal the workshop makes from.
 *
 * Kept apart from the old-gold screen on purpose. That one is a customer
 * walking in with their own jewellery: one lot, cash across the counter,
 * priced below the day's rate because the spread is the margin. This is a
 * trade bill: a dealer, several bars, and often on account. Filing one as the
 * other makes the buy-back margin report meaningless and hides a payable.
 */
import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { FilterSelect, Toolbar } from "@/components/Toolbar";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { EmptyState } from "@/components/EmptyState";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Lot {
  id: number;
  description: string | null;
  purity: number;
  weight_g: string;
  rate_per_g: string;
  amount: string;
  fine_weight_g: string;
}

interface GoldPurchase {
  id: number;
  purchase_no: string;
  supplier_id: number;
  supplier_name: string | null;
  branch_name: string | null;
  purchased_at: string;
  reference: string | null;
  payment_mode: "cash" | "bank" | "credit";
  subtotal: string;
  extra_cost_pct: string;
  extra_cost_amount: string;
  total: string;
  item_count: number;
  total_weight_g: string;
  total_fine_g: string;
  effective_rate_per_fine_g: string;
  journal_entry_no: string | null;
  is_reversed: boolean;
  reversal_entry_no: string | null;
  notes: string | null;
  items?: Lot[];
}

interface Named {
  id: number;
  name: string;
}

const MODES = [
  { value: "cash", label: "Cash" },
  { value: "bank", label: "Bank transfer" },
  { value: "credit", label: "On account" },
];

const MODE_LABEL: Record<string, string> = {
  cash: "Cash",
  bank: "Bank",
  credit: "On account",
};

interface DraftLot {
  description: string;
  purity: string;
  weight_g: string;
  rate_per_g: string;
}

const blankLot = (): DraftLot => ({ description: "", purity: "24", weight_g: "", rate_per_g: "" });

const n = (v: string) => {
  const x = Number(v);
  return Number.isFinite(x) ? x : 0;
};

export function GoldPurchasePage() {
  const [rows, setRows] = useState<GoldPurchase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [suppliers, setSuppliers] = useState<Named[]>([]);
  const [modeFilter, setModeFilter] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [detail, setDetail] = useState<Record<number, Lot[]>>({});
  const [reversing, setReversing] = useState<GoldPurchase | null>(null);

  const [supplierId, setSupplierId] = useState("");
  const [reference, setReference] = useState("");
  const [paymentMode, setPaymentMode] = useState("cash");
  const [extraPct, setExtraPct] = useState("");
  const [notes, setNotes] = useState("");
  const [lots, setLots] = useState<DraftLot[]>([blankLot()]);
  const [submitting, setSubmitting] = useState(false);

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (modeFilter) params.payment_mode = modeFilter;
    api
      .get<GoldPurchase[]>("/purchasing/gold-purchases", { params })
      .then((r) => setRows(r.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [modeFilter]);

  useEffect(() => {
    api
      .get<Named[]>("/purchasing/suppliers", { params: { limit: 200 } })
      .then((r) => setSuppliers(r.data))
      .catch(() => setSuppliers([]));
  }, []);

  // Worked out on screen as the lots are typed, from the same rule the server
  // uses. A counter hand agreeing a bill needs the figure before they commit
  // it, not after.
  const totals = useMemo(() => {
    const subtotal = lots.reduce((t, l) => t + n(l.weight_g) * n(l.rate_per_g), 0);
    const weight = lots.reduce((t, l) => t + n(l.weight_g), 0);
    const fine = lots.reduce((t, l) => t + (n(l.weight_g) * n(l.purity)) / 24, 0);
    const total = subtotal * (1 + n(extraPct) / 100);
    return { subtotal, weight, fine, total, perFine: fine > 0 ? total / fine : 0 };
  }, [lots, extraPct]);

  const setLot = (i: number, patch: Partial<DraftLot>) =>
    setLots((prev) => prev.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!supplierId) {
      toast("error", "Pick a supplier first");
      return;
    }
    const usable = lots.filter((l) => n(l.weight_g) > 0);
    if (usable.length === 0) {
      toast("error", "Add at least one lot with a weight");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/purchasing/gold-purchases", {
        supplier_id: Number(supplierId),
        reference: reference || null,
        payment_mode: paymentMode,
        extra_cost_pct: extraPct || "0",
        notes: notes || null,
        items: usable.map((l) => ({
          description: l.description || null,
          purity: Number(l.purity),
          weight_g: l.weight_g,
          rate_per_g: l.rate_per_g || "0",
        })),
      });
      toast("success", "Gold purchase recorded");
      setReference("");
      setExtraPct("");
      setNotes("");
      setLots([blankLot()]);
      load();
    } catch (err) {
      toast("error", apiError(err, "Could not record the purchase"));
    } finally {
      setSubmitting(false);
    }
  };

  const open = async (row: GoldPurchase) => {
    if (expanded === row.id) {
      setExpanded(null);
      return;
    }
    setExpanded(row.id);
    if (!detail[row.id]) {
      try {
        const { data } = await api.get<GoldPurchase>(`/purchasing/gold-purchases/${row.id}`);
        setDetail((p) => ({ ...p, [row.id]: data.items ?? [] }));
      } catch {
        setDetail((p) => ({ ...p, [row.id]: [] }));
      }
    }
  };

  const confirmReverse = async (password: string) => {
    if (!reversing) return;
    try {
      await api.post(
        `/purchasing/gold-purchases/${reversing.id}/reverse`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${reversing.purchase_no} reversed`);
      setReversing(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Reversal failed"));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Gold purchases</h1>
        <p className="mt-1 text-sm text-slate-500">
          Raw gold bought in from a dealer — the metal the workshop makes from. Each lot goes
          into the melt pot for its purity. For a customer trading in their own jewellery, use
          Old gold instead.
        </p>
      </div>

      <form onSubmit={submit} className="card space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectField
            label="Dealer"
            required
            options={[
              { value: "", label: "Select a supplier…" },
              ...suppliers.map((s) => ({ value: s.id, label: s.name })),
            ]}
            value={supplierId}
            onChange={(e) => setSupplierId(e.target.value)}
          />
          <TextField
            label="Their bill no."
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            hint="So the two documents can be matched"
          />
          {/* Cash and bank leave the shop today; on account is a debt the books
              have to carry until it is settled. */}
          <SelectField
            label="Paid by"
            options={MODES}
            value={paymentMode}
            onChange={(e) => setPaymentMode(e.target.value)}
          />
          <TextField
            label="Carriage / assay %"
            type="number"
            step="0.001"
            value={extraPct}
            onChange={(e) => setExtraPct(e.target.value)}
            hint="Added on top and costed into the metal"
          />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3 font-medium">What it is</th>
                <th className="py-2 px-2 font-medium">Purity</th>
                <th className="py-2 px-2 text-right font-medium">Weight (g)</th>
                <th className="py-2 px-2 text-right font-medium">Rate / g</th>
                <th className="py-2 px-2 text-right font-medium">Amount</th>
                <th className="py-2 pl-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {lots.map((l, i) => (
                <tr key={i}>
                  <td className="py-2 pr-3">
                    <input
                      className="input w-full"
                      placeholder="TT bar 10 tola"
                      value={l.description}
                      onChange={(e) => setLot(i, { description: e.target.value })}
                    />
                  </td>
                  <td className="py-2 px-2">
                    <input
                      className="input w-20"
                      type="number"
                      min="1"
                      max="24"
                      value={l.purity}
                      onChange={(e) => setLot(i, { purity: e.target.value })}
                    />
                  </td>
                  <td className="py-2 px-2">
                    <input
                      className="input w-28 text-right"
                      type="number"
                      step="0.0001"
                      value={l.weight_g}
                      onChange={(e) => setLot(i, { weight_g: e.target.value })}
                    />
                  </td>
                  <td className="py-2 px-2">
                    <input
                      className="input w-32 text-right"
                      type="number"
                      step="0.0001"
                      value={l.rate_per_g}
                      onChange={(e) => setLot(i, { rate_per_g: e.target.value })}
                    />
                  </td>
                  <td className="num py-2 px-2 text-right text-slate-700">
                    {fmtMoney(n(l.weight_g) * n(l.rate_per_g))}
                  </td>
                  <td className="py-2 pl-2 text-right">
                    {lots.length > 1 && (
                      <button
                        type="button"
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => setLots((p) => p.filter((_, idx) => idx !== i))}
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <button
          type="button"
          className="btn-outline"
          onClick={() => setLots((p) => [...p, blankLot()])}
        >
          Add a lot
        </button>

        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />

        <div className="flex flex-wrap items-end justify-between gap-4 border-t border-slate-200 pt-4">
          <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs uppercase text-slate-500">Weight</dt>
              <dd className="num">{totals.weight.toFixed(3)} g</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-slate-500">Fine</dt>
              <dd className="num">{totals.fine.toFixed(3)} g</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-slate-500">Bill</dt>
              <dd className="num">{fmtMoney(totals.total)}</dd>
            </div>
            {/* The only figure that can honestly be held against the day's
                rate: loading included, and against fine grams. */}
            <div>
              <dt className="text-xs uppercase text-slate-500">Cost / fine g</dt>
              <dd className="num">{fmtMoney(totals.perFine)}</dd>
            </div>
          </dl>
          <button className="btn-primary" disabled={submitting}>
            {submitting ? "Recording…" : "Record purchase"}
          </button>
        </div>
      </form>

      <Toolbar>
        <FilterSelect
          value={modeFilter}
          onChange={setModeFilter}
          options={MODES}
          allLabel="Any payment"
        />
        <span className="ml-auto text-xs text-slate-500">{rows.length} shown</span>
      </Toolbar>

      <div className="card overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && rows.length === 0 && (
          <EmptyState title="No gold bought in yet" filtered={!!modeFilter}>
            When you buy bullion from a dealer, record it here and the metal lands in the melt
            pot for its purity.
          </EmptyState>
        )}
        {rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Bill</th>
                <th className="px-4 py-3">Dealer</th>
                <th className="px-4 py-3">Paid by</th>
                <th className="px-4 py-3 text-right">Weight</th>
                <th className="px-4 py-3 text-right">Fine</th>
                <th className="px-4 py-3 text-right">Total</th>
                <th className="px-4 py-3 text-right">Cost / fine g</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <>
                  <tr
                    key={r.id}
                    className={`cursor-pointer hover:bg-slate-50 ${r.is_reversed ? "opacity-60" : ""}`}
                    onClick={() => open(r)}
                  >
                    <td className="px-4 py-3 font-mono text-xs">
                      {r.purchase_no}
                      {r.is_reversed && (
                        <span className="ml-2 chip-dead">reversed</span>
                      )}
                      {r.reference && (
                        <span className="block text-slate-400">their {r.reference}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">{r.supplier_name ?? "—"}</td>
                    <td className="px-4 py-3">
                      {MODE_LABEL[r.payment_mode] ?? r.payment_mode}
                    </td>
                    <td className="num px-4 py-3 text-right">
                      {Number(r.total_weight_g).toFixed(3)} g
                    </td>
                    <td className="num px-4 py-3 text-right">
                      {Number(r.total_fine_g).toFixed(3)} g
                    </td>
                    <td className="num px-4 py-3 text-right font-medium">
                      {fmtMoney(r.total)}
                    </td>
                    <td className="num px-4 py-3 text-right">
                      {fmtMoney(r.effective_rate_per_fine_g)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {!r.is_reversed && (
                        <button
                          className="text-xs text-red-600 hover:underline"
                          onClick={(e) => {
                            e.stopPropagation();
                            setReversing(r);
                          }}
                        >
                          Reverse
                        </button>
                      )}
                    </td>
                  </tr>
                  {expanded === r.id && (
                    <tr key={`${r.id}-lots`} className="bg-slate-50/60">
                      <td colSpan={8} className="px-4 py-3">
                        <div className="text-xs uppercase text-slate-500">
                          {r.item_count} lot(s)
                          {Number(r.extra_cost_pct) > 0 && (
                            <> · carriage {Number(r.extra_cost_pct)}% = {fmtMoney(r.extra_cost_amount)}</>
                          )}
                          {r.journal_entry_no && <> · entry {r.journal_entry_no}</>}
                        </div>
                        <ul className="mt-2 space-y-1 text-sm">
                          {(detail[r.id] ?? []).map((l) => (
                            <li key={l.id} className="num">
                              {l.description ? `${l.description} — ` : ""}
                              {Number(l.weight_g).toFixed(3)} g at {l.purity}k
                              {" @ "}
                              {fmtMoney(l.rate_per_g)}/g = {fmtMoney(l.amount)}
                              <span className="ml-2 text-xs text-slate-500">
                                {Number(l.fine_weight_g).toFixed(3)} g fine
                              </span>
                            </li>
                          ))}
                        </ul>
                        {r.notes && <p className="mt-2 text-xs text-slate-500">{r.notes}</p>}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <PasswordConfirm
        open={!!reversing}
        onClose={() => setReversing(null)}
        title={`Reverse ${reversing?.purchase_no ?? ""}?`}
        description="The metal comes back out of the safe and the money goes back where it came from. The bill is not deleted — a reversing entry is posted against it. If any of this gold has already gone to a worker, the reversal will be refused."
        onConfirm={confirmReverse}
      />
    </div>
  );
}

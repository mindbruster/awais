import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextField } from "@/components/Field";
import { Toolbar } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Supplier {
  id: number;
  name: string;
  is_active: boolean;
}

interface Stone {
  id: number;
  name: string;
  kind: string;
  category: "stone" | "diamond";
  quality: string | null;
  cut: string | null;
  color: string | null;
  clarity: string | null;
  default_rate_per_ct: string | null;
}

interface PurchaseItem {
  id: number;
  stone_id: number;
  stone_name: string | null;
  quantity: number;
  weight_ct: string;
  rate_per_ct: string;
  amount: string;
  quality: string | null;
  cut: string | null;
  color: string | null;
  clarity: string | null;
}

interface Purchase {
  id: number;
  purchase_no: string;
  supplier_id: number;
  supplier_name: string | null;
  purchased_at: string;
  reference: string | null;
  subtotal: string;
  extra_cost_pct: string;
  extra_cost_amount: string;
  total: string;
  item_count: number;
  total_weight_ct: string;
  journal_entry_no: string | null;
  notes: string | null;
  items?: PurchaseItem[];
}

/** One row in the line editor. Everything is a string: these are inputs, and
 *  parsing them early is how a typed "0.05" becomes 0.05000000000000001. */
interface LineDraft {
  key: number;
  stone_id: string;
  quantity: string;
  weight_ct: string;
  rate_per_ct: string;
  quality: string;
  cut: string;
  color: string;
  clarity: string;
}

const num = (v: string) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

let nextKey = 1;
const blankLine = (): LineDraft => ({
  key: nextKey++,
  stone_id: "",
  quantity: "",
  weight_ct: "",
  rate_per_ct: "",
  quality: "",
  cut: "",
  color: "",
  clarity: "",
});

export function StonePurchasePage() {
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [stones, setStones] = useState<Stone[]>([]);
  const [viewing, setViewing] = useState<Purchase | null>(null);

  const [supplierFilter, setSupplierFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [supplierId, setSupplierId] = useState("");
  const [reference, setReference] = useState("");
  const [extraPct, setExtraPct] = useState("0");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([blankLine()]);
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (supplierFilter) params.supplier_id = supplierFilter;
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    api
      .get<Purchase[]>("/purchasing/stone-purchases", { params })
      .then((r) => setPurchases(r.data))
      .catch((e) => setError(apiError(e, "Failed to load purchases")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [supplierFilter, dateFrom, dateTo]);

  useEffect(() => {
    api
      .get<Supplier[]>("/purchasing/suppliers", { params: { is_active: "true" } })
      .then((r) => setSuppliers(r.data))
      .catch(() => setSuppliers([]));
    api
      .get<Stone[]>("/stones", { params: { limit: "300" } })
      .then((r) => setStones(r.data))
      .catch(() => setStones([]));
  }, []);

  const stoneById = useMemo(
    () => Object.fromEntries(stones.map((s) => [String(s.id), s])),
    [stones],
  );

  const setLine = (key: number, patch: Partial<LineDraft>) =>
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  /** Picking a stone copies its grading and default rate in as a starting
   *  point. They stay editable because the bill, not the catalogue, is the
   *  record of what actually arrived — and what is typed here is frozen onto
   *  the line at save. */
  const pickStone = (key: number, stoneId: string) => {
    const s = stoneById[stoneId];
    setLine(key, {
      stone_id: stoneId,
      quality: s?.quality ?? "",
      cut: s?.cut ?? "",
      color: s?.color ?? "",
      clarity: s?.clarity ?? "",
      rate_per_ct: s?.default_rate_per_ct ?? "",
    });
  };

  const totals = useMemo(() => {
    const subtotal = lines.reduce(
      (sum, l) => sum + num(l.weight_ct) * num(l.rate_per_ct),
      0,
    );
    const extra = (subtotal * num(extraPct)) / 100;
    return {
      subtotal,
      extra,
      total: subtotal + extra,
      carats: lines.reduce((sum, l) => sum + num(l.weight_ct), 0),
      stones: lines.reduce((sum, l) => sum + num(l.quantity), 0),
    };
  }, [lines, extraPct]);

  const usable = lines.filter((l) => l.stone_id && num(l.weight_ct) > 0);
  const canSubmit = supplierId !== "" && usable.length > 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await api.post<Purchase>("/purchasing/stone-purchases", {
        supplier_id: Number(supplierId),
        reference: reference || null,
        extra_cost_pct: extraPct || "0",
        notes: notes || null,
        items: usable.map((l) => ({
          stone_id: Number(l.stone_id),
          quantity: Number(l.quantity || 0),
          weight_ct: l.weight_ct,
          rate_per_ct: l.rate_per_ct || "0",
          quality: l.quality || null,
          cut: l.cut || null,
          color: l.color || null,
          clarity: l.clarity || null,
        })),
      });
      toast("success", `${res.data.purchase_no} booked — ${fmtMoney(res.data.total)}`);
      setReference("");
      setNotes("");
      setExtraPct("0");
      setLines([blankLine()]);
      load();
    } catch (err) {
      toast("error", apiError(err, "Could not save the purchase"));
    } finally {
      setSaving(false);
    }
  };

  const openDetail = async (p: Purchase) => {
    try {
      const res = await api.get<Purchase>(`/purchasing/stone-purchases/${p.id}`);
      setViewing(res.data);
    } catch (err) {
      toast("error", apiError(err, "Could not load the bill"));
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Stone purchases</h1>
      <p className="mt-1 text-sm text-slate-500">
        A supplier's bill, lot by lot. Each line's grading is written onto the bill as it stands
        today, so renaming a grade later never rewrites what was bought. Freight and
        certification go on as a percentage of the goods, the way the bills arrive.
      </p>

      <form onSubmit={submit} className="card mt-5 space-y-4">
        <div className="grid gap-3 md:grid-cols-4">
          <SelectField
            label="Supplier"
            required
            value={supplierId}
            onChange={(e) => setSupplierId(e.target.value)}
            options={[
              { value: "", label: "Select a supplier…" },
              ...suppliers.map((s) => ({ value: String(s.id), label: s.name })),
            ]}
          />
          <TextField
            label="Bill reference"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="Supplier's own number"
          />
          <TextField
            label="Extra cost %"
            type="number"
            min="0"
            max="100"
            step="0.001"
            value={extraPct}
            onChange={(e) => setExtraPct(e.target.value)}
            hint="Applied to the subtotal."
          />
          <TextField
            label="Notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">Stone</th>
                <th className="px-3 py-2">Quality</th>
                <th className="px-3 py-2">Cut</th>
                <th className="px-3 py-2">Colour</th>
                <th className="px-3 py-2">Clarity</th>
                <th className="px-3 py-2 text-right">Pieces</th>
                <th className="px-3 py-2 text-right">Carats</th>
                <th className="px-3 py-2 text-right">Rate/ct</th>
                <th className="px-3 py-2 text-right">Amount</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {lines.map((l) => (
                <tr key={l.key}>
                  <td className="px-3 py-2">
                    <select
                      className="input min-w-[160px]"
                      value={l.stone_id}
                      onChange={(e) => pickStone(l.key, e.target.value)}
                    >
                      <option value="">Select…</option>
                      {stones.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  {(["quality", "cut", "color", "clarity"] as const).map((f) => (
                    <td key={f} className="px-3 py-2">
                      <input
                        className="input min-w-[100px]"
                        value={l[f]}
                        onChange={(e) => setLine(l.key, { [f]: e.target.value })}
                      />
                    </td>
                  ))}
                  <td className="px-3 py-2">
                    <input
                      className="input w-24 text-right"
                      type="number"
                      min="0"
                      step="1"
                      value={l.quantity}
                      onChange={(e) => setLine(l.key, { quantity: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      className="input w-28 text-right"
                      type="number"
                      min="0"
                      step="0.0001"
                      value={l.weight_ct}
                      onChange={(e) => setLine(l.key, { weight_ct: e.target.value })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      className="input w-28 text-right"
                      type="number"
                      min="0"
                      step="0.0001"
                      value={l.rate_per_ct}
                      onChange={(e) => setLine(l.key, { rate_per_ct: e.target.value })}
                    />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right font-medium">
                    {fmtMoney(num(l.weight_ct) * num(l.rate_per_ct))}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      className="text-xs text-red-600 hover:underline disabled:opacity-40"
                      disabled={lines.length === 1}
                      onClick={() => setLines((p) => p.filter((x) => x.key !== l.key))}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-end justify-between gap-4">
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setLines((p) => [...p, blankLine()])}
          >
            + Add line
          </button>

          <dl className="w-full max-w-xs space-y-1 text-sm sm:w-auto">
            <div className="flex justify-between gap-8">
              <dt className="text-slate-500">
                {totals.stones} pieces · {totals.carats.toFixed(4)} ct
              </dt>
              <dd />
            </div>
            <div className="flex justify-between gap-8">
              <dt className="text-slate-500">Subtotal</dt>
              <dd className="font-medium">{fmtMoney(totals.subtotal)}</dd>
            </div>
            <div className="flex justify-between gap-8">
              <dt className="text-slate-500">Extra cost ({num(extraPct)}%)</dt>
              <dd className="font-medium">{fmtMoney(totals.extra)}</dd>
            </div>
            <div className="flex justify-between gap-8 border-t border-slate-200 pt-1">
              <dt className="font-medium text-slate-700">Payable to supplier</dt>
              <dd className="text-base font-semibold">{fmtMoney(totals.total)}</dd>
            </div>
          </dl>

          <button type="submit" className="btn-primary" disabled={saving || !canSubmit}>
            {saving ? "Saving…" : "Record purchase"}
          </button>
        </div>
      </form>

      <Toolbar>
        <select
          className="input w-auto"
          value={supplierFilter}
          onChange={(e) => setSupplierFilter(e.target.value)}
        >
          <option value="">All suppliers</option>
          {suppliers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-xs text-slate-500">
          From
          <input
            type="date"
            className="input w-auto"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-500">
          To
          <input
            type="date"
            className="input w-auto"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>
        <span className="ml-auto text-xs text-slate-500">{purchases.length} shown</span>
      </Toolbar>

      <div className="card mt-4 overflow-x-auto p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && purchases.length === 0 && (
          <div className="p-6 text-sm text-slate-500">No stone bills in this window.</div>
        )}
        {purchases.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="whitespace-nowrap px-4 py-3">No.</th>
                <th className="whitespace-nowrap px-4 py-3">Date</th>
                <th className="whitespace-nowrap px-4 py-3">Supplier</th>
                <th className="whitespace-nowrap px-4 py-3">Reference</th>
                <th className="whitespace-nowrap px-4 py-3 text-right">Lots</th>
                <th className="whitespace-nowrap px-4 py-3 text-right">Carats</th>
                <th className="whitespace-nowrap px-4 py-3 text-right">Subtotal</th>
                <th className="whitespace-nowrap px-4 py-3 text-right">Extra</th>
                <th className="whitespace-nowrap px-4 py-3 text-right">Total</th>
                <th className="whitespace-nowrap px-4 py-3">Entry</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {purchases.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="whitespace-nowrap px-4 py-3 font-medium">{p.purchase_no}</td>
                  <td className="whitespace-nowrap px-4 py-3">{p.purchased_at.slice(0, 10)}</td>
                  <td className="px-4 py-3">{p.supplier_name ?? "—"}</td>
                  <td className="px-4 py-3">{p.reference ?? "—"}</td>
                  <td className="px-4 py-3 text-right">{p.item_count}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {Number(p.total_weight_ct).toFixed(4)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {fmtMoney(p.subtotal)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {fmtMoney(p.extra_cost_amount)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-medium">
                    {fmtMoney(p.total)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
                    {p.journal_entry_no ?? "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    <button
                      className="text-xs text-brand-700 hover:underline"
                      onClick={() => openDetail(p)}
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Modal
        open={!!viewing}
        onClose={() => setViewing(null)}
        title={viewing ? `${viewing.purchase_no} — ${viewing.supplier_name ?? ""}` : ""}
      >
        {viewing && (
          <div className="space-y-4">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Stone</th>
                    <th className="px-3 py-2">Grade</th>
                    <th className="px-3 py-2 text-right">Pieces</th>
                    <th className="px-3 py-2 text-right">Carats</th>
                    <th className="px-3 py-2 text-right">Rate/ct</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(viewing.items ?? []).map((i) => (
                    <tr key={i.id}>
                      <td className="px-3 py-2 font-medium">{i.stone_name}</td>
                      <td className="px-3 py-2 text-xs text-slate-500">
                        {[i.quality, i.cut, i.color, i.clarity].filter(Boolean).join(" / ") ||
                          "ungraded"}
                      </td>
                      <td className="px-3 py-2 text-right">{i.quantity}</td>
                      <td className="px-3 py-2 text-right">{Number(i.weight_ct).toFixed(4)}</td>
                      <td className="px-3 py-2 text-right">{fmtMoney(i.rate_per_ct)}</td>
                      <td className="px-3 py-2 text-right font-medium">{fmtMoney(i.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="space-y-1 border-t border-slate-200 pt-3 text-sm">
              <div className="flex justify-between">
                <dt className="text-slate-500">Subtotal</dt>
                <dd>{fmtMoney(viewing.subtotal)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-slate-500">
                  Extra cost ({Number(viewing.extra_cost_pct)}%)
                </dt>
                <dd>{fmtMoney(viewing.extra_cost_amount)}</dd>
              </div>
              <div className="flex justify-between font-semibold">
                <dt>Total</dt>
                <dd>{fmtMoney(viewing.total)}</dd>
              </div>
            </dl>
            {viewing.journal_entry_no && (
              <p className="text-xs text-slate-500">
                Posted as {viewing.journal_entry_no}: Stone Inventory debited, the supplier
                credited.
              </p>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

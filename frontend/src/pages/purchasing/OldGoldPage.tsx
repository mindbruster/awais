import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { FilterSelect, Toolbar } from "@/components/Toolbar";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface OldGold {
  id: number;
  purchase_no: string;
  customer_id: number | null;
  customer_name: string | null;
  walk_in_name: string | null;
  seller_name: string;
  kind: "pure" | "used";
  weight_g: string;
  purity: number | null;
  rate_per_g: string;
  amount: string;
  fine_weight_g: string;
  effective_rate_per_fine_g: string;
  journal_entry_no: string | null;
  is_reversed: boolean;
  reversal_entry_no: string | null;
  purchased_at: string;
  notes: string | null;
}

interface CustomerOption {
  id: number;
  name: string;
}

const KINDS = [
  { value: "used", label: "Used jewellery" },
  { value: "pure", label: "Pure / bullion" },
];

const num = (v: string) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

const fmtG = (v: string | number) => `${Number(v).toFixed(4)} g`;

export function OldGoldPage() {
  const [rows, setRows] = useState<OldGold[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [customers, setCustomers] = useState<CustomerOption[]>([]);
  const [marketRate, setMarketRate] = useState<string | null>(null);

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [kindFilter, setKindFilter] = useState("");

  const [sellerMode, setSellerMode] = useState<"walk_in" | "customer">("walk_in");
  const [walkIn, setWalkIn] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [kind, setKind] = useState<"pure" | "used">("used");
  const [weight, setWeight] = useState("");
  const [purity, setPurity] = useState("22");
  const [rate, setRate] = useState("");
  const [notes, setNotes] = useState("");
  const [allowAbove, setAllowAbove] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reversing, setReversing] = useState<OldGold | null>(null);

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;
    if (kindFilter) params.kind = kindFilter;
    api
      .get<OldGold[]>("/purchasing/old-gold", { params })
      .then((r) => setRows(r.data))
      .catch((e) => setError(apiError(e, "Failed to load purchases")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [dateFrom, dateTo, kindFilter]);

  useEffect(() => {
    api
      .get<CustomerOption[]>("/customers", { params: { limit: "300" } })
      .then((r) => setCustomers(r.data))
      .catch(() => setCustomers([]));
    // The day's rate is shown beside the input purely so the counter can see
    // the spread it is buying at. It is never copied into the rate field:
    // buying at rate is buying at no margin, and a default that did that
    // would be invisible on every ticket afterwards.
    api
      .get<{ rate_per_g: string }>("/gold-rates/current", { params: { purity: "24" } })
      .then((r) => setMarketRate(r.data.rate_per_g))
      .catch(() => setMarketRate(null));
  }, []);

  // Mirrors what the server will compute. Shown live so the spread is visible
  // before the money leaves the till, never used in place of the server's own
  // figures — the row that comes back is what got booked.
  const preview = useMemo(() => {
    const w = num(weight);
    const r = num(rate);
    const p = kind === "pure" ? num(purity) || 24 : num(purity);
    const fine = p > 0 ? (w * p) / 24 : 0;
    const amount = w * r;
    const perFine = fine > 0 ? amount / fine : 0;
    const market = marketRate ? Number(marketRate) : 0;
    return {
      fine,
      amount,
      perFine,
      market,
      spread: market > 0 ? market - perFine : 0,
      spreadPct: market > 0 && perFine > 0 ? ((market - perFine) / market) * 100 : 0,
      aboveMarket: market > 0 && perFine >= market,
    };
  }, [weight, rate, purity, kind, marketRate]);

  const canSubmit =
    num(weight) > 0 &&
    num(rate) > 0 &&
    (sellerMode === "walk_in" ? walkIn.trim().length > 0 : customerId !== "") &&
    (kind === "pure" || num(purity) > 0) &&
    (!preview.aboveMarket || allowAbove);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        kind,
        weight_g: weight,
        rate_per_g: rate,
        notes: notes || null,
        allow_above_market: allowAbove,
      };
      if (sellerMode === "customer") body.customer_id = Number(customerId);
      else body.walk_in_name = walkIn.trim();
      if (purity) body.purity = Number(purity);

      const res = await api.post<OldGold>("/purchasing/old-gold", body);
      toast(
        "success",
        `${res.data.purchase_no}: ${fmtG(res.data.weight_g)} in, ${fmtMoney(res.data.amount)} out`,
      );
      setWeight("");
      setRate("");
      setNotes("");
      setWalkIn("");
      setAllowAbove(false);
      load();
    } catch (err) {
      toast("error", apiError(err, "Could not record the purchase"));
    } finally {
      setSaving(false);
    }
  };

  const confirmReverse = async (password: string) => {
    if (!reversing) return;
    try {
      const res = await api.post<OldGold>(
        `/purchasing/old-gold/${reversing.id}/reverse`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${reversing.purchase_no} reversed by ${res.data.reversal_entry_no}`);
      setReversing(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Reversal failed"));
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Old gold</h1>
      <p className="mt-1 text-sm text-slate-500">
        Metal bought back over the counter. The shop buys below the day's rate — that spread is
        the margin, so the rate is always typed, never filled in for you. Each purchase puts the
        metal into the melt pot for its purity and pays for it out of cash in hand.
      </p>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,420px)_1fr]">
        <form onSubmit={submit} className="card space-y-4 self-start">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Buy over the counter
          </h2>

          <div className="flex rounded-lg border border-slate-200 p-0.5 text-sm">
            {(
              [
                ["walk_in", "Walk-in"],
                ["customer", "Customer"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setSellerMode(value)}
                className={`flex-1 rounded-md px-3 py-1.5 transition ${
                  sellerMode === value
                    ? "bg-brand-600 font-medium text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {sellerMode === "walk_in" ? (
            <TextField
              label="Walk-in name"
              required
              value={walkIn}
              onChange={(e) => setWalkIn(e.target.value)}
              placeholder="Who handed the metal over"
              hint="Walk-ins often decline to be put on file; a name is enough."
            />
          ) : (
            <SelectField
              label="Customer"
              required
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              options={[
                { value: "", label: "Select a customer…" },
                ...customers.map((c) => ({ value: String(c.id), label: c.name })),
              ]}
            />
          )}

          <div className="grid grid-cols-2 gap-3">
            <SelectField
              label="Kind"
              options={KINDS}
              value={kind}
              onChange={(e) => setKind(e.target.value as "pure" | "used")}
            />
            <TextField
              label="Purity (k)"
              type="number"
              min={1}
              max={24}
              step="1"
              required={kind === "used"}
              value={purity}
              onChange={(e) => setPurity(e.target.value)}
              hint={kind === "used" ? "Required — the price was struck on it." : "Blank = 24k."}
            />
            <TextField
              label="Weight (g)"
              type="number"
              min="0"
              step="0.0001"
              required
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
            />
            <TextField
              label="Rate paid per gram"
              type="number"
              min="0"
              step="0.0001"
              required
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              hint={
                marketRate
                  ? `Day's 24k rate: ${fmtMoney(marketRate)}/fine g`
                  : "No 24k rate on record today."
              }
            />
          </div>

          <dl className="space-y-1.5 rounded-lg bg-slate-50 p-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Fine (24k-equivalent)</dt>
              <dd className="font-medium text-slate-900">{fmtG(preview.fine)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Paid per fine gram</dt>
              <dd className="font-medium text-slate-900">
                {preview.perFine > 0 ? fmtMoney(preview.perFine) : "—"}
              </dd>
            </div>
            {preview.market > 0 && (
              <div className="flex justify-between">
                <dt className="text-slate-500">Spread below rate</dt>
                <dd
                  className={`font-medium ${
                    preview.spread > 0 ? "text-emerald-700" : "text-red-600"
                  }`}
                >
                  {preview.perFine > 0
                    ? `${fmtMoney(preview.spread)} (${preview.spreadPct.toFixed(2)}%)`
                    : "—"}
                </dd>
              </div>
            )}
            <div className="flex justify-between border-t border-slate-200 pt-1.5">
              <dt className="font-medium text-slate-700">Cash out</dt>
              <dd className="text-base font-semibold text-slate-900">
                {fmtMoney(preview.amount)}
              </dd>
            </div>
          </dl>

          {preview.aboveMarket && (
            <label className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4"
                checked={allowAbove}
                onChange={(e) => setAllowAbove(e.target.checked)}
              />
              <span>
                This pays at or above the day's rate — a loss, not a purchase. Tick to book it
                anyway.
              </span>
            </label>
          )}

          <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />

          <button type="submit" className="btn-primary w-full" disabled={saving || !canSubmit}>
            {saving ? "Recording…" : "Record purchase"}
          </button>
        </form>

        <div>
          <Toolbar>
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
            <FilterSelect
              value={kindFilter}
              onChange={setKindFilter}
              options={KINDS}
              allLabel="All kinds"
            />
            <span className="ml-auto text-xs text-slate-500">{rows.length} shown</span>
          </Toolbar>

          <div className="card mt-4 overflow-x-auto p-0">
            {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
            {error && <div className="p-6 text-sm text-red-600">{error}</div>}
            {!loading && !error && rows.length === 0 && (
              <div className="p-6 text-sm text-slate-500">No buy-backs in this window.</div>
            )}
            {rows.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="whitespace-nowrap px-4 py-3">No.</th>
                    <th className="whitespace-nowrap px-4 py-3">Date</th>
                    <th className="whitespace-nowrap px-4 py-3">From</th>
                    <th className="whitespace-nowrap px-4 py-3">Kind</th>
                    <th className="whitespace-nowrap px-4 py-3 text-right">Weight</th>
                    <th className="whitespace-nowrap px-4 py-3 text-right">Fine</th>
                    <th className="whitespace-nowrap px-4 py-3 text-right">Rate/g</th>
                    <th className="whitespace-nowrap px-4 py-3 text-right">Amount</th>
                    <th className="whitespace-nowrap px-4 py-3">Entry</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {rows.map((r) => (
                    <tr
                      key={r.id}
                      className={r.is_reversed ? "text-slate-400" : "hover:bg-slate-50"}
                    >
                      <td className="whitespace-nowrap px-4 py-3 font-medium">
                        {r.purchase_no}
                        {r.is_reversed && (
                          <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase text-slate-500">
                            reversed
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {r.purchased_at.slice(0, 10)}
                      </td>
                      <td className="px-4 py-3">{r.seller_name}</td>
                      <td className="px-4 py-3">
                        {r.kind === "used" ? "Used" : "Pure"}
                        {r.purity ? ` ${r.purity}k` : ""}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        {fmtG(r.weight_g)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        {fmtG(r.fine_weight_g)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        {fmtMoney(r.rate_per_g)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right font-medium">
                        {fmtMoney(r.amount)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
                        {r.reversal_entry_no
                          ? `${r.journal_entry_no} → ${r.reversal_entry_no}`
                          : r.journal_entry_no ?? "—"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        {!r.is_reversed && (
                          <button
                            className="text-xs text-red-600 hover:underline"
                            onClick={() => setReversing(r)}
                          >
                            Reverse
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      <PasswordConfirm
        open={!!reversing}
        onClose={() => setReversing(null)}
        title={`Reverse ${reversing?.purchase_no ?? ""}?`}
        description={
          `The metal comes back out of stock and the cash back into the till. The purchase is ` +
          `not deleted — a reversing entry is posted against it, so the books can still explain ` +
          `what happened. If the gold has already gone out to a worker this will be refused.`
        }
        confirmLabel="Reverse purchase"
        onConfirm={confirmReverse}
      />
    </div>
  );
}

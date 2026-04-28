import { FormEvent, useEffect, useState } from "react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextField } from "@/components/Field";
import { FilterSelect, Toolbar } from "@/components/Toolbar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { CURRENCY_OPTIONS, Currency, fmtMoney } from "@/lib/money";

interface Rate {
  id: number;
  rate_date: string; // YYYY-MM-DD
  currency: Currency;
  rate_per_g: string;
  purity: number;
  notes: string | null;
  created_at: string;
}

const today = () => new Date().toISOString().slice(0, 10);

export function GoldRatesPage() {
  const [rates, setRates] = useState<Rate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState<Rate | null>(null);
  const [busyDelete, setBusyDelete] = useState(false);
  const [currency, setCurrency] = useState("");

  const load = () => {
    setLoading(true);
    api
      .get<Rate[]>("/gold-rates", { params: currency ? { currency } : {} })
      .then((r) => setRates(r.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [currency]);

  const confirmDelete = async () => {
    if (!deleting) return;
    setBusyDelete(true);
    try {
      await api.delete(`/gold-rates/${deleting.id}`);
      toast("success", "Rate deleted");
      setDeleting(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Delete failed"));
    } finally {
      setBusyDelete(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Gold rates</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          Set new rate
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Latest rate per (currency, purity) is auto-applied to new invoices. Pricing engine
        adjusts non-24k purities automatically.
      </p>
      <Toolbar>
        <FilterSelect
          value={currency}
          onChange={setCurrency}
          options={CURRENCY_OPTIONS}
          allLabel="All currencies"
        />
        <span className="ml-auto text-xs text-slate-500">{rates.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && rates.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            No rates yet. Set one to enable pricing on invoices.
          </div>
        )}
        {rates.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Currency</th>
                <th className="px-4 py-3 text-right">Purity</th>
                <th className="px-4 py-3 text-right">Rate / g</th>
                <th className="px-4 py-3">Notes</th>
                <th className="px-4 py-3 text-xs">Recorded</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rates.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium">{r.rate_date}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                      {r.currency}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">{r.purity}k</td>
                  <td className="px-4 py-3 text-right font-mono">
                    {fmtMoney(r.rate_per_g, r.currency)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{r.notes ?? "—"}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="text-xs text-red-600 hover:underline"
                      onClick={() => setDeleting(r)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <NewRateModal open={open} onClose={() => setOpen(false)} onCreated={() => { setOpen(false); load(); }} />
      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title="Delete this rate?"
        description="The next-most-recent rate (if any) becomes the current rate."
        destructive
        confirmLabel="Delete"
        busy={busyDelete}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function NewRateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [date, setDate] = useState(today());
  const [currency, setCurrency] = useState<Currency>("PKR");
  const [rate, setRate] = useState("");
  const [purity, setPurity] = useState("24");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setDate(today());
      setRate("");
      setNotes("");
    }
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/gold-rates", {
        rate_date: date,
        currency,
        rate_per_g: rate || "0",
        purity: parseInt(purity || "24", 10),
        notes: notes || null,
      });
      toast("success", `Rate ${rate} ${currency}/g set`);
      onCreated();
    } catch (err) {
      toast("error", apiError(err, "Could not save rate"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Set gold rate">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Rate date"
            type="date"
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
          <SelectField
            label="Currency"
            options={CURRENCY_OPTIONS}
            value={currency}
            onChange={(e) => setCurrency(e.target.value as Currency)}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Rate per gram"
            type="number"
            step="0.0001"
            min={0.0001}
            required
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            hint={`Stored as ${currency} per gram at the chosen purity`}
          />
          <TextField
            label="Purity (k)"
            type="number"
            min={1}
            max={24}
            value={purity}
            onChange={(e) => setPurity(e.target.value)}
            hint="24 is standard"
          />
        </div>
        <TextField
          label="Notes (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy || !rate}>
            {busy ? "Saving…" : "Save rate"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

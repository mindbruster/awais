import { Fragment, useEffect, useState } from "react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { FilterSelect, Toolbar } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

type Commodity = "PKR" | "USD" | "GOLD";
type PartyType = "" | "customer" | "worker" | "supplier";

interface AccountOption {
  id: number;
  code: string;
  name: string;
  is_postable: boolean;
}

interface Party {
  id: number;
  name: string;
}

interface JournalLine {
  id: number;
  account_id: number;
  account_code: string;
  account_name: string;
  commodity: Commodity;
  quantity: string;
  rate: string;
  value_pkr: string;
  native_weight_g: string | null;
  native_purity: number | null;
  party_type: string | null;
  party_id: number | null;
  memo: string | null;
}

interface JournalEntry {
  id: number;
  entry_no: string;
  entry_date: string;
  memo: string | null;
  source_type: string | null;
  source_id: number | null;
  reverses_entry_id: number | null;
  posted_at: string;
  total_debit: string;
  total_credit: string;
  lines: JournalLine[];
}

const SOURCE_TYPES = [
  { value: "manual", label: "Manual voucher" },
  { value: "opening_balance", label: "Opening balance" },
  { value: "manufacturing_leg", label: "Manufacturing" },
  { value: "invoice", label: "Invoice" },
];

const COMMODITIES = [
  { value: "PKR", label: "PKR" },
  { value: "USD", label: "USD" },
  { value: "GOLD", label: "GOLD" },
];

const PARTY_TYPES = [
  { value: "", label: "—" },
  { value: "customer", label: "Customer" },
  { value: "worker", label: "Worker" },
  { value: "supplier", label: "Supplier" },
];

const fmtQty = (q: string, commodity: Commodity) =>
  commodity === "GOLD" ? `${Number(q).toFixed(4)} g` : fmtMoney(q, commodity);

export function JournalPage() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [creating, setCreating] = useState(false);
  const [reversing, setReversing] = useState<JournalEntry | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    const params: Record<string, string> = { limit: "200" };
    if (source) params.source_type = source;
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    api
      .get<JournalEntry[]>("/ledger/entries", { params })
      .then((res) => setEntries(res.data))
      .catch((e) => setError(apiError(e, "Failed to load the journal")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [source, from, to]);

  const toggle = (id: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const confirmReverse = async (password: string) => {
    if (!reversing) return;
    try {
      const { data } = await api.post<JournalEntry>(
        `/ledger/entries/${reversing.id}/reverse`,
        { memo: `Reversal of ${reversing.entry_no}` },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `Posted ${data.entry_no}`);
      setReversing(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Could not reverse the entry"));
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Journal</h1>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          New entry
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Every balanced event in the shop, newest first. Entries are never edited — a mistake is
        corrected by posting its reversal.
      </p>

      <Toolbar>
        <FilterSelect value={source} onChange={setSource} options={SOURCE_TYPES} allLabel="All sources" />
        <input
          className="input w-auto"
          type="date"
          aria-label="From date"
          value={from}
          onChange={(e) => setFrom(e.target.value)}
        />
        <input
          className="input w-auto"
          type="date"
          aria-label="To date"
          value={to}
          onChange={(e) => setTo(e.target.value)}
        />
        <span className="ml-auto text-xs text-slate-500">{entries.length} entries</span>
      </Toolbar>

      <div className="card mt-4 overflow-x-auto p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && entries.length === 0 && (
          <div className="p-6 text-sm text-slate-500">No entries in the selected range.</div>
        )}
        {entries.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3" />
                <th className="px-4 py-3">Entry</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Memo</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3 text-right">Debit</th>
                <th className="px-4 py-3 text-right">Credit</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {entries.map((e) => (
                <Fragment key={e.id}>
                  <tr className="cursor-pointer hover:bg-slate-50" onClick={() => toggle(e.id)}>
                    <td className="w-8 px-4 py-2.5 text-slate-400">{open.has(e.id) ? "▾" : "▸"}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs">{e.entry_no}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-500">
                      {e.entry_date}
                    </td>
                    <td className="px-4 py-2.5">
                      {e.memo ?? "—"}
                      {e.reverses_entry_id && (
                        <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700">
                          reversal
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500">
                      {e.source_type ?? "—"}
                      {e.source_id ? ` #${e.source_id}` : ""}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right">
                      {fmtMoney(e.total_debit)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right text-red-600">
                      {fmtMoney(e.total_credit)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-right">
                      {!e.reverses_entry_id && (
                        <button
                          className="text-xs text-red-600 hover:underline"
                          onClick={(ev) => {
                            ev.stopPropagation();
                            setReversing(e);
                          }}
                        >
                          Reverse
                        </button>
                      )}
                    </td>
                  </tr>
                  {open.has(e.id) && (
                    <tr className="bg-slate-50/60">
                      <td />
                      <td colSpan={7} className="px-4 py-3">
                        <table className="w-full text-xs">
                          <thead className="text-left uppercase text-slate-500">
                            <tr>
                              <th className="py-1">Account</th>
                              <th className="py-1">Party</th>
                              <th className="py-1">Memo</th>
                              <th className="py-1 text-right">Quantity</th>
                              <th className="py-1 text-right">Rate</th>
                              <th className="py-1 text-right">Value (PKR)</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-200">
                            {e.lines.map((ln) => (
                              <tr key={ln.id}>
                                <td className="py-1.5">
                                  <span className="font-mono text-slate-500">{ln.account_code}</span>{" "}
                                  {ln.account_name}
                                </td>
                                <td className="py-1.5 text-slate-500">
                                  {ln.party_type ? `${ln.party_type} #${ln.party_id}` : "—"}
                                </td>
                                <td className="py-1.5 text-slate-500">{ln.memo ?? "—"}</td>
                                <td
                                  className={`py-1.5 text-right ${
                                    Number(ln.quantity) < 0 ? "text-red-600" : ""
                                  }`}
                                >
                                  {fmtQty(ln.quantity, ln.commodity)}
                                  {ln.native_weight_g && (
                                    <span className="ml-1 text-slate-400">
                                      ({Number(ln.native_weight_g)}g
                                      {ln.native_purity ? `/${ln.native_purity}k` : ""})
                                    </span>
                                  )}
                                </td>
                                <td className="py-1.5 text-right text-slate-500">
                                  {ln.commodity === "PKR" ? "—" : Number(ln.rate).toFixed(2)}
                                </td>
                                <td
                                  className={`py-1.5 text-right ${
                                    Number(ln.value_pkr) < 0 ? "text-red-600" : ""
                                  }`}
                                >
                                  {fmtMoney(ln.value_pkr)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <EntryForm open={creating} onClose={() => setCreating(false)} onPosted={() => { setCreating(false); load(); }} />

      <PasswordConfirm
        open={!!reversing}
        onClose={() => setReversing(null)}
        title={`Reverse ${reversing?.entry_no ?? "entry"}?`}
        description="This posts the mirror image of the entry, leaving both on the record. The original stays exactly as it was — that is what makes the correction explainable."
        confirmLabel="Post reversal"
        onConfirm={confirmReverse}
      />
    </div>
  );
}

interface DraftPosting {
  account_code: string;
  commodity: Commodity;
  /** For GOLD this is the weight as weighed, not fine grams — see nativePurity. */
  quantity: string;
  /** Karat of the weight above. Only meaningful for GOLD; blank means pure. */
  native_purity: string;
  rate: string;
  party_type: PartyType;
  party_id: string;
  memo: string;
}

const emptyPosting = (): DraftPosting => ({
  account_code: "",
  commodity: "PKR",
  quantity: "",
  native_purity: "",
  rate: "",
  party_type: "",
  party_id: "",
  memo: "",
});

/**
 * The PKR value of one posting, in paisa.
 *
 * Integer paisa rather than a float sum: the balance test is an equality, and
 * 0.1 + 0.2 in binary floating point is exactly the kind of thing that would
 * make a correct voucher unpostable. Returns null while the row is unusable,
 * which is also what keeps the entry from being submitted.
 */
function paisa(p: DraftPosting): number | null {
  const qty = Number(p.quantity);
  if (p.quantity.trim() === "" || Number.isNaN(qty)) return null;
  if (p.commodity === "PKR") return Math.round(qty * 100);
  const rate = Number(p.rate);
  if (!(rate > 0)) return null;
  // The rate is per FINE gram, so gold has to be converted before it is valued
  // — exactly as the server does it. Valuing the as-weighed figure here would
  // show a balanced entry that the server then rejects.
  return Math.round(fineGrams(p) * rate * 100);
}

/** As-weighed grams to 24k equivalent. Mirrors `fine_grams` on the server. */
function fineGrams(p: DraftPosting): number {
  const qty = Number(p.quantity);
  if (p.commodity !== "GOLD") return qty;
  const k = Number(p.native_purity);
  return k > 0 && k <= 24 ? (qty * k) / 24 : qty;
}

function EntryForm({
  open,
  onClose,
  onPosted,
}: {
  open: boolean;
  onClose: () => void;
  onPosted: () => void;
}) {
  const [memo, setMemo] = useState("");
  const [entryDate, setEntryDate] = useState("");
  const [rows, setRows] = useState<DraftPosting[]>([emptyPosting(), emptyPosting()]);
  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [customers, setCustomers] = useState<Party[]>([]);
  const [workers, setWorkers] = useState<Party[]>([]);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMemo("");
    setEntryDate("");
    setRows([emptyPosting(), emptyPosting()]);
    api
      .get<AccountOption[]>("/ledger/accounts", { params: { is_active: "true" } })
      .then((res) => setAccounts(res.data.filter((a) => a.is_postable)))
      .catch((e) => toast("error", apiError(e, "Failed to load accounts")));
    api
      .get<Party[]>("/customers", { params: { limit: "500" } })
      .then((res) => setCustomers(res.data))
      .catch(() => setCustomers([]));
    api
      .get<Party[]>("/vendors", { params: { limit: "500" } })
      .then((res) => setWorkers(res.data))
      .catch(() => setWorkers([]));
  }, [open]);

  const set = (i: number, patch: Partial<DraftPosting>) =>
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const values = rows.map(paisa);
  const debit = values.reduce<number>((sum, v) => sum + (v && v > 0 ? v : 0), 0);
  const credit = values.reduce<number>((sum, v) => sum + (v && v < 0 ? -v : 0), 0);
  const difference = debit - credit;
  const incomplete = rows.some((r, i) => !r.account_code || values[i] === null);
  const balanced = !incomplete && rows.length >= 2 && difference === 0;
  const canPost = balanced && memo.trim() !== "";

  const post = async (password: string) => {
    try {
      const body = {
        memo: memo.trim(),
        entry_date: entryDate || null,
        postings: rows.map((r) => ({
          account_code: r.account_code,
          quantity: r.quantity,
          commodity: r.commodity,
          // Sent only for GOLD; the server converts to fine grams from it.
          native_purity:
            r.commodity === "GOLD" && r.native_purity ? Number(r.native_purity) : null,
          rate: r.commodity === "PKR" ? "1" : r.rate,
          party_type: r.party_type || null,
          party_id: r.party_id ? Number(r.party_id) : null,
          memo: r.memo || null,
        })),
      };
      const { data } = await api.post<JournalEntry>("/ledger/entries", body, {
        headers: { "X-Confirm-Password": password },
      });
      toast("success", `Posted ${data.entry_no}`);
      setConfirming(false);
      onPosted();
    } catch (err) {
      toast("error", apiError(err, "Could not post the entry"));
    }
  };

  const partiesFor = (t: PartyType) => (t === "customer" ? customers : t ? workers : []);

  return (
    <>
      <Modal open={open} onClose={onClose} title="New journal entry" widthClass="max-w-5xl">
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <TextField
                label="Memo"
                required
                value={memo}
                onChange={(e) => setMemo(e.target.value)}
                placeholder="What happened, in the shop's words"
              />
            </div>
            <TextField
              label="Entry date"
              type="date"
              hint="Blank posts today"
              value={entryDate}
              onChange={(e) => setEntryDate(e.target.value)}
            />
          </div>

          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-3 py-2">Account</th>
                  <th className="px-3 py-2">Commodity</th>
                  <th className="px-3 py-2 text-right">Quantity</th>
                  <th className="px-3 py-2 text-right">Karat</th>
                  <th className="px-3 py-2 text-right">Rate</th>
                  <th className="px-3 py-2">Party</th>
                  <th className="px-3 py-2 text-right">Value (PKR)</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="px-3 py-2">
                      <select
                        className="input"
                        value={r.account_code}
                        onChange={(e) => set(i, { account_code: e.target.value })}
                      >
                        <option value="">Choose…</option>
                        {accounts.map((a) => (
                          <option key={a.id} value={a.code}>
                            {a.code} — {a.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <select
                        className="input"
                        value={r.commodity}
                        onChange={(e) =>
                          set(i, { commodity: e.target.value as Commodity, rate: "" })
                        }
                      >
                        {COMMODITIES.map((c) => (
                          <option key={c.value} value={c.value}>
                            {c.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <input
                        className="input text-right"
                        type="number"
                        step={r.commodity === "GOLD" ? "0.0001" : "0.01"}
                        placeholder={
                          r.commodity === "GOLD" ? "grams, − to credit" : "− to credit"
                        }
                        value={r.quantity}
                        onChange={(e) => set(i, { quantity: e.target.value })}
                      />
                      {r.commodity === "GOLD" && r.quantity && (
                        <div className="mt-1 text-right text-xs text-slate-500">
                          = {fineGrams(r).toFixed(4)} fine g
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {/* Enter the weight as it came off the scale and the karat
                          stamp; the server converts. Asking for a 24k equivalent
                          is how 22k ends up banked as pure. */}
                      <input
                        className="input text-right"
                        type="number"
                        min="1"
                        max="24"
                        placeholder={r.commodity === "GOLD" ? "24" : "—"}
                        value={r.commodity === "GOLD" ? r.native_purity : ""}
                        disabled={r.commodity !== "GOLD"}
                        onChange={(e) => set(i, { native_purity: e.target.value })}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        className="input text-right"
                        type="number"
                        step="0.0001"
                        placeholder={
                          r.commodity === "PKR"
                            ? "1"
                            : r.commodity === "GOLD"
                              ? "PKR per fine g"
                              : "PKR per unit"
                        }
                        value={r.commodity === "PKR" ? "" : r.rate}
                        disabled={r.commodity === "PKR"}
                        onChange={(e) => set(i, { rate: e.target.value })}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1">
                        <select
                          className="input w-24"
                          value={r.party_type}
                          onChange={(e) =>
                            set(i, { party_type: e.target.value as PartyType, party_id: "" })
                          }
                        >
                          {PARTY_TYPES.map((p) => (
                            <option key={p.value} value={p.value}>
                              {p.label}
                            </option>
                          ))}
                        </select>
                        <select
                          className="input"
                          value={r.party_id}
                          disabled={!r.party_type}
                          onChange={(e) => set(i, { party_id: e.target.value })}
                        >
                          <option value="">—</option>
                          {partiesFor(r.party_type).map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    </td>
                    <td
                      className={`whitespace-nowrap px-3 py-2 text-right ${
                        values[i] === null
                          ? "text-slate-400"
                          : values[i]! < 0
                          ? "text-red-600"
                          : "text-slate-900"
                      }`}
                    >
                      {values[i] === null ? "—" : fmtMoney(values[i]! / 100)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        className="text-xs text-slate-400 hover:text-red-600 disabled:opacity-40"
                        disabled={rows.length <= 2}
                        onClick={() => setRows((prev) => prev.filter((_, idx) => idx !== i))}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setRows((prev) => [...prev, emptyPosting()])}
            >
              Add row
            </button>
            <div
              className={`ml-auto flex items-center gap-4 rounded-lg px-4 py-2 text-sm ring-1 ${
                balanced
                  ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
                  : "bg-amber-50 text-amber-900 ring-amber-200"
              }`}
            >
              <span>
                Debits <span className="font-semibold">{fmtMoney(debit / 100)}</span>
              </span>
              <span>
                Credits <span className="font-semibold">{fmtMoney(credit / 100)}</span>
              </span>
              <span className="font-semibold">
                {balanced
                  ? "Balanced"
                  : incomplete
                  ? "Finish every row"
                  : `Out by ${fmtMoney(difference / 100)}`}
              </span>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={!canPost}
              onClick={() => setConfirming(true)}
            >
              Post entry
            </button>
          </div>
        </div>
      </Modal>

      <PasswordConfirm
        open={open && confirming}
        onClose={() => setConfirming(false)}
        title="Post this entry?"
        description="Posting is final — the journal is append-only, so a mistake is corrected by a reversal that stays on the record."
        confirmLabel="Post entry"
        destructive={false}
        onConfirm={post}
      />
    </>
  );
}

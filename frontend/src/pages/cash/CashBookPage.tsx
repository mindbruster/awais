/**
 * The cash book — the shop's money that no other document explains.
 *
 * Everything else in this system moves cash as a consequence: an invoice bills,
 * a payment settles, a purchase owes. Rent, wages, the electricity bill, a
 * courier, tea, the owner putting a few thousand in the till — none of it had
 * anywhere to go, so the cash figure on the dashboard was only ever the part of
 * the shop's money that happened to pass through a sale.
 *
 * The strip at the top is the *whole* day's money and deliberately does not
 * come from the table beneath it: it reads the ledger, so bills settled and
 * suppliers paid appear alongside the rent. A summary that only counted the
 * rows on this page would answer a question nobody asks. It is also owner
 * information and hidden from staff, who can still record what leaves the till.
 */
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { FilterSelect, Toolbar } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { Currency, fmtMoney } from "@/lib/money";

type Direction = "paid" | "received";
type Method = "cash" | "bank";

interface Category {
  id: number;
  name: string;
  direction: Direction | null;
  account_code: string | null;
  is_active: boolean;
}

interface Entry {
  id: number;
  entry_no: string;
  direction: Direction;
  method: Method;
  category_id: number | null;
  category_name: string | null;
  occurred_on: string;
  amount: string;
  currency: Currency;
  amount_pkr: string;
  bank_account_label: string | null;
  counterparty: string | null;
  reference: string | null;
  notes: string | null;
}

interface FlowHead {
  account_code: string;
  account_name: string;
  money_in: string;
  money_out: string;
}

interface Flow {
  date_from: string;
  date_to: string;
  opening_cash: string;
  opening_bank: string;
  closing_cash: string;
  closing_bank: string;
  money_in: string;
  money_out: string;
  net: string;
  by_head: FlowHead[];
}

interface BankAccount {
  id: number;
  account_no: string;
  title: string | null;
  bank_name?: string | null;
}

const DIRECTIONS = [
  { value: "paid", label: "Money out" },
  { value: "received", label: "Money in" },
];

const METHODS = [
  { value: "cash", label: "Cash" },
  { value: "bank", label: "Bank" },
];

const today = () => new Date().toISOString().slice(0, 10);

export function CashBookPage() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [flow, setFlow] = useState<Flow | null>(null);
  // Staff may record an expense but not read the shop's position, so a 403 on
  // the summary is an expected answer rather than a failure to report.
  const [flowDenied, setFlowDenied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState(today());
  const [to, setTo] = useState(today());
  const [direction, setDirection] = useState("");

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = { date_from: from, date_to: to };
    if (direction) params.direction = direction;
    api
      .get<Entry[]>("/cash/entries", { params })
      .then((r) => setEntries(r.data))
      .catch((e) => setError(apiError(e, "Failed to load the cash book")))
      .finally(() => setLoading(false));
    api
      .get<Flow>("/cash/flow", { params: { date_from: from, date_to: to } })
      .then((r) => {
        setFlow(r.data);
        setFlowDenied(false);
      })
      .catch((e) => {
        setFlow(null);
        setFlowDenied(e?.response?.status === 403);
      });
  };

  useEffect(load, [from, to, direction]);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Cash book</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          Record money
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Rent, wages, a courier, the till float — money in and out that no invoice or purchase
        explains. Every entry posts to the books.
      </p>

      <Toolbar>
        <label className="text-xs text-slate-500">
          From{" "}
          <input
            type="date"
            className="input ml-1 w-auto py-1"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label className="text-xs text-slate-500">
          to{" "}
          <input
            type="date"
            className="input ml-1 w-auto py-1"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
        </label>
        <FilterSelect
          value={direction}
          onChange={setDirection}
          options={DIRECTIONS}
          allLabel="In and out"
        />
        <span className="ml-auto text-xs text-slate-500">{entries.length} entries</span>
      </Toolbar>

      {flow && <FlowStrip flow={flow} />}
      {flowDenied && (
        <p className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-500">
          The day's totals and the shop's closing position are owner information. You can record
          money here, but the summary is not shown.
        </p>
      )}

      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && entries.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            Nothing recorded in this range.
          </div>
        )}
        {entries.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Entry</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Heading</th>
                <th className="px-4 py-3">Who</th>
                <th className="px-4 py-3">Through</th>
                <th className="px-4 py-3 text-right">In</th>
                <th className="px-4 py-3 text-right">Out</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {entries.map((e) => (
                <tr key={e.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">{e.entry_no}</td>
                  <td className="px-4 py-3 text-slate-500">{e.occurred_on}</td>
                  <td className="px-4 py-3 font-medium text-slate-900">
                    {e.category_name ?? "—"}
                    {e.reference && (
                      <span className="block text-xs font-normal text-slate-400">
                        {e.reference}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{e.counterparty ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {e.method === "bank" ? e.bank_account_label ?? "bank" : "cash"}
                  </td>
                  <td className="px-4 py-3 text-right text-emerald-700">
                    {e.direction === "received" ? fmtMoney(e.amount_pkr) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right text-red-600">
                    {e.direction === "paid" ? fmtMoney(e.amount_pkr) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <EntryForm
        open={open}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          load();
        }}
      />
    </div>
  );
}

/**
 * The day's whole money, read off the ledger.
 *
 * Cash and bank are shown apart rather than as one "money" figure: a drawer is
 * counted and a bank account is agreed against a statement, and a total
 * covering both cannot be reconciled against either.
 */
function FlowStrip({ flow }: { flow: Flow }) {
  const opening = Number(flow.opening_cash) + Number(flow.opening_bank);
  const closing = Number(flow.closing_cash) + Number(flow.closing_bank);
  return (
    <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat label="Opened with" value={fmtMoney(opening)} sub={`cash ${fmtMoney(flow.opening_cash)} · bank ${fmtMoney(flow.opening_bank)}`} />
      <Stat label="Money in" value={fmtMoney(flow.money_in)} tone="good" />
      <Stat label="Money out" value={fmtMoney(flow.money_out)} tone="bad" />
      <Stat
        label="Closed with"
        value={fmtMoney(closing)}
        sub={`cash ${fmtMoney(flow.closing_cash)} · bank ${fmtMoney(flow.closing_bank)}`}
      />
      {flow.by_head.length > 0 && (
        <div className="card sm:col-span-2 lg:col-span-4">
          <p className="eyebrow">What moved it</p>
          <div className="mt-2 divide-y divide-slate-100">
            {flow.by_head.map((h) => (
              <div key={h.account_code} className="flex items-baseline justify-between gap-3 py-1.5">
                <span className="text-sm text-slate-700">
                  {h.account_name}
                  <span className="ml-1.5 font-mono text-[11px] text-slate-400">
                    {h.account_code}
                  </span>
                </span>
                <span className="text-right text-sm tabular-nums">
                  {Number(h.money_in) > 0 && (
                    <span className="text-emerald-700">+{fmtMoney(h.money_in)}</span>
                  )}
                  {Number(h.money_in) > 0 && Number(h.money_out) > 0 && (
                    <span className="text-slate-300"> · </span>
                  )}
                  {Number(h.money_out) > 0 && (
                    <span className="text-red-600">−{fmtMoney(h.money_out)}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="card">
      <p className="eyebrow">{label}</p>
      <p
        className={`num mt-1 text-xl font-semibold ${
          tone === "good" ? "text-emerald-700" : tone === "bad" ? "text-red-600" : "text-slate-900"
        }`}
      >
        {value}
      </p>
      {sub && <p className="num mt-0.5 text-[11px] text-slate-500">{sub}</p>}
    </div>
  );
}

function EntryForm({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [banks, setBanks] = useState<BankAccount[]>([]);
  const [direction, setDirection] = useState<Direction>("paid");
  const [method, setMethod] = useState<Method>("cash");
  const [categoryId, setCategoryId] = useState("");
  const [bankId, setBankId] = useState("");
  const [amount, setAmount] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const [occurredOn, setOccurredOn] = useState(today());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  // Adding a heading from here rather than sending the user to a settings
  // screen: the moment you discover there is no heading for "generator diesel"
  // is the moment you are trying to record it.
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [savingCat, setSavingCat] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDirection("paid");
    setMethod("cash");
    setAmount("");
    setCounterparty("");
    setReference("");
    setNotes("");
    setOccurredOn(today());
    setAdding(false);
    setNewName("");
    Promise.all([
      api.get<Category[]>("/cash/categories", { params: { is_active: true } }),
      api.get<BankAccount[]>("/bank-accounts", { params: { limit: 200 } }),
    ])
      .then(([c, b]) => {
        setCategories(c.data);
        setBanks(b.data);
      })
      .catch((e) => toast("error", apiError(e, "Could not load the cash book's headings")));
  }, [open]);

  // A heading declared for one direction cannot be used on the other, and the
  // server refuses it — so the list narrows rather than explaining afterwards.
  const usable = categories.filter((c) => c.direction === null || c.direction === direction);
  useEffect(() => {
    setCategoryId((prev) =>
      usable.some((c) => String(c.id) === prev) ? prev : String(usable[0]?.id ?? ""),
    );
  }, [direction, categories]);

  const addCategory = async () => {
    setSavingCat(true);
    try {
      const r = await api.post<Category>("/cash/categories", {
        name: newName.trim(),
        direction,
      });
      setCategories((prev) => [...prev, r.data]);
      setCategoryId(String(r.data.id));
      setAdding(false);
      setNewName("");
      toast("success", `${r.data.name} added`);
    } catch (err) {
      toast("error", apiError(err, "Could not add that heading"));
    } finally {
      setSavingCat(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/cash/entries", {
        direction,
        method,
        category_id: categoryId ? Number(categoryId) : null,
        occurred_on: occurredOn,
        amount: amount || "0",
        // Required for a bank entry and refused on a cash one, so it is sent
        // exclusively rather than left over from switching the method.
        bank_account_id: method === "bank" && bankId ? Number(bankId) : null,
        counterparty: counterparty || null,
        reference: reference || null,
        notes: notes || null,
      });
      toast("success", direction === "paid" ? "Payment recorded" : "Receipt recorded");
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not record it"));
    } finally {
      setBusy(false);
    }
  };

  const ready = Number(amount || 0) > 0 && (method === "cash" || !!bankId);

  return (
    <Modal open={open} onClose={onClose} title="Record money">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Direction"
            value={direction}
            onChange={(e) => setDirection(e.target.value as Direction)}
            options={DIRECTIONS}
          />
          <SelectField
            label="Through"
            value={method}
            onChange={(e) => {
              setMethod(e.target.value as Method);
              setBankId("");
            }}
            options={METHODS}
          />
        </div>

        {method === "bank" && (
          <SelectField
            label="Bank account"
            required
            value={bankId}
            onChange={(e) => setBankId(e.target.value)}
            options={[
              { value: "", label: "Select an account…" },
              ...banks.map((b) => ({
                value: b.id,
                label: `${b.bank_name ? `${b.bank_name} · ` : ""}${b.account_no}${
                  b.title ? ` — ${b.title}` : ""
                }`,
              })),
            ]}
            hint={
              banks.length === 0
                ? "No bank accounts on file — add one under Settings → Banks."
                : "Which statement this will be reconciled against"
            }
          />
        )}

        <div>
          <SelectField
            label="Heading"
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            options={[
              { value: "", label: direction === "paid" ? "Other expenses" : "Other income" },
              ...usable.map((c) => ({ value: c.id, label: c.name })),
            ]}
            hint="Where it lands in the books"
          />
          {adding ? (
            <div className="mt-2 space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
              <TextField
                label="New heading"
                required
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder={direction === "paid" ? "Generator diesel" : "Scrap sold"}
                hint={`Filed under money ${direction === "paid" ? "out" : "in"}`}
              />
              <div className="flex justify-end gap-2">
                <button type="button" className="btn-ghost" onClick={() => setAdding(false)}>
                  Cancel
                </button>
                {/* Not a submit: this form's submit records the money, and an
                    Enter keypress while adding a heading would post the entry. */}
                <button
                  type="button"
                  className="btn-primary"
                  onClick={addCategory}
                  disabled={savingCat || !newName.trim()}
                >
                  {savingCat ? "Adding…" : "Add heading"}
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              className="mt-1 text-xs font-medium text-brand-700 underline underline-offset-2"
              onClick={() => setAdding(true)}
            >
              Not listed? Add a heading
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Amount"
            type="number"
            step="0.01"
            min={0.01}
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
          <TextField
            label="Date"
            type="date"
            value={occurredOn}
            onChange={(e) => setOccurredOn(e.target.value)}
            hint="The day the money moved"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <TextField
            label={direction === "paid" ? "Paid to" : "Received from"}
            value={counterparty}
            onChange={(e) => setCounterparty(e.target.value)}
            placeholder={direction === "paid" ? "Landlord" : "Owner"}
          />
          <TextField
            label="Reference"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="Receipt no."
          />
        </div>

        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy || !ready}>
            {busy ? "Recording…" : direction === "paid" ? "Record payment" : "Record receipt"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { SelectField, TextField } from "@/components/Field";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

/**
 * A trade party's account, in metal and money at once.
 *
 * The ordinary Statement screen shows one account in one commodity. That is
 * the right tool for "what is in Cash in Hand", and the wrong one for "where
 * do I stand with Muzammil Bhai" — because the answer to that is two numbers
 * in two different units, and reading them off two separate screens is how a
 * settlement conversation goes wrong.
 *
 * The two columns are never netted. Converting the metal side to rupees to
 * show one figure would price gold the party has not agreed to sell yet; the
 * whole point of settling in metal is that the rate is fixed on the day the
 * metal moves, not on the day the bill was written.
 */

type PartyType = "customer" | "worker" | "supplier" | "salesman";

interface Party {
  id: number;
  name: string;
}

interface Row {
  entry_id: number;
  entry_no: string;
  entry_date: string;
  memo: string | null;
  source_type: string | null;
  source_id: number | null;
  metal_in_g: string;
  metal_out_g: string;
  metal_balance_g: string;
  native_weight_g: string | null;
  native_purity: number | null;
  native_tunch_pct: string | null;
  cash_debit: string;
  cash_credit: string;
  cash_balance: string;
}

interface Report {
  party_type: PartyType;
  party_id: number;
  party_name: string | null;
  date_from: string | null;
  date_to: string | null;
  opening_metal_g: string;
  opening_cash: string;
  rows: Row[];
  metal_in_total_g: string;
  metal_out_total_g: string;
  cash_debit_total: string;
  cash_credit_total: string;
  closing_metal_g: string;
  closing_cash: string;
  total_rows: number;
  truncated: boolean;
}

const PARTY_TYPES = [
  { value: "customer", label: "Jeweller / customer" },
  { value: "supplier", label: "Supplier" },
  { value: "worker", label: "Worker" },
  { value: "salesman", label: "Salesman" },
];

// What the document was, in the shop's words rather than the table's.
const SOURCE_LABELS: Record<string, string> = {
  invoice: "Sale",
  payment: "Payment",
  old_gold_purchase: "Old gold bought",
  gold_purchase: "Gold bought",
  stone_purchase: "Stones bought",
  job_leg: "Job",
  design_stock: "Stocked",
  opening_balance: "Opening",
  manual: "Journal",
};

const zero = (v: string | null | undefined) => !v || Number(v) === 0;

function grams(v: string | null | undefined): string {
  if (zero(v)) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${n.toLocaleString(undefined, {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  })} g`;
}

function money(v: string | null | undefined): string {
  if (zero(v)) return "—";
  return fmtMoney(v, "PKR");
}

/**
 * Which way a balance points, said in words.
 *
 * A signed number is unambiguous to an accountant and ambiguous to everyone
 * else, and this screen gets read across a counter during an argument about
 * money. "He owes you" and "you are holding his" are the two things anybody
 * actually wants to know.
 */
function direction(value: string, unit: "metal" | "cash"): { text: string; tone: string } {
  const n = Number(value);
  if (!n) return { text: "Square", tone: "text-slate-500" };
  if (n > 0) return { text: "Owed to you", tone: "text-emerald-700" };
  return {
    text: unit === "metal" ? "You are holding theirs" : "You owe them",
    tone: "text-amber-700",
  };
}

export function TradeAccountPage() {
  const [partyType, setPartyType] = useState<PartyType>("customer");
  const [partyId, setPartyId] = useState("");
  const [parties, setParties] = useState<Party[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const [data, setData] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Customers have their own master; every other outside party lives in the
  // vendor list, which is also where salesmen sit until the route work gives
  // them somewhere better.
  useEffect(() => {
    setPartyId("");
    const url = partyType === "customer" ? "/customers" : "/vendors";
    api
      .get<Party[]>(url, { params: { limit: "500" } })
      .then((res) => setParties(res.data))
      .catch(() => setParties([]));
  }, [partyType]);

  useEffect(() => {
    if (!partyId) {
      setData(null);
      return;
    }
    const params: Record<string, string> = { party_type: partyType, party_id: partyId };
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    setLoading(true);
    setError(null);
    api
      .get<Report>("/ledger/party-statement", { params })
      .then((res) => setData(res.data))
      .catch((e) => {
        setData(null);
        setError(apiError(e, "Failed to load the trade account"));
      })
      .finally(() => setLoading(false));
  }, [partyType, partyId, from, to]);

  const metalDir = data ? direction(data.closing_metal_g, "metal") : null;
  const cashDir = data ? direction(data.closing_cash, "cash") : null;

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Trade account</h1>
      <p className="mt-1 text-sm text-slate-500">
        Everything you have ever traded with one party, and where you stand with them — in fine
        gold and in rupees, side by side. The two settle separately and are never netted against
        each other.
      </p>

      <div className="card mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <SelectField
          label="Kind of party"
          options={PARTY_TYPES}
          value={partyType}
          onChange={(e) => setPartyType(e.target.value as PartyType)}
        />
        <SelectField
          label="Party"
          options={[
            { value: "", label: "Choose…" },
            ...parties.map((p) => ({ value: p.id, label: p.name })),
          ]}
          value={partyId}
          onChange={(e) => setPartyId(e.target.value)}
        />
        <TextField label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <TextField label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>

      {error && <div className="card mt-4 text-sm text-red-600">{error}</div>}
      {!partyId && !error && (
        <div className="card mt-4 text-sm text-slate-500">
          Pick a party to see their account.
        </div>
      )}
      {loading && <div className="card mt-4 text-sm text-slate-500">Loading…</div>}

      {data && !loading && (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="card border-l-4 border-amber-400">
              <div className="text-xs uppercase tracking-wide text-slate-500">Gold position</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">
                {grams(data.closing_metal_g) === "—" ? "0.000 g" : grams(data.closing_metal_g)}
              </div>
              <div className={`mt-1 text-sm font-medium ${metalDir?.tone}`}>{metalDir?.text}</div>
              <div className="mt-2 text-xs text-slate-500">
                Fine (24k-equivalent) grams. Unpriced on purpose — the rate is agreed when the
                metal moves.
              </div>
            </div>
            <div className="card border-l-4 border-sky-500">
              <div className="text-xs uppercase tracking-wide text-slate-500">Cash position</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">
                {money(data.closing_cash) === "—" ? fmtMoney("0", "PKR") : money(data.closing_cash)}
              </div>
              <div className={`mt-1 text-sm font-medium ${cashDir?.tone}`}>{cashDir?.text}</div>
              <div className="mt-2 text-xs text-slate-500">
                Making, stones and anything billed in money. Dollar bills are counted at the rate
                they were struck at.
              </div>
            </div>
          </div>

          <div className="card mt-4 overflow-x-auto p-0">
            <div className="border-b border-slate-200 px-4 py-3 text-sm">
              <span className="font-medium text-slate-900">
                {data.party_name ?? `Party #${data.party_id}`}
              </span>
              <span className="ml-2 text-slate-500">
                {data.total_rows} document{data.total_rows === 1 ? "" : "s"}
                {data.date_from || data.date_to
                  ? ` · ${data.date_from ?? "start"} to ${data.date_to ?? "today"}`
                  : " · full history"}
              </span>
            </div>

            {data.rows.length === 0 ? (
              <div className="p-6 text-sm text-slate-500">
                Nothing has been traded with this party in the selected range.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Date</th>
                    <th className="px-4 py-3">Document</th>
                    <th className="px-4 py-3">Particulars</th>
                    <th className="bg-amber-50 px-3 py-3 text-right text-amber-800">Gold in</th>
                    <th className="bg-amber-50 px-3 py-3 text-right text-amber-800">Gold out</th>
                    <th className="bg-amber-50 px-3 py-3 text-right text-amber-800">Gold bal.</th>
                    <th className="bg-sky-50 px-3 py-3 text-right text-sky-800">Cash Dr</th>
                    <th className="bg-sky-50 px-3 py-3 text-right text-sky-800">Cash Cr</th>
                    <th className="bg-sky-50 px-3 py-3 text-right text-sky-800">Cash bal.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  <tr className="bg-slate-50/60 text-xs text-slate-500">
                    <td className="px-4 py-2" colSpan={3}>
                      Opening
                    </td>
                    <td className="bg-amber-50/50 px-3 py-2" colSpan={2} />
                    <td className="bg-amber-50/50 px-3 py-2 text-right font-medium tabular-nums">
                      {grams(data.opening_metal_g)}
                    </td>
                    <td className="bg-sky-50/50 px-3 py-2" colSpan={2} />
                    <td className="bg-sky-50/50 px-3 py-2 text-right font-medium tabular-nums">
                      {money(data.opening_cash)}
                    </td>
                  </tr>
                  {data.rows.map((r) => (
                    <tr key={r.entry_id} className="hover:bg-slate-50">
                      <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-500">
                        {r.entry_date}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5">
                        <span className="font-mono text-xs">{r.entry_no}</span>
                        {r.source_type && (
                          <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                            {SOURCE_LABELS[r.source_type] ?? r.source_type}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        {r.memo ?? "—"}
                        {/* What the scale actually read, when the document said.
                            Tunch is shown in preference to karat: it is what the
                            two sides agreed the metal was. */}
                        {!zero(r.native_weight_g) && (
                          <span className="ml-2 text-xs text-slate-500">
                            ({Math.abs(Number(r.native_weight_g))} g
                            {r.native_tunch_pct
                              ? ` @ ${Number(r.native_tunch_pct)} tunch`
                              : r.native_purity
                                ? ` @ ${r.native_purity}k`
                                : ""}
                            )
                          </span>
                        )}
                      </td>
                      <td className="bg-amber-50/40 px-3 py-2.5 text-right tabular-nums">
                        {grams(r.metal_in_g)}
                      </td>
                      <td className="bg-amber-50/40 px-3 py-2.5 text-right tabular-nums text-amber-700">
                        {grams(r.metal_out_g)}
                      </td>
                      <td className="bg-amber-50/40 px-3 py-2.5 text-right font-medium tabular-nums">
                        {grams(r.metal_balance_g) === "—" ? "0.000 g" : grams(r.metal_balance_g)}
                      </td>
                      <td className="bg-sky-50/40 px-3 py-2.5 text-right tabular-nums">
                        {money(r.cash_debit)}
                      </td>
                      <td className="bg-sky-50/40 px-3 py-2.5 text-right tabular-nums text-sky-700">
                        {money(r.cash_credit)}
                      </td>
                      <td className="bg-sky-50/40 px-3 py-2.5 text-right font-medium tabular-nums">
                        {money(r.cash_balance) === "—" ? fmtMoney("0", "PKR") : money(r.cash_balance)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="border-t-2 border-slate-200 bg-slate-50 text-sm">
                  <tr>
                    <td className="px-4 py-3 font-medium" colSpan={3}>
                      Totals
                    </td>
                    <td className="bg-amber-100/60 px-3 py-3 text-right font-medium tabular-nums">
                      {grams(data.metal_in_total_g)}
                    </td>
                    <td className="bg-amber-100/60 px-3 py-3 text-right font-medium tabular-nums">
                      {grams(data.metal_out_total_g)}
                    </td>
                    <td className="bg-amber-100/60 px-3 py-3 text-right font-semibold tabular-nums">
                      {grams(data.closing_metal_g) === "—" ? "0.000 g" : grams(data.closing_metal_g)}
                    </td>
                    <td className="bg-sky-100/60 px-3 py-3 text-right font-medium tabular-nums">
                      {money(data.cash_debit_total)}
                    </td>
                    <td className="bg-sky-100/60 px-3 py-3 text-right font-medium tabular-nums">
                      {money(data.cash_credit_total)}
                    </td>
                    <td className="bg-sky-100/60 px-3 py-3 text-right font-semibold tabular-nums">
                      {money(data.closing_cash) === "—"
                        ? fmtMoney("0", "PKR")
                        : money(data.closing_cash)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            )}
            {data.truncated && (
              <div className="border-t border-slate-200 px-4 py-3 text-xs text-slate-500">
                Showing the first {data.rows.length} of {data.total_rows} documents. The totals
                above cover the whole period.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

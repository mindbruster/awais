import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { SelectField, TextField } from "@/components/Field";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

type Commodity = "PKR" | "USD" | "GOLD";

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

interface StatementRow {
  line_id: number;
  entry_id: number;
  entry_no: string;
  entry_date: string;
  memo: string | null;
  counter_accounts: string[];
  debit: string;
  credit: string;
  running_balance: string;
  native_weight_g: string | null;
  native_purity: number | null;
}

interface Statement {
  account_id: number;
  account_code: string;
  account_name: string;
  commodity: Commodity;
  party_type: string | null;
  party_id: number | null;
  date_from: string | null;
  date_to: string | null;
  opening_balance: string;
  rows: StatementRow[];
  period_debit: string;
  period_credit: string;
  closing_balance: string;
}

const COMMODITIES = [
  { value: "PKR", label: "Rupees (PKR)" },
  { value: "USD", label: "Dollars (USD)" },
  { value: "GOLD", label: "Gold (fine grams)" },
];

const PARTY_TYPES = [
  { value: "", label: "Whole account" },
  { value: "customer", label: "Customer" },
  { value: "worker", label: "Worker" },
  { value: "supplier", label: "Supplier" },
];

/** Gold is a balance in grams, not money — the same column means both here. */
function fmtAmount(value: string | null | undefined, commodity: Commodity): string {
  if (value === null || value === undefined || value === "") return "—";
  if (commodity !== "GOLD") return fmtMoney(value, commodity);
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return `${n.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 })} g`;
}

const zero = (v: string) => Number(v) === 0;

export function StatementPage() {
  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [accountId, setAccountId] = useState("");
  const [commodity, setCommodity] = useState<Commodity>("PKR");
  const [partyType, setPartyType] = useState("");
  const [partyId, setPartyId] = useState("");
  const [parties, setParties] = useState<Party[]>([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const [data, setData] = useState<Statement | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AccountOption[]>("/ledger/accounts", { params: { is_active: "true" } })
      .then((res) => setAccounts(res.data.filter((a) => a.is_postable)))
      .catch((e) => setError(apiError(e, "Failed to load accounts")));
  }, []);

  // The shop has no supplier master of its own — outside parties, whether they
  // work metal or sell it, live in the vendor list.
  useEffect(() => {
    setPartyId("");
    if (!partyType) {
      setParties([]);
      return;
    }
    const url = partyType === "customer" ? "/customers" : "/vendors";
    api
      .get<Party[]>(url, { params: { limit: "500" } })
      .then((res) => setParties(res.data))
      .catch(() => setParties([]));
  }, [partyType]);

  useEffect(() => {
    if (!accountId) {
      setData(null);
      return;
    }
    const params: Record<string, string> = { account_id: accountId, commodity };
    if (partyType) params.party_type = partyType;
    if (partyId) params.party_id = partyId;
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    setLoading(true);
    setError(null);
    api
      .get<Statement>("/ledger/statement", { params })
      .then((res) => setData(res.data))
      .catch((e) => {
        setData(null);
        setError(apiError(e, "Failed to load the statement"));
      })
      .finally(() => setLoading(false));
  }, [accountId, commodity, partyType, partyId, from, to]);

  const partyName = parties.find((p) => String(p.id) === partyId)?.name;

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Statement</h1>
      <p className="mt-1 text-sm text-slate-500">
        One account, in one commodity, running from an opening balance. Narrow it to a single
        customer or worker to get their own ledger out of the control account.
      </p>

      <div className="card mt-4 grid gap-3 md:grid-cols-3 lg:grid-cols-6">
        <div className="md:col-span-2">
          <SelectField
            label="Account"
            options={[
              { value: "", label: "Choose an account…" },
              ...accounts.map((a) => ({ value: a.id, label: `${a.code} — ${a.name}` })),
            ]}
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
          />
        </div>
        <SelectField
          label="Commodity"
          options={COMMODITIES}
          value={commodity}
          onChange={(e) => setCommodity(e.target.value as Commodity)}
        />
        <SelectField
          label="Scope"
          options={PARTY_TYPES}
          value={partyType}
          onChange={(e) => setPartyType(e.target.value)}
        />
        <SelectField
          label="Party"
          options={[
            { value: "", label: partyType ? "All" : "—" },
            ...parties.map((p) => ({ value: p.id, label: p.name })),
          ]}
          value={partyId}
          onChange={(e) => setPartyId(e.target.value)}
          disabled={!partyType}
        />
        <div className="grid grid-cols-2 gap-2">
          <TextField label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <TextField label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>

      {error && <div className="card mt-4 text-sm text-red-600">{error}</div>}
      {!accountId && !error && (
        <div className="card mt-4 text-sm text-slate-500">
          Pick an account to see its statement.
        </div>
      )}
      {loading && <div className="card mt-4 text-sm text-slate-500">Loading…</div>}

      {data && !loading && (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <Tile label="Opening balance" value={fmtAmount(data.opening_balance, data.commodity)} />
            <Tile label="Period debit" value={fmtAmount(data.period_debit, data.commodity)} />
            <Tile label="Period credit" value={fmtAmount(data.period_credit, data.commodity)} />
            <Tile
              label="Closing balance"
              value={fmtAmount(data.closing_balance, data.commodity)}
              accent
            />
          </div>

          <div className="card mt-4 overflow-x-auto p-0">
            <div className="border-b border-slate-200 px-4 py-3 text-sm">
              <span className="font-medium text-slate-900">
                {data.account_code} — {data.account_name}
              </span>
              <span className="ml-2 text-slate-500">
                {data.commodity}
                {partyName ? ` · ${partyName}` : ""}
                {data.date_from || data.date_to
                  ? ` · ${data.date_from ?? "start"} to ${data.date_to ?? "today"}`
                  : ""}
              </span>
            </div>
            {data.rows.length === 0 ? (
              <div className="p-6 text-sm text-slate-500">
                No {data.commodity} postings on this account in the selected range.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Date</th>
                    <th className="px-4 py-3">Entry</th>
                    <th className="px-4 py-3">Particulars</th>
                    <th className="px-4 py-3">Against</th>
                    <th className="px-4 py-3 text-right">Debit</th>
                    <th className="px-4 py-3 text-right">Credit</th>
                    <th className="px-4 py-3 text-right">Balance</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  <tr className="bg-slate-50/60">
                    <td className="px-4 py-2 text-xs text-slate-500" colSpan={6}>
                      Opening balance
                    </td>
                    <td className="px-4 py-2 text-right font-medium">
                      {fmtAmount(data.opening_balance, data.commodity)}
                    </td>
                  </tr>
                  {data.rows.map((r) => (
                    <tr key={r.line_id} className="hover:bg-slate-50">
                      <td className="whitespace-nowrap px-4 py-2.5 text-xs text-slate-500">
                        {r.entry_date}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs">
                        {r.entry_no}
                      </td>
                      <td className="px-4 py-2.5">
                        {r.memo ?? "—"}
                        {r.native_weight_g && (
                          <span className="ml-2 text-xs text-slate-500">
                            ({Number(r.native_weight_g)} g
                            {r.native_purity ? ` @ ${r.native_purity}k` : ""})
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-slate-500">
                        {r.counter_accounts.join(", ") || "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {zero(r.debit) ? "—" : fmtAmount(r.debit, data.commodity)}
                      </td>
                      <td className="px-4 py-2.5 text-right text-red-600">
                        {zero(r.credit) ? "—" : fmtAmount(r.credit, data.commodity)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-medium">
                        {fmtAmount(r.running_balance, data.commodity)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="border-t-2 border-slate-200 bg-slate-50 text-sm">
                  <tr>
                    <td className="px-4 py-3 font-medium" colSpan={4}>
                      Period totals
                    </td>
                    <td className="px-4 py-3 text-right font-medium">
                      {fmtAmount(data.period_debit, data.commodity)}
                    </td>
                    <td className="px-4 py-3 text-right font-medium text-red-600">
                      {fmtAmount(data.period_credit, data.commodity)}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold">
                      {fmtAmount(data.closing_balance, data.commodity)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`card ${accent ? "bg-brand-50 ring-1 ring-brand-200" : ""}`}>
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

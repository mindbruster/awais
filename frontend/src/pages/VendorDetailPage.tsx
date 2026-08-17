/**
 * One worker's whole position.
 *
 * The question this page exists for is the one argued at the counter: "what
 * does Zahid owe me, and what am I holding of his". Until now it could only be
 * answered by reading the ledger by hand.
 *
 * Four balances, never netted into one. He can be holding the shop's gold,
 * holding its silver, short of stones, and owed money for his labour, all at
 * the same time — and none of those settles another. A single "balance" figure
 * would have to price metal he has not agreed to sell and carats nobody has
 * valued, and would then be argued with.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Vendor {
  id: number;
  name: string;
  type: string;
  department_name: string | null;
  phone: string | null;
  cnic: string | null;
  address: string | null;
  default_wastage_pct: string | null;
  effective_wastage_pct: string | null;
  is_active: boolean;
  notes: string | null;
}

interface StatementRow {
  entry_id: number;
  entry_no: string;
  entry_date: string;
  memo: string | null;
  source_type: string | null;
  metal_in_g: string;
  metal_out_g: string;
  metal_balance_g: string;
  cash_debit: string;
  cash_credit: string;
  cash_balance: string;
  silver_delta_g: string;
  stone_delta_ct: string;
}

interface Statement {
  party_name: string | null;
  closing_metal_g: string;
  closing_cash: string;
  closing_silver_g: string;
  closing_stone_ct: string;
  rows: StatementRow[];
  total_rows: number;
  truncated: boolean;
}

interface Design {
  id: number;
  design_no: string;
  item_name: string | null;
  status: string;
  current_department_name: string | null;
}

const wt = (v: string, unit: string) =>
  `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${unit}`;

export function VendorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const vendorId = Number(id);
  const [vendor, setVendor] = useState<Vendor | null>(null);
  const [account, setAccount] = useState<Statement | null>(null);
  const [holding, setHolding] = useState<Design[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Balances are owner information; a counter user can still open the worker's
  // details. A 403 on the account is an expected answer, not a failure.
  const [accountDenied, setAccountDenied] = useState(false);

  const load = useCallback(async () => {
    try {
      const v = await api.get<Vendor>(`/vendors/${vendorId}`);
      setVendor(v.data);
    } catch (e) {
      setError(apiError(e, "Could not load this worker"));
      return;
    }
    try {
      const a = await api.get<Statement>("/ledger/party-statement", {
        params: { party_type: "worker", party_id: vendorId },
      });
      setAccount(a.data);
    } catch (e) {
      setAccountDenied((e as { response?: { status?: number } })?.response?.status === 403);
    }
    try {
      const d = await api.get<Design[]>("/designs", {
        params: { worker_id: vendorId, held_by_worker: true },
      });
      setHolding(d.data);
    } catch {
      setHolding([]);
    }
  }, [vendorId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!vendor) return <div className="text-sm text-slate-500">Loading…</div>;

  return (
    <div className="space-y-5">
      <div>
        <Link to="/vendors" className="text-xs text-slate-500 hover:underline">
          ← Workers
        </Link>
        <div className="mt-2 flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">{vendor.name}</h1>
          <span className="chip-idle">{vendor.department_name ?? "no department"}</span>
          {!vendor.is_active && <span className="chip-dead">inactive</span>}
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {vendor.phone ?? "no phone"}
          {vendor.effective_wastage_pct !== null && (
            <> · {Number(vendor.effective_wastage_pct)}% wastage allowed</>
          )}
        </p>
      </div>

      {accountDenied ? (
        <div className="card text-xs leading-relaxed text-slate-500">
          What this worker holds and is owed are money figures, and are not shown at your
          access level.
        </div>
      ) : (
        account && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Balance
              label="Gold with him"
              value={wt(account.closing_metal_g, "g fine")}
              hint="positive means he is holding the shop's metal"
              tone={Number(account.closing_metal_g) > 0 ? "out" : undefined}
            />
            <Balance
              label="Silver with him"
              value={wt(account.closing_silver_g, "g fine")}
              hint="counted apart from gold — a gram of one never settles the other"
              tone={Number(account.closing_silver_g) > 0 ? "out" : undefined}
            />
            <Balance
              label="Stones owed"
              value={wt(account.closing_stone_ct, "ct")}
              hint="carats he could not produce — settled in stones, not cash"
              tone={Number(account.closing_stone_ct) > 0 ? "bad" : undefined}
            />
            <Balance
              label={Number(account.closing_cash) < 0 ? "Owed to him" : "Owed by him"}
              value={fmtMoney(Math.abs(Number(account.closing_cash)))}
              hint="labour earned, less what has been paid"
              tone={Number(account.closing_cash) < 0 ? "owe" : undefined}
            />
          </div>
        )
      )}

      <div className="card p-0">
        <div className="border-b border-slate-100 px-5 py-3">
          <p className="eyebrow">In his hands right now</p>
        </div>
        {holding.length === 0 ? (
          <p className="px-5 py-6 text-sm text-slate-500">
            Nothing is out with him.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {holding.map((d) => (
              <li key={d.id} className="flex items-baseline justify-between gap-3 px-5 py-2.5">
                <Link
                  to={`/designs/${d.id}`}
                  className="num font-medium text-brand-700 hover:underline"
                >
                  {d.design_no}
                </Link>
                <span className="text-sm text-slate-500">{d.item_name ?? "—"}</span>
                <span className="ml-auto text-xs text-slate-400">
                  {d.current_department_name ?? "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {account && account.rows.length > 0 && (
        <div className="card p-0">
          <div className="border-b border-slate-100 px-5 py-3">
            <p className="eyebrow">Account</p>
            {account.truncated && (
              <p className="mt-0.5 text-[11px] text-slate-500">
                Showing the first {account.rows.length} of {account.total_rows} entries.
              </p>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-sm tabular-nums">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-5 py-2">Date</th>
                  <th className="px-5 py-2">Entry</th>
                  <th className="px-5 py-2">What</th>
                  <th className="px-5 py-2 text-right">Gold</th>
                  <th className="px-5 py-2 text-right">Silver</th>
                  <th className="px-5 py-2 text-right">Stones</th>
                  <th className="px-5 py-2 text-right">Cash</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {account.rows.map((r) => {
                  const metal = Number(r.metal_in_g) - Number(r.metal_out_g);
                  const cash = Number(r.cash_debit) - Number(r.cash_credit);
                  return (
                    <tr key={r.entry_id}>
                      <td className="px-5 py-2.5 text-slate-500">{r.entry_date}</td>
                      <td className="px-5 py-2.5 font-mono text-xs text-slate-500">
                        {r.entry_no}
                      </td>
                      <td className="px-5 py-2.5 text-slate-700">{r.memo ?? r.source_type}</td>
                      <td className="px-5 py-2.5 text-right">{signed(metal, "g")}</td>
                      <td className="px-5 py-2.5 text-right">
                        {signed(Number(r.silver_delta_g), "g")}
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        {signed(Number(r.stone_delta_ct), "ct")}
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        {cash ? fmtMoney(cash) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function signed(n: number, unit: string) {
  if (!n) return <span className="text-slate-300">—</span>;
  return (
    <span className={n > 0 ? "text-amber-700" : "text-emerald-700"}>
      {n > 0 ? "+" : "−"}
      {Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 4 })} {unit}
    </span>
  );
}

function Balance({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone?: "out" | "bad" | "owe";
}) {
  const colour =
    tone === "bad"
      ? "text-red-600"
      : tone === "out"
      ? "text-amber-700"
      : tone === "owe"
      ? "text-sky-700"
      : "text-slate-900";
  return (
    <div className="card">
      <p className="eyebrow">{label}</p>
      <p className={`num mt-1 text-xl font-semibold ${colour}`}>{value}</p>
      <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{hint}</p>
    </div>
  );
}

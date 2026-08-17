/**
 * One supplier's whole position: what was bought from them, and what is owed.
 *
 * Deliberately the same shape as the worker page, and deliberately a different
 * set of balances. A worker is *given* the shop's material and owes it back as
 * pieces; a supplier *sells* the shop material and is owed money for it. The
 * two are both "parties" and their accounts settle in different units, which is
 * why they were never merged into one screen.
 *
 * The metal column is here because a bullion dealer can be owed grams rather
 * than rupees — a bill settled in metal on the day the metal moves, which is
 * how the bazaar trades and why the ledger keeps a party metal account at all.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Supplier {
  id: number;
  name: string;
  phone: string | null;
  address: string | null;
  opening_balance: string;
  is_active: boolean;
  notes: string | null;
}

interface Statement {
  closing_metal_g: string;
  closing_cash: string;
  closing_silver_g: string;
  closing_stone_ct: string;
  rows: {
    entry_id: number;
    entry_no: string;
    entry_date: string;
    memo: string | null;
    source_type: string | null;
    metal_in_g: string;
    metal_out_g: string;
    cash_debit: string;
    cash_credit: string;
    cash_balance: string;
  }[];
  total_rows: number;
  truncated: boolean;
}

interface Purchase {
  id: number;
  purchase_no: string;
  purchased_at: string;
  total: string;
  reference?: string | null;
  payment_mode?: string | null;
}

const wt = (v: string, unit: string) =>
  `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${unit}`;

export function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const supplierId = Number(id);
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [account, setAccount] = useState<Statement | null>(null);
  const [gold, setGold] = useState<Purchase[]>([]);
  const [stones, setStones] = useState<Purchase[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [accountDenied, setAccountDenied] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await api.get<Supplier>(`/purchasing/suppliers/${supplierId}`);
      setSupplier(s.data);
    } catch (e) {
      setError(apiError(e, "Could not load this supplier"));
      return;
    }
    try {
      const a = await api.get<Statement>("/ledger/party-statement", {
        params: { party_type: "supplier", party_id: supplierId },
      });
      setAccount(a.data);
    } catch (e) {
      setAccountDenied((e as { response?: { status?: number } })?.response?.status === 403);
    }
    // Both purchase kinds, because a dealer who sells bullion often sells
    // stones too and a page that showed only one would look like half the
    // relationship.
    for (const [path, set] of [
      ["/purchasing/gold-purchases", setGold],
      ["/purchasing/stone-purchases", setStones],
    ] as const) {
      try {
        const r = await api.get<Purchase[]>(path, {
          params: { supplier_id: supplierId, limit: 100 },
        });
        set(r.data);
      } catch {
        set([]);
      }
    }
  }, [supplierId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!supplier) return <div className="text-sm text-slate-500">Loading…</div>;

  const owed = account ? -Number(account.closing_cash) : 0;

  return (
    <div className="space-y-5">
      <div>
        <Link to="/purchasing/suppliers" className="text-xs text-slate-500 hover:underline">
          ← Suppliers
        </Link>
        <div className="mt-2 flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">{supplier.name}</h1>
          {!supplier.is_active && <span className="chip-dead">inactive</span>}
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {supplier.phone ?? "no phone"}
          {supplier.address && <> · {supplier.address}</>}
        </p>
      </div>

      {accountDenied ? (
        <div className="card text-xs leading-relaxed text-slate-500">
          What is owed to this supplier is a money figure and is not shown at your access
          level.
        </div>
      ) : (
        account && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Balance
              label={owed >= 0 ? "Owed to them" : "They owe the shop"}
              value={fmtMoney(Math.abs(owed))}
              hint="what is on the books, less what has been paid"
              tone={owed > 0 ? "owe" : undefined}
            />
            <Balance
              label="Metal on account"
              value={wt(account.closing_metal_g, "g fine")}
              hint="a bill settled in metal is settled on the day the metal moves"
            />
            <Balance
              label="Bullion bills"
              value={String(gold.length)}
              hint="gold purchases raised against them"
            />
            <Balance
              label="Stone bills"
              value={String(stones.length)}
              hint="stone purchases raised against them"
            />
          </div>
        )
      )}

      <PurchaseList title="Bullion purchases" rows={gold} />
      <PurchaseList title="Stone purchases" rows={stones} />

      {account && account.rows.length > 0 && (
        <div className="card p-0">
          <div className="border-b border-slate-100 px-5 py-3">
            <p className="eyebrow">Every movement with them</p>
            {account.truncated && (
              <p className="mt-0.5 text-[11px] text-slate-500">
                Showing the first {account.rows.length} of {account.total_rows}.
              </p>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[42rem] text-sm tabular-nums">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-5 py-2">Date</th>
                  <th className="px-5 py-2">Entry</th>
                  <th className="px-5 py-2">What</th>
                  <th className="px-5 py-2 text-right">Metal</th>
                  <th className="px-5 py-2 text-right">Cash</th>
                  <th className="px-5 py-2 text-right">Balance</th>
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
                      <td className="px-5 py-2.5 text-right">
                        {metal
                          ? `${metal > 0 ? "+" : "−"}${Math.abs(metal).toFixed(4)} g`
                          : "—"}
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        {cash ? fmtMoney(cash) : "—"}
                      </td>
                      <td className="px-5 py-2.5 text-right text-slate-500">
                        {fmtMoney(r.cash_balance)}
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

function PurchaseList({ title, rows }: { title: string; rows: Purchase[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="card p-0">
      <div className="border-b border-slate-100 px-5 py-3">
        <p className="eyebrow">{title}</p>
      </div>
      <ul className="divide-y divide-slate-100">
        {rows.map((p) => (
          <li key={p.id} className="flex flex-wrap items-baseline gap-3 px-5 py-2.5">
            <span className="num font-medium text-slate-800">{p.purchase_no}</span>
            <span className="text-xs text-slate-500">
              {p.purchased_at?.slice(0, 10)}
              {p.reference && ` · their ref ${p.reference}`}
              {p.payment_mode && ` · ${p.payment_mode}`}
            </span>
            <span className="num ml-auto text-sm font-medium">{fmtMoney(p.total)}</span>
          </li>
        ))}
      </ul>
    </div>
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
  tone?: "owe";
}) {
  return (
    <div className="card">
      <p className="eyebrow">{label}</p>
      <p
        className={`num mt-1 text-xl font-semibold ${
          tone === "owe" ? "text-sky-700" : "text-slate-900"
        }`}
      >
        {value}
      </p>
      <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{hint}</p>
    </div>
  );
}

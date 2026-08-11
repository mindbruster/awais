import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Position {
  as_of: string;
  cash_in_hand: string;
  gold_in_hand_g: string;
  gold_with_workers_g: string;
  customer_receivable: string;
  supplier_payable: string;
  worker_payable: string;
}

const fmtGrams = (v: string) =>
  `${Number(v).toLocaleString(undefined, {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  })} g`;

export function PositionPage() {
  const [data, setData] = useState<Position | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .get<Position>("/ledger/position")
      .then((res) => setData(res.data))
      .catch((e) => setError(apiError(e, "Failed to load the position")))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Position</h1>
        <button className="btn-ghost" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        What the shop is holding this morning{data ? ` — as of ${data.as_of}` : ""}. Every figure is
        rebuilt from the journal, so it can always be traced back to the entries behind it.
      </p>

      {error && <div className="card mt-4 text-sm text-red-600">{error}</div>}
      {loading && !data && <div className="card mt-4 text-sm text-slate-500">Loading…</div>}

      {data && (
        <>
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <Tile
              label="Cash in hand"
              value={fmtMoney(data.cash_in_hand)}
              note="Counter cash, excluding bank"
              accent="emerald"
            />
            <Tile
              label="Gold in hand"
              value={fmtGrams(data.gold_in_hand_g)}
              note="Fine grams in the shop"
              accent="brand"
            />
            <Tile
              label="Gold with workers"
              value={fmtGrams(data.gold_with_workers_g)}
              note="Issued out and not yet returned"
              accent="amber"
            />
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <Tile
              label="Receivable"
              value={fmtMoney(data.customer_receivable)}
              note="Owed to the shop by customers"
              accent="emerald"
            />
            <Tile
              label="Supplier payable"
              value={fmtMoney(data.supplier_payable)}
              note="Owed by the shop to suppliers"
              accent="red"
            />
            <Tile
              label="Worker payable"
              value={fmtMoney(data.worker_payable)}
              note="Labour earned and not yet paid"
              accent="red"
            />
          </div>
        </>
      )}
    </div>
  );
}

const ACCENT: Record<string, string> = {
  emerald: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  amber: "bg-amber-50 text-amber-900 ring-amber-200",
  brand: "bg-brand-50 text-brand-800 ring-brand-200",
  red: "bg-red-50 text-red-800 ring-red-200",
};

function Tile({
  label,
  value,
  note,
  accent,
}: {
  label: string;
  value: string;
  note: string;
  accent: string;
}) {
  return (
    <div className={`card ring-1 ${ACCENT[accent]}`}>
      <div className="text-xs uppercase opacity-70">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      <div className="mt-1 text-xs opacity-70">{note}</div>
    </div>
  );
}

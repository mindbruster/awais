import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { FilterSelect, Toolbar } from "@/components/Toolbar";
import { apiError } from "@/lib/api-error";

const MOVEMENT_TYPES = [
  { value: "purchase_in", label: "Purchase in" },
  { value: "manufacturing_out", label: "Manufacturing out" },
  { value: "manufacturing_in", label: "Manufacturing in" },
  { value: "sale_out", label: "Sale out" },
  { value: "sale_return_in", label: "Sale return in" },
  { value: "approval_out", label: "Approval out" },
  { value: "approval_return_in", label: "Approval return in" },
  { value: "adjustment", label: "Adjustment" },
];

interface Movement {
  id: number;
  type: string;
  inventory_item_id: number;
  quantity_delta: number;
  weight_g_delta: string;
  weight_ct_delta: string;
  reference_type: string | null;
  reference_id: number | null;
  notes: string | null;
  created_at: string;
}

const TYPE_COLOR: Record<string, string> = {
  purchase_in: "bg-emerald-100 text-emerald-800",
  manufacturing_in: "bg-emerald-100 text-emerald-800",
  sale_return_in: "bg-emerald-100 text-emerald-800",
  approval_return_in: "bg-emerald-100 text-emerald-800",
  manufacturing_out: "bg-amber-100 text-amber-800",
  sale_out: "bg-red-100 text-red-700",
  approval_out: "bg-blue-100 text-blue-800",
  adjustment: "bg-slate-200 text-slate-700",
};

const fmtDelta = (v: string | number) => {
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (n === 0) return "—";
  return n > 0 ? `+${n}` : `${n}`;
};

export function StockMovementsPage() {
  const [items, setItems] = useState<Movement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [type, setType] = useState("");

  useEffect(() => {
    setLoading(true);
    api
      .get<Movement[]>("/stock-movements", { params: type ? { type } : {} })
      .then((res) => setItems(res.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  }, [type]);

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Stock ledger</h1>
      <p className="mt-1 text-sm text-slate-500">
        Immutable audit trail of every stock change. Linked to invoices,
        manufacturing jobs and adjustments.
      </p>
      <Toolbar>
        <FilterSelect value={type} onChange={setType} options={MOVEMENT_TYPES} allLabel="All types" />
        <span className="ml-auto text-xs text-slate-500">{items.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            No movements yet. They are created automatically by manufacturing
            and sales actions, or directly via POST /api/v1/stock-movements.
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">When</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Item</th>
                <th className="px-4 py-3 text-right">Qty Δ</th>
                <th className="px-4 py-3 text-right">Gold Δ (g)</th>
                <th className="px-4 py-3 text-right">Stone Δ (ct)</th>
                <th className="px-4 py-3">Ref</th>
                <th className="px-4 py-3">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((m) => (
                <tr key={m.id}>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {new Date(m.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        TYPE_COLOR[m.type] ?? "bg-slate-100"
                      }`}
                    >
                      {m.type}
                    </span>
                  </td>
                  <td className="px-4 py-3">#{m.inventory_item_id}</td>
                  <td className="px-4 py-3 text-right">
                    {fmtDelta(m.quantity_delta)}
                  </td>
                  <td className="px-4 py-3 text-right">{fmtDelta(m.weight_g_delta)}</td>
                  <td className="px-4 py-3 text-right">{fmtDelta(m.weight_ct_delta)}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {m.reference_type
                      ? `${m.reference_type} #${m.reference_id ?? "—"}`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{m.notes ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

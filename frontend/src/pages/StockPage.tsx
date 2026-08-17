/**
 * Everything the shop is holding, in the unit it is held in.
 *
 * This existed only as a block buried inside Reports that grouped inventory
 * rows by type — it could say there were 1,240 grams of raw gold, but not that
 * they were 22k, not what they were worth, and not that the eight kilos beside
 * them were silver.
 *
 * Gold and silver are never added together. They differ a hundredfold in value
 * and a combined "metal" figure is a number in no unit at all; the only place
 * they meet is the rupee total, where both have become money. Stones stay in
 * carats and are held at what they cost, because there is no market rate for a
 * grade of diamond the way there is for metal.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface MetalPosition {
  metal: "gold" | "silver";
  weight_g: string;
  fine_weight_g: string;
  rate_per_fine_g: string | null;
  value: string | null;
}

interface StockPosition {
  as_of: string;
  metals: MetalPosition[];
  stone_weight_ct: string;
  stone_value: string;
  broken_stone_weight_ct: string;
  finished_pieces: number;
  finished_value: string;
  total_value: string;
  unpriced_metals: string[];
}

interface Bucket {
  type: string;
  items: number;
  total_quantity: number;
  total_weight_g: string;
  total_weight_ct: string;
}

const TYPE_LABEL: Record<string, string> = {
  raw_gold: "Raw gold",
  raw_silver: "Raw silver",
  raw_stone: "Raw stone",
  broken_stone: "Broken / misc stones",
  finished_product: "Finished pieces",
  other: "Other",
};

const wt = (v: string | number, unit: "g" | "ct") =>
  `${Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 })} ${unit}`;

export function StockPage() {
  const [pos, setPos] = useState<StockPosition | null>(null);
  const [buckets, setBuckets] = useState<Bucket[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<StockPosition>("/reports/stock-position"),
      api.get<{ by_type: Bucket[] }>("/reports/stock"),
    ])
      .then(([p, s]) => {
        setPos(p.data);
        setBuckets(s.data.by_type);
      })
      .catch((e) => setError(apiError(e, "Could not load stock")))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-sm text-slate-500">Loading…</div>;
  if (error) return <div className="text-sm text-red-600">{error}</div>;
  if (!pos) return null;

  const gold = pos.metals.find((m) => m.metal === "gold");
  const silver = pos.metals.find((m) => m.metal === "silver");

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Stock</h1>
        <span className="text-xs text-slate-500">as of {pos.as_of}</span>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        What the shop is holding and what it is worth this morning. Metals are valued on their
        pure content, not their scale reading.
      </p>

      {pos.unpriced_metals.length > 0 && (
        <p className="mt-4 rounded-xl bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-900">
          No rate is on record today for {pos.unpriced_metals.join(" or ")}, so it is counted but
          not valued — the total below is everything except that.{" "}
          <Link to="/gold-rates" className="font-medium underline">
            Set today's rate
          </Link>
          .
        </p>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {gold && <MetalCard label="Gold" m={gold} />}
        {silver && <MetalCard label="Silver" m={silver} />}
        <div className="card">
          <p className="eyebrow">Stones</p>
          <p className="num mt-1 text-xl font-semibold text-slate-900">
            {wt(pos.stone_weight_ct, "ct")}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {fmtMoney(pos.stone_value)} at cost
            {Number(pos.broken_stone_weight_ct) > 0 && (
              <> · {wt(pos.broken_stone_weight_ct, "ct")} broken</>
            )}
          </p>
        </div>
        <div className="card">
          <p className="eyebrow">Finished pieces</p>
          <p className="num mt-1 text-xl font-semibold text-slate-900">{pos.finished_pieces}</p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {fmtMoney(pos.finished_value)} of material
          </p>
        </div>
      </div>

      <div className="card mt-4">
        <div className="flex items-baseline justify-between">
          <p className="eyebrow">Everything, valued</p>
          <p className="num text-2xl font-semibold text-slate-900">
            {fmtMoney(pos.total_value)}
          </p>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
          Metals at today's rate, stones and finished pieces at what they cost. The two metals are
          only added here, where both have become money.
        </p>
      </div>

      <div className="card mt-4 p-0">
        <div className="border-b border-slate-100 px-5 py-3">
          <p className="eyebrow">By category</p>
        </div>
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-5 py-2">Category</th>
              <th className="px-5 py-2 text-right">Rows</th>
              <th className="px-5 py-2 text-right">Pieces</th>
              <th className="px-5 py-2 text-right">Grams</th>
              <th className="px-5 py-2 text-right">Carats</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {buckets.map((b) => (
              <tr key={b.type}>
                <td className="px-5 py-2.5">
                  <Link
                    to={`/inventory?type=${b.type}`}
                    className="text-brand-700 hover:underline"
                  >
                    {TYPE_LABEL[b.type] ?? b.type}
                  </Link>
                </td>
                <td className="num px-5 py-2.5 text-right text-slate-500">{b.items}</td>
                <td className="num px-5 py-2.5 text-right">{b.total_quantity || "—"}</td>
                <td className="num px-5 py-2.5 text-right">
                  {Number(b.total_weight_g) ? wt(b.total_weight_g, "g") : "—"}
                </td>
                <td className="num px-5 py-2.5 text-right">
                  {Number(b.total_weight_ct) ? wt(b.total_weight_ct, "ct") : "—"}
                </td>
              </tr>
            ))}
            {buckets.length === 0 && (
              <tr>
                <td colSpan={5} className="px-5 py-6 text-center text-sm text-slate-500">
                  Nothing in stock yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MetalCard({ label, m }: { label: string; m: MetalPosition }) {
  const held = Number(m.weight_g) > 0;
  return (
    <div className="card">
      <p className="eyebrow">{label}</p>
      <p className="num mt-1 text-xl font-semibold text-slate-900">
        {held ? wt(m.fine_weight_g, "g") : "—"}
      </p>
      {held ? (
        <p className="num mt-0.5 text-[11px] leading-snug text-slate-500">
          {wt(m.weight_g, "g")} as weighed
          {m.rate_per_fine_g ? (
            <> · {fmtMoney(m.rate_per_fine_g)}/g fine</>
          ) : (
            <span className="text-amber-700"> · no rate today</span>
          )}
        </p>
      ) : (
        <p className="mt-0.5 text-[11px] text-slate-400">none on hand</p>
      )}
      {m.value && (
        <p className="num mt-1.5 text-sm font-medium text-slate-900">{fmtMoney(m.value)}</p>
      )}
    </div>
  );
}

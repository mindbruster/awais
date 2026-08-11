import { useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { Toolbar } from "@/components/Toolbar";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface StoneOption {
  id: number;
  name: string;
}

interface StockRow {
  stone_id: number;
  stone_name: string;
  stone_kind: string;
  category: "stone" | "diamond";
  abbreviation: string | null;
  quality: string | null;
  cut: string | null;
  color: string | null;
  clarity: string | null;
  purchased_quantity: number;
  purchased_weight_ct: string;
  purchased_value: string;
  avg_rate_per_ct: string;
  used_quantity: number;
  used_weight_ct: string;
  available_quantity: number;
  available_weight_ct: string;
}

interface StockReport {
  rows: StockRow[];
  total_purchased_weight_ct: string;
  total_used_weight_ct: string;
  total_available_weight_ct: string;
}

const ct = (v: string | number) => Number(v).toFixed(4);

export function StoneStockPage() {
  const [report, setReport] = useState<StockReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stones, setStones] = useState<StoneOption[]>([]);

  const [category, setCategory] = useState("");
  const [stoneId, setStoneId] = useState("");
  const [quality, setQuality] = useState("");
  const [cut, setCut] = useState("");
  const [clarity, setClarity] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const params = useMemo(() => {
    const p: Record<string, string> = {};
    if (category) p.category = category;
    if (stoneId) p.stone_id = stoneId;
    if (quality) p.quality = quality;
    if (cut) p.cut = cut;
    if (clarity) p.clarity = clarity;
    if (dateFrom) p.date_from = dateFrom;
    if (dateTo) p.date_to = dateTo;
    return p;
  }, [category, stoneId, quality, cut, clarity, dateFrom, dateTo]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .get<StockReport>("/purchasing/stone-stock", { params })
      .then((r) => setReport(r.data))
      .catch((e) => setError(apiError(e, "Failed to load the stock report")))
      .finally(() => setLoading(false));
  }, [params]);

  useEffect(() => {
    api
      .get<StoneOption[]>("/stones", { params: { limit: "300" } })
      .then((r) => setStones(r.data))
      .catch(() => setStones([]));
  }, []);

  const rows = report?.rows ?? [];
  const windowed = !!(dateFrom || dateTo);

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Stone stock</h1>
      <p className="mt-1 text-sm text-slate-500">
        Bought, used and left — per stone <em>and grade</em>, because "how much 12 PTR do I have"
        is never the question; "how much 12 PTR commercial" is. Usage is what setting legs issued
        less what they returned, so this counts stones that went into pieces, not stones that
        merely left the safe.
      </p>

      <Toolbar>
        <select
          className="input w-auto"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          <option value="diamond">Diamond</option>
          <option value="stone">Stone</option>
        </select>
        <select
          className="input w-auto"
          value={stoneId}
          onChange={(e) => setStoneId(e.target.value)}
        >
          <option value="">All stones</option>
          {stones.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <input
          className="input w-36"
          placeholder="Quality"
          value={quality}
          onChange={(e) => setQuality(e.target.value)}
        />
        <input
          className="input w-32"
          placeholder="Cut"
          value={cut}
          onChange={(e) => setCut(e.target.value)}
        />
        <input
          className="input w-32"
          placeholder="Clarity"
          value={clarity}
          onChange={(e) => setClarity(e.target.value)}
        />
        <label className="flex items-center gap-2 text-xs text-slate-500">
          From
          <input
            type="date"
            className="input w-auto"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-500">
          To
          <input
            type="date"
            className="input w-auto"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </label>
        <span className="ml-auto text-xs text-slate-500">{rows.length} grades</span>
      </Toolbar>

      {windowed && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
          A date window narrows both sides equally, so this reads as movement for the period —
          not the position as it stands today. Clear the dates for that.
        </p>
      )}

      <div className="card mt-4 overflow-x-auto p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && rows.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            Nothing bought or consumed under these filters.
          </div>
        )}
        {rows.length > 0 && (
          <table className="w-full min-w-[1000px] text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Stone</th>
                <th className="px-4 py-3">Grade</th>
                <th className="px-4 py-3 text-right">Bought (pcs)</th>
                <th className="px-4 py-3 text-right">Bought (ct)</th>
                <th className="px-4 py-3 text-right">Avg rate/ct</th>
                <th className="px-4 py-3 text-right">Value</th>
                <th className="px-4 py-3 text-right">Used (pcs)</th>
                <th className="px-4 py-3 text-right">Used (ct)</th>
                <th className="px-4 py-3 text-right">Left (pcs)</th>
                <th className="px-4 py-3 text-right">Left (ct)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => {
                const short = Number(r.available_weight_ct) < 0;
                return (
                  <tr
                    key={`${r.stone_id}-${r.quality}-${r.cut}-${r.color}-${r.clarity}`}
                    className="hover:bg-slate-50"
                  >
                    <td className="whitespace-nowrap px-4 py-3">
                      <span className="font-medium">{r.stone_name}</span>
                      <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase text-slate-500">
                        {r.category}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {[r.quality, r.cut, r.color, r.clarity].filter(Boolean).join(" / ") ||
                        "ungraded"}
                    </td>
                    <td className="px-4 py-3 text-right">{r.purchased_quantity}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      {ct(r.purchased_weight_ct)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-slate-500">
                      {fmtMoney(r.avg_rate_per_ct)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-slate-500">
                      {fmtMoney(r.purchased_value)}
                    </td>
                    <td className="px-4 py-3 text-right">{r.used_quantity}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      {ct(r.used_weight_ct)}
                    </td>
                    <td
                      className={`px-4 py-3 text-right ${short ? "text-red-600" : "font-medium"}`}
                    >
                      {r.available_quantity}
                    </td>
                    <td
                      className={`whitespace-nowrap px-4 py-3 text-right ${
                        short ? "font-semibold text-red-600" : "font-semibold"
                      }`}
                    >
                      {ct(r.available_weight_ct)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot className="border-t border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <td className="px-4 py-3" colSpan={3}>
                  Totals
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-right text-slate-900">
                  {ct(report?.total_purchased_weight_ct ?? 0)}
                </td>
                <td className="px-4 py-3" colSpan={3} />
                <td className="whitespace-nowrap px-4 py-3 text-right text-slate-900">
                  {ct(report?.total_used_weight_ct ?? 0)}
                </td>
                <td className="px-4 py-3" />
                <td className="whitespace-nowrap px-4 py-3 text-right text-slate-900">
                  {ct(report?.total_available_weight_ct ?? 0)}
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      {rows.some((r) => Number(r.available_weight_ct) < 0) && (
        <p className="mt-3 text-xs text-red-600">
          A negative figure means stones went into pieces that this system never saw bought —
          usually stock that predates purchasing. Record the opening lot to clear it.
        </p>
      )}
    </div>
  );
}

/**
 * What the market is doing — on its own tab, and touching nothing.
 *
 * The shop asked for live rates "only show them in a separate tab", and the
 * separateness is the design, not a layout choice. Every invoice, every product
 * costing and every journal entry that values metal reads the rate the shop
 * *sets*. A feed wired into pricing would reprice the counter mid-sale from a
 * number nobody in the shop agreed to.
 *
 * So this page has no action that changes anything. It shows spot beside the
 * rate you have set, and where the two differ it says so and leaves the
 * decision with you — which is the only honest thing it can do, because the
 * feed is international spot and the bazaar sets its own price.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface LiveRates {
  currency: string;
  gold_per_gram: string | null;
  silver_per_gram: string | null;
  fetched_at: string;
  unavailable: string | null;
  caveat: string;
  source: string;
}

interface SetRate {
  rate_per_g: string;
  purity: number;
  metal: string;
  fineness_pct: string | null;
  rate_date: string;
}

export function LiveRatesPage() {
  const [live, setLive] = useState<LiveRates | null>(null);
  const [gold, setGold] = useState<SetRate | null>(null);
  const [silver, setSilver] = useState<SetRate | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    try {
      const l = await api.get<LiveRates>("/gold-rates/live", {
        params: refresh ? { refresh: true } : {},
      });
      setLive(l.data);
    } catch (e) {
      toast("error", apiError(e, "Could not reach the rate service"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
    // The rate the shop has set, for each metal. A 404 is the ordinary answer
    // on a day nobody has keyed one, so it is not treated as a failure.
    for (const [metal, set] of [
      ["gold", setGold],
      ["silver", setSilver],
    ] as const) {
      try {
        const r = await api.get<SetRate>("/gold-rates/current", {
          params: { metal, currency: "PKR" },
        });
        set(r.data);
      } catch {
        set(null);
      }
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <div className="text-sm text-slate-500">Loading…</div>;

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Live rates</h1>
        <button
          className="btn-ghost"
          onClick={() => load(true)}
          disabled={refreshing}
        >
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        The market, for reference. Nothing here prices anything.
      </p>

      {live?.unavailable ? (
        <div className="card mt-4 border-amber-200 bg-amber-50">
          <p className="text-sm leading-relaxed text-amber-900">{live.unavailable}</p>
        </div>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <RateCard
            label="Gold"
            spot={live?.gold_per_gram ?? null}
            set={gold}
            setLabel="24k"
          />
          <RateCard
            label="Silver"
            spot={live?.silver_per_gram ?? null}
            set={silver}
            setLabel="999"
          />
        </div>
      )}

      <div className="card mt-4">
        <p className="eyebrow">What this is, and is not</p>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">{live?.caveat}</p>
        <p className="mt-3 text-xs text-slate-500">
          Source: {live?.source} · fetched{" "}
          {live ? new Date(live.fetched_at).toLocaleTimeString() : "—"}
        </p>
        <p className="mt-3 border-t border-slate-100 pt-3 text-xs leading-relaxed text-slate-500">
          To change what the shop prices at, set the rate under{" "}
          <Link to="/gold-rates" className="font-medium text-brand-700 hover:underline">
            Gold rates
          </Link>
          . That is deliberately a separate action — a number fetched from the internet should
          not be able to reprice a sale in progress.
        </p>
      </div>
    </div>
  );
}

function RateCard({
  label,
  spot,
  set,
  setLabel,
}: {
  label: string;
  spot: string | null;
  set: SetRate | null;
  setLabel: string;
}) {
  const spotN = spot ? Number(spot) : null;
  const setN = set ? Number(set.rate_per_g) : null;
  // The gap between the market and what the shop is charging. Shown as a
  // difference rather than as two numbers to compare by eye, because that gap
  // is the only reason to look at this page at all.
  const gap = spotN !== null && setN !== null ? setN - spotN : null;
  const gapPct = gap !== null && spotN ? (gap / spotN) * 100 : null;

  return (
    <div className="card">
      <p className="eyebrow">{label} — market</p>
      <p className="num mt-1 text-2xl font-semibold text-slate-900">
        {spotN !== null ? `${fmtMoney(spotN)} / g` : "—"}
      </p>
      <p className="mt-0.5 text-[11px] text-slate-500">per gram of pure metal</p>

      <div className="mt-3 border-t border-slate-100 pt-3">
        <p className="eyebrow">Your rate ({setLabel})</p>
        {setN !== null ? (
          <>
            <p className="num mt-1 text-lg font-medium text-slate-900">
              {fmtMoney(setN)} / g
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">set {set?.rate_date}</p>
            {gap !== null && gapPct !== null && (
              <p
                className={`num mt-1.5 text-xs ${
                  gap >= 0 ? "text-emerald-700" : "text-amber-700"
                }`}
              >
                {gap >= 0 ? "+" : "−"}
                {fmtMoney(Math.abs(gap))} ({gapPct >= 0 ? "+" : "−"}
                {Math.abs(gapPct).toFixed(1)}%) against the market
              </p>
            )}
          </>
        ) : (
          <p className="mt-1 text-sm text-amber-700">
            No rate set today — nothing can be priced or posted until there is one.
          </p>
        )}
      </div>
    </div>
  );
}

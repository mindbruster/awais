/**
 * Two businesses under one roof, and what the market did to the metal.
 *
 * The split and the revaluation share a page because they are the same
 * question asked from two sides: what the shop earned by trading, and what it
 * gained or lost by simply holding. A jeweller can have a flat month on the
 * floor and be materially richer, or a good month and be poorer, and neither
 * figure alone says so.
 *
 * The revaluation is the only action on this page and it is deliberately
 * awkward: a preview you can open all day, and a posting that needs your
 * password. Moving the balance sheet to market is a decision somebody makes,
 * not something that happens while a page loads.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Stream {
  stream: string;
  revenue: string;
  cost: string;
  gross_margin: string;
  margin_pct: string | null;
}

interface Split {
  currency: string;
  streams: Stream[];
  revenue: string;
  cost: string;
  gross_margin: string;
  lines: number;
  unsplit_lines: number;
  basis: "cost" | "replacement";
  basis_label: string;
  // Every judgement the report made, in plain sentences. Shown in full rather
  // than summarised: the shop never wrote its profit formulas down, so a
  // conventional method was implemented, and the honest way to present that is
  // to say what was assumed instead of letting the figures look authoritative.
  assumptions: string[];
  basis_fallback: string | null;
}

interface MetalValuation {
  metal: string;
  fine_grams: string;
  rate_per_fine_g: string | null;
  book_value: string;
  market_value: string | null;
  difference: string | null;
  unpriced: string | null;
}

interface Revaluation {
  as_of: string;
  metals: MetalValuation[];
  total_difference: string;
}

const LABEL: Record<string, string> = {
  gold: "Gold",
  stones: "Stones",
  making: "Making",
};

const WHY: Record<string, string> = {
  gold: "Bought and sold at a rate that moves daily. Margin is the spread plus wastage charged.",
  stones: "Bought in parcels at a negotiated price and held for months. Margin was fixed when the parcel was.",
  making: "The shop's own labour, sold on. Moves with neither rate.",
};

export function ProfitSplitPage() {
  const [split, setSplit] = useState<Split | null>(null);
  const [reval, setReval] = useState<Revaluation | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [basis, setBasis] = useState<"cost" | "replacement">("cost");
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  const load = useCallback(async () => {
    const params: Record<string, string> = { basis };
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    try {
      const s = await api.get<Split>("/reports/profit-split", { params });
      setSplit(s.data);
    } catch (e) {
      setError(apiError(e, "Could not load the profit split"));
    }
    try {
      const r = await api.get<Revaluation>("/ledger/revaluation");
      setReval(r.data);
    } catch {
      setReval(null);
    }
  }, [from, to, basis]);

  useEffect(() => {
    load();
  }, [load]);

  const postReval = async (password: string) => {
    try {
      const r = await api.post<{ entry_no: string | null; total_difference: string }>(
        "/ledger/revaluation",
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast(
        "success",
        r.data.entry_no
          ? `Posted ${r.data.entry_no} — ${fmtMoney(r.data.total_difference)}`
          : "Nothing to move: the books already hold metal at today's rate.",
      );
      setAsking(false);
      load();
    } catch (err) {
      toast("error", apiError(err, "Could not post the revaluation"));
    }
  };

  if (error) return <div className="card text-red-600">{error}</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Profit</h1>
        <p className="mt-1 text-sm text-slate-500">
          What the shop earned by trading, and what the market did to the metal it was
          already holding.
        </p>
      </div>

      {/* Two legitimate answers to "what did we make", not a display option.
          Labelled by the question each one answers, because "cost" and
          "replacement" mean nothing to somebody who has not read the code. */}
      <div className="card">
        <p className="eyebrow">How should metal be valued?</p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {(
            [
              {
                key: "cost" as const,
                title: "At what we paid",
                blurb:
                  "The rate locked onto each piece when it was stocked. Gross profit as an accountant means it — and the only one that reconciles to the ledger unaided.",
              },
              {
                key: "replacement" as const,
                title: "At today's rate",
                blurb:
                  "What it would cost to restock what you just sold. In a rising market this is the smaller, more sobering number.",
              },
            ]
          ).map((o) => (
            <button
              key={o.key}
              onClick={() => setBasis(o.key)}
              className={`rounded-xl border p-3 text-left transition ${
                basis === o.key
                  ? "border-brand-400 bg-brand-50"
                  : "border-slate-200 hover:border-slate-300"
              }`}
            >
              <p className="text-sm font-semibold text-slate-900">{o.title}</p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{o.blurb}</p>
            </button>
          ))}
        </div>
        {split?.basis_fallback && (
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-900">
            {split.basis_fallback}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
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
        <a
          className="btn-ghost ml-auto"
          href={`/api/v1/reports/profit-split?format=csv&basis=${basis}${
            from ? `&date_from=${from}` : ""
          }${to ? `&date_to=${to}` : ""}`}
        >
          Export CSV
        </a>
      </div>

      {/* --- the two businesses --- */}
      {split && (
        <section>
          <h2 className="eyebrow">Earned by trading</h2>
          <div className="mt-2 grid gap-3 lg:grid-cols-3">
            {split.streams.map((s) => (
              <div key={s.stream} className="card">
                <div className="flex items-baseline justify-between">
                  <p className="text-sm font-semibold text-slate-900">
                    {LABEL[s.stream] ?? s.stream}
                  </p>
                  <p
                    className={`num text-lg font-semibold ${
                      Number(s.gross_margin) >= 0 ? "text-emerald-700" : "text-red-600"
                    }`}
                  >
                    {s.margin_pct !== null ? `${Number(s.margin_pct).toFixed(1)}%` : "—"}
                  </p>
                </div>
                <dl className="mt-2 space-y-1 text-xs">
                  <Row label="Revenue" value={fmtMoney(s.revenue)} />
                  <Row label="Cost" value={fmtMoney(s.cost)} />
                  <Row label="Margin" value={fmtMoney(s.gross_margin)} strong />
                </dl>
                <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                  {WHY[s.stream]}
                </p>
              </div>
            ))}
          </div>

          <div className="card mt-3">
            <dl className="space-y-1 text-sm">
              <Row label="Total revenue" value={fmtMoney(split.revenue)} />
              <Row label="Total cost" value={fmtMoney(split.cost)} />
              <Row label="Gross margin" value={fmtMoney(split.gross_margin)} strong />
            </dl>
            {split.unsplit_lines > 0 && (
              <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-900">
                {split.unsplit_lines} of {split.lines} line
                {split.lines === 1 ? "" : "s"} could not be split between metal and stones —
                no product behind them, or a piece with no gold rate locked when it was
                costed. Their cost is charged whole to gold rather than guessed at, so the
                two margins above are firm only to the extent this number is small.
              </p>
            )}
          </div>

          {/* Stated in full, never collapsed. These figures come from a
              conventional method rather than one the shop wrote down, and a
              reader deciding prices off them is entitled to know on what. */}
          {split.assumptions.length > 0 && (
            <div className="card mt-3 bg-slate-50/60">
              <p className="eyebrow">What this assumes</p>
              <ul className="mt-2 space-y-1.5">
                {split.assumptions.map((a, i) => (
                  <li
                    key={i}
                    className="flex gap-2 text-[11px] leading-relaxed text-slate-600"
                  >
                    <span className="flex-none text-slate-300">—</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 border-t border-slate-200 pt-2 text-[11px] italic leading-relaxed text-slate-500">
                The shop has not written its profit formulas down, so these follow the
                common jeweller's convention. Tell us where one differs from how you
                reckon it and it will be changed — nothing here is a rule the system
                invented for its own convenience.
              </p>
            </div>
          )}
        </section>
      )}

      {/* --- what holding it did --- */}
      {reval && (
        <section>
          <div className="flex items-baseline justify-between">
            <h2 className="eyebrow">Gained or lost by holding</h2>
            <span className="text-xs text-slate-500">as of {reval.as_of}</span>
          </div>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            {reval.metals.map((m) => (
              <div key={m.metal} className="card">
                <p className="text-sm font-semibold capitalize text-slate-900">{m.metal}</p>
                {m.unpriced ? (
                  <p className="mt-1 text-[11px] leading-relaxed text-amber-700">{m.unpriced}</p>
                ) : (
                  <>
                    <dl className="mt-2 space-y-1 text-xs">
                      <Row label="Held" value={`${Number(m.fine_grams).toFixed(4)} g fine`} />
                      <Row label="On the books at" value={fmtMoney(m.book_value)} />
                      <Row label="Worth today" value={fmtMoney(m.market_value)} />
                      <Row
                        label={Number(m.difference) >= 0 ? "Unrecognised gain" : "Unrecognised loss"}
                        value={fmtMoney(m.difference)}
                        strong
                      />
                    </dl>
                    <p className="mt-2 text-[11px] text-slate-500">
                      at {fmtMoney(m.rate_per_fine_g)} per fine gram
                    </p>
                  </>
                )}
              </div>
            ))}
          </div>

          <div className="card mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="num text-lg font-semibold text-slate-900">
                {fmtMoney(reval.total_difference)}
              </p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
                Posting this moves the metal accounts to market and books the difference to
                4500. Only money moves — not one gram changes, because no metal moved.
                {Number(reval.total_difference) < 0 &&
                  " A falling rate books a real loss, in a month the floor may have worked well."}
              </p>
            </div>
            <button
              className="btn-primary flex-none"
              disabled={Number(reval.total_difference) === 0}
              onClick={() => setAsking(true)}
            >
              {Number(reval.total_difference) === 0
                ? "Already at market"
                : "Post revaluation"}
            </button>
          </div>
        </section>
      )}

      <PasswordConfirm
        open={asking}
        onClose={() => setAsking(false)}
        title="Move the metal to market?"
        description={
          `This posts ${fmtMoney(reval?.total_difference)} to the books and changes the ` +
          "balance sheet and this month's profit. The gram balances are untouched. " +
          "Undoing it means a hand-written reversal."
        }
        confirmLabel="Post revaluation"
        onConfirm={postReval}
      />
    </div>
  );
}

function Row({
  label,
  value,
  strong,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className={`num ${strong ? "font-semibold text-slate-900" : "text-slate-700"}`}>
        {value}
      </dd>
    </div>
  );
}

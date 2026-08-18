/**
 * The whole business on one page: what it is worth, and how it is trading.
 *
 * Two questions that get confused constantly and answer differently. A shop can
 * trade flat on the floor and be materially richer because the rate moved, or
 * trade well and be poorer. So worth and trading sit in separate blocks here
 * and are never added — a single number covering both answers neither.
 *
 * Every figure is fetched already computed by the screen that owns it: stock
 * values from the stock position, trading from the profit split, cash from the
 * cash flow. Nothing is re-derived, because a second definition of net worth is
 * a second thing to disagree with the first, and this is the page a partner
 * gets shown.
 *
 * It is only honest at all because the shelves and the books now agree. Until
 * the four paths that moved stock without the ledger were closed, the metal
 * line alone could have been out by a hundred and twenty million rupees
 * depending on which table it read.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Line {
  key: string;
  label: string;
  amount: string;
  detail: string | null;
  to: string | null;
}

interface Period {
  label: string;
  date_from: string | null;
  date_to: string | null;
  invoices: number;
  sales: string;
  cost_of_goods: string;
  gross_margin: string;
  margin_pct: string | null;
  expenses: string;
  net: string;
  cash_opened: string;
  cash_closed: string;
}

interface Overview {
  as_of: string;
  worth: {
    as_of: string;
    owned: Line[];
    owed: Line[];
    total_owned: string;
    total_owed: string;
    net_worth: string;
    unpriced: string[];
  };
  period: Period;
  previous: Period | null;
  metal_outside_g: string;
  overdue_bills: number;
  overdue_bill_amount: string;
  basis: string;
  assumptions: string[];
}

const n = (v: string | null) => Number(v ?? 0) || 0;

/** Percentage change, or null when the base is zero — not "∞", and not 0%. */
function delta(now: string, before: string | undefined): number | null {
  const b = n(before ?? null);
  if (!b) return null;
  return ((n(now) - b) / Math.abs(b)) * 100;
}

export function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const params: Record<string, string> = {};
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    api
      .get<Overview>("/reports/overview", { params })
      .then((r) => setData(r.data))
      .catch((e) => setError(apiError(e, "Could not load the overview")));
  }, [from, to]);

  useEffect(load, [load]);

  if (error) return <div className="card text-sm text-red-600">{error}</div>;
  if (!data) return <div className="card text-sm text-slate-500">Loading…</div>;

  const w = data.worth;
  const p = data.period;
  const prev = data.previous ?? undefined;

  return (
    <div className="space-y-6">
      <div className="no-print flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Business overview</h1>
          <p className="mt-1 text-sm text-slate-500">
            What the shop is worth, and how it is trading. The two are kept apart —
            a good month and a richer business are not the same fact.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-slate-500">
            From{" "}
            <input type="date" className="input ml-1 w-auto py-1" value={from}
                   onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="text-xs text-slate-500">
            to{" "}
            <input type="date" className="input ml-1 w-auto py-1" value={to}
                   onChange={(e) => setTo(e.target.value)} />
          </label>
          <button className="btn-outline" onClick={() => window.print()}>
            Print
          </button>
        </div>
      </div>

      {/* Exceptions first. A beautiful net-worth figure does not matter if
          fifty grams are sitting unaccounted for at a setter. */}
      {(data.overdue_bills > 0 || n(data.metal_outside_g) !== 0) && (
        <div className="grid gap-3 sm:grid-cols-2">
          {data.overdue_bills > 0 && (
            <Link to="/purchasing/bills" className="card block bg-red-50 ring-1 ring-red-200">
              <p className="text-xs uppercase text-red-700">Overdue bills</p>
              <p className="num mt-0.5 text-xl font-semibold text-red-900">
                {fmtMoney(data.overdue_bill_amount)}
              </p>
              <p className="mt-0.5 text-xs text-red-700">
                {data.overdue_bills} bill{data.overdue_bills === 1 ? "" : "s"} past their date
              </p>
            </Link>
          )}
          {n(data.metal_outside_g) !== 0 && (
            <Link to="/material-outside" className="card block bg-amber-50 ring-1 ring-amber-200">
              <p className="text-xs uppercase text-amber-800">Gold outside the building</p>
              <p className="num mt-0.5 text-xl font-semibold text-amber-900">
                {Number(data.metal_outside_g).toFixed(3)} fine g
              </p>
              <p className="mt-0.5 text-xs text-amber-800">
                {n(data.metal_outside_g) < 0
                  ? "negative — workers are owed their own metal back"
                  : "with makers and setters"}
              </p>
            </Link>
          )}
        </div>
      )}

      {/* ---- what it is worth ---- */}
      <section className="card print-block">
        <div className="flex items-baseline justify-between">
          <h2 className="eyebrow">What the business is worth</h2>
          <span className="text-xs text-slate-400">{w.as_of}</span>
        </div>
        <dl className="mt-3 space-y-1">
          {w.owned.map((l) => (
            <Row key={l.key} line={l} />
          ))}
          <div className="!mt-2 border-t border-slate-200 pt-2" />
          {w.owed.map((l) => (
            <Row key={l.key} line={l} />
          ))}
          <div className="!mt-2 flex items-baseline justify-between border-t-2 border-slate-300 pt-2">
            <dt className="text-sm font-semibold text-slate-900">Net worth</dt>
            <dd className="num text-2xl font-semibold text-slate-900">
              {fmtMoney(w.net_worth)}
            </dd>
          </div>
        </dl>
        {w.unpriced.length > 0 && (
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-900">
            {w.unpriced.join(" and ")} could not be valued — no rate on record today. The
            total above is everything <em>except</em> that, rather than a figure that
            quietly counted it as worthless.
          </p>
        )}
      </section>

      {/* ---- how it is trading ---- */}
      <section className="card print-block">
        <div className="flex items-baseline justify-between">
          <h2 className="eyebrow">How this period went</h2>
          <span className="text-xs text-slate-400">
            {p.date_from} → {p.date_to}
            {prev && ` · against ${prev.date_from} → ${prev.date_to}`}
          </span>
        </div>
        <dl className="mt-3 space-y-1">
          <Trade label="Sales" now={p.sales} before={prev?.sales} />
          <Trade label="Cost of goods" now={p.cost_of_goods} before={prev?.cost_of_goods} negative />
          <Trade label="Gross margin" now={p.gross_margin} before={prev?.gross_margin} strong
                 note={p.margin_pct !== null ? `${Number(p.margin_pct).toFixed(1)}%` : undefined} />
          <Trade label="Money out of the drawer" now={p.expenses} before={prev?.expenses} negative />
          <div className="!mt-2 flex items-baseline justify-between border-t border-slate-200 pt-2">
            <dt className="text-sm font-semibold text-slate-900">Margin less money out</dt>
            <dd className={`num text-lg font-semibold ${
              n(p.net) >= 0 ? "text-emerald-700" : "text-red-600"}`}>
              {fmtMoney(p.net)}
            </dd>
          </div>
        </dl>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          <strong>Money out</strong> is everything that left the drawer and the bank —
          suppliers paid and wages included — not only what an accountant would call an
          expense of this period. So the last line is a working figure, not a statutory
          profit, and it is deliberately not called one.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Small label="Cash and bank opened" value={fmtMoney(p.cash_opened)} />
          <Small label="Cash and bank closed" value={fmtMoney(p.cash_closed)} />
        </div>
      </section>

      {data.assumptions.length > 0 && (
        <section className="card bg-slate-50/60 print-block">
          <p className="eyebrow">What these figures assume</p>
          <ul className="mt-2 space-y-1.5">
            {data.assumptions.map((a, i) => (
              <li key={i} className="flex gap-2 text-[11px] leading-relaxed text-slate-600">
                <span className="flex-none text-slate-300">—</span>
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Row({ line }: { line: Line }) {
  const body = (
    <>
      <dt className="text-sm text-slate-600">
        {line.label}
        {line.detail && <span className="ml-2 text-xs text-slate-400">{line.detail}</span>}
      </dt>
      <dd className={`num text-sm ${n(line.amount) < 0 ? "text-red-600" : "text-slate-900"}`}>
        {fmtMoney(line.amount)}
      </dd>
    </>
  );
  return line.to ? (
    <Link to={line.to} className="flex items-baseline justify-between gap-3 rounded px-1 -mx-1 hover:bg-slate-50">
      {body}
    </Link>
  ) : (
    <div className="flex items-baseline justify-between gap-3">{body}</div>
  );
}

function Trade({
  label, now, before, negative, strong, note,
}: {
  label: string; now: string; before?: string;
  negative?: boolean; strong?: boolean; note?: string;
}) {
  const d = delta(now, before);
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className={`text-sm ${strong ? "font-medium text-slate-900" : "text-slate-600"}`}>
        {label}
        {note && <span className="ml-2 text-xs text-slate-400">{note}</span>}
      </dt>
      <dd className="flex items-baseline gap-3">
        {/* Null rather than a percentage when the previous period was zero.
            "+∞%" and "0%" are both lies about a shop that has just started. */}
        {d !== null && (
          <span className={`text-[11px] ${
            (d >= 0) === !negative ? "text-emerald-600" : "text-amber-600"}`}>
            {d >= 0 ? "+" : ""}{d.toFixed(0)}%
          </span>
        )}
        <span className={`num ${strong ? "text-lg font-semibold" : "text-sm"} ${
          negative ? "text-slate-600" : "text-slate-900"}`}>
          {negative ? `−${fmtMoney(now).replace("-", "")}` : fmtMoney(now)}
        </span>
      </dd>
    </div>
  );
}

function Small({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="num mt-0.5 text-base font-semibold text-slate-900">{value}</div>
    </div>
  );
}

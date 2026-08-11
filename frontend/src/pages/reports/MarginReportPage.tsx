import { useEffect, useState } from "react";
import { SelectField } from "@/components/Field";
import { Currency, fmtMoney } from "@/lib/money";
import {
  Bar,
  Loadable,
  Notes,
  RangeToolbar,
  ReportContents,
  Stat,
  ExportCsvButton,
  blank,
  dateParams,
  fetchInto,
  num,
  pct,
  useDateRange,
} from "@/pages/ReportsPage";

/**
 * Margin — where the month's profit actually came from.
 *
 * The page is laid out to be read top-down in about three seconds: the profit,
 * then the four levers that earned it, then everything that was handed back.
 * The levers are shown against a shared scale, because the useful question is
 * never "how big is the rate spread" but "is the rate spread carrying this
 * shop" — and that is a comparison, not a number.
 *
 * `unattributed` and `notes` are drawn whether or not they are interesting. A
 * report that hides its own residual reads cleaner and is worth less: the
 * owner is about to make decisions on these figures and needs to know when
 * they do not add up.
 */

interface MarginBreakdown {
  period: string | null;
  revenue: string;
  tax: string;
  cost_of_goods: string;
  gross_profit: string;
  margin_pct: string | null;
  rate_spread: string;
  wastage_charged: string;
  making_charges: string;
  stone_margin: string;
  uncosted_metal: string;
  ratti_discount: string;
  cash_discount: string;
  round_off: string;
  making_cost: string;
  unattributed: string;
  invoices: number;
  lines: number;
  notes: string[];
}

interface MarginReport {
  date_from: string | null;
  date_to: string | null;
  currency: Currency;
  total: MarginBreakdown;
  by_month: MarginBreakdown[];
  excluded_invoices: number;
}

/** The four levers that earn, in the order a jeweller thinks about them. */
const EARNED = [
  {
    key: "rate_spread",
    label: "Rate spread",
    bar: "bg-emerald-500",
    chip: "bg-emerald-500",
    why: "Metal sold above what it was costed at",
  },
  {
    key: "wastage_charged",
    label: "Wastage charged",
    bar: "bg-sky-500",
    chip: "bg-sky-500",
    why: "Grams billed beyond what the piece holds",
  },
  {
    key: "making_charges",
    label: "Making charges",
    bar: "bg-brand-500",
    chip: "bg-brand-500",
    why: "Labour billed to the customer",
  },
  {
    key: "stone_margin",
    label: "Stone margin",
    bar: "bg-violet-500",
    chip: "bg-violet-500",
    why: "Stones billed less what they cost",
  },
  {
    // Deliberately amber, not green. It sits among the earners because that is
    // arithmetically where it falls, but it is not money the shop made — it is
    // metal sold with nothing booked against it, and the colour should stop the
    // reader counting it as margin.
    key: "uncosted_metal",
    label: "Uncosted metal",
    bar: "bg-amber-500",
    chip: "bg-amber-500",
    why: "Sold with no recorded cost — bookkeeping owed, not margin earned",
  },
] as const;

const GIVEN = [
  {
    key: "ratti_discount",
    label: "Ratti discount",
    bar: "bg-red-400",
    why: "Grams knocked off the billable weight",
  },
  {
    key: "cash_discount",
    label: "Cash discount",
    bar: "bg-red-400",
    why: "Line and document discounts, incl. weight discount",
  },
  { key: "round_off", label: "Round-off", bar: "bg-red-300", why: "Rounded away at the counter" },
  {
    key: "making_cost",
    label: "Making cost",
    bar: "bg-amber-500",
    why: "What the workers were paid for the pieces sold",
  },
] as const;

export function MarginReportPage() {
  const range = useDateRange();
  // Currency takes effect immediately rather than waiting on Apply: it is a
  // two-item select, so there is no half-finished state to protect against.
  const [currency, setCurrency] = useState<Currency>("PKR");
  const [report, setReport] = useState<Loadable<MarginReport>>(blank());

  const params = { ...dateParams(range.applied), currency };

  useEffect(() => {
    fetchInto<MarginReport>("/reports/margin", setReport, {
      ...dateParams(range.applied),
      currency,
    });
  }, [range.applied, currency]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-xl text-sm text-slate-500">
          Profit split by the lever that produced it. Two shops with the same
          bottom line can be running in opposite directions — one earning on
          labour with the metal flat, the other living on a rate spread that
          closes the moment the market turns.
        </p>
        <RangeToolbar
          range={range}
          extra={
            <SelectField
              label="Currency"
              value={currency}
              options={[
                { value: "PKR", label: "PKR (₨)" },
                { value: "USD", label: "USD ($)" },
              ]}
              onChange={(e) => setCurrency(e.target.value as Currency)}
            />
          }
        >
          <ExportCsvButton
            url="/reports/margin"
            params={params}
            filename={`margin_${range.applied.from}_${range.applied.to}.csv`}
          />
        </RangeToolbar>
      </div>

      <ReportContents state={report}>
        {(d) => (
          <div className="space-y-4">
            <Headline breakdown={d.total} currency={d.currency} />
            <Levers breakdown={d.total} currency={d.currency} />
            <Reconciliation breakdown={d.total} currency={d.currency} />
            <Notes notes={d.total.notes} />
            <MonthlySeries months={d.by_month} currency={d.currency} />
          </div>
        )}
      </ReportContents>
    </div>
  );
}

function Headline({
  breakdown: b,
  currency,
}: {
  breakdown: MarginBreakdown;
  currency: Currency;
}) {
  const profit = num(b.gross_profit);
  return (
    <section className="card">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Gross profit</div>
          <div
            className={`mt-1 text-4xl font-semibold tabular-nums sm:text-5xl ${
              profit < 0 ? "text-red-600" : "text-emerald-700"
            }`}
          >
            {fmtMoney(b.gross_profit, currency)}
          </div>
          <div className="mt-1 text-sm text-slate-500">
            {b.margin_pct === null ? "no revenue to measure against" : `${b.margin_pct}% of revenue`}{" "}
            · {b.invoices} invoice{b.invoices === 1 ? "" : "s"} · {b.lines} line
            {b.lines === 1 ? "" : "s"}
          </div>
        </div>
        <div className="grid flex-1 gap-3 sm:grid-cols-3">
          <Stat label="Revenue" value={fmtMoney(b.revenue, currency)} hint="Excluding tax" />
          <Stat label="Cost of goods" value={fmtMoney(b.cost_of_goods, currency)} tone="warn" />
          <Stat
            label="Tax collected"
            value={fmtMoney(b.tax, currency)}
            hint="The government's money, not income"
          />
        </div>
      </div>
    </section>
  );
}

function Levers({ breakdown: b, currency }: { breakdown: MarginBreakdown; currency: Currency }) {
  const values = [...EARNED, ...GIVEN].map((l) => Math.abs(num(b[l.key])));
  const scale = Math.max(...values, 1);
  const earnedTotal = EARNED.reduce((s, l) => s + num(b[l.key]), 0);
  const givenTotal = GIVEN.reduce((s, l) => s + num(b[l.key]), 0);

  return (
    <section className="grid gap-4 lg:grid-cols-2">
      <div className="card">
        <h3 className="text-sm font-semibold text-emerald-800">What earned it</h3>
        <p className="mb-3 text-xs text-slate-500">
          The four levers, on a scale shared with the giveaways below.
        </p>
        <div className="space-y-3">
          {EARNED.map((l) => (
            <LeverRow
              key={l.key}
              label={l.label}
              why={l.why}
              value={b[l.key]}
              currency={currency}
              max={scale}
              bar={l.bar}
            />
          ))}
        </div>
        <TotalLine label="Total earned" value={earnedTotal} currency={currency} tone="good" />
      </div>

      <div className="card">
        <h3 className="text-sm font-semibold text-red-800">What it cost and what was given back</h3>
        <p className="mb-3 text-xs text-slate-500">
          Each figure is held positive and subtracted, so the page reads as "we
          earned this and handed back that".
        </p>
        <div className="space-y-3">
          {GIVEN.map((l) => (
            <LeverRow
              key={l.key}
              label={l.label}
              why={l.why}
              value={b[l.key]}
              currency={currency}
              max={scale}
              bar={l.bar}
            />
          ))}
        </div>
        <TotalLine label="Total given away" value={givenTotal} currency={currency} tone="bad" />
      </div>
    </section>
  );
}

function LeverRow({
  label,
  why,
  value,
  currency,
  max,
  bar,
}: {
  label: string;
  why: string;
  value: string;
  currency: Currency;
  max: number;
  bar: string;
}) {
  const n = num(value);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-slate-800">{label}</span>
        <span
          className={`text-sm font-semibold tabular-nums ${
            n < 0 ? "text-red-600" : "text-slate-900"
          }`}
        >
          {fmtMoney(value, currency)}
        </span>
      </div>
      <div className="mt-1">
        {/* A negative lever is drawn in red at its own magnitude rather than
            omitted — a rate spread that has gone the wrong way is the single
            most important thing on this page. */}
        <Bar value={n} max={max} className={n < 0 ? "bg-red-500" : bar} />
      </div>
      <div className="mt-0.5 text-xs text-slate-500">
        {why}
        {n < 0 && <span className="ml-1 font-medium text-red-600">— running negative</span>}
      </div>
    </div>
  );
}

function TotalLine({
  label,
  value,
  currency,
  tone,
}: {
  label: string;
  value: number;
  currency: Currency;
  tone: "good" | "bad";
}) {
  return (
    <div className="mt-4 flex items-baseline justify-between border-t border-slate-200 pt-3">
      <span className="text-sm font-medium text-slate-600">{label}</span>
      <span
        className={`text-lg font-semibold tabular-nums ${
          tone === "good" ? "text-emerald-700" : "text-red-700"
        }`}
      >
        {fmtMoney(value, currency)}
      </span>
    </div>
  );
}

/**
 * The levers minus the giveaways against the gross profit they are supposed to
 * explain. Drawn always, not only when it fails: a reader who has never seen
 * this line reconcile has no reason to believe it when it doesn't.
 */
function Reconciliation({
  breakdown: b,
  currency,
}: {
  breakdown: MarginBreakdown;
  currency: Currency;
}) {
  const unattributed = num(b.unattributed);
  const attributed = num(b.gross_profit) - unattributed;
  // The service allows ~5 paisa of independent rounding per line before it
  // considers the residual real; the same bound decides the colour here.
  const material = Math.abs(unattributed) > 0.05 * Math.max(b.lines, 1);

  return (
    <section
      className={`card ${material ? "bg-amber-50 ring-1 ring-amber-300" : ""}`}
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 text-sm">
        <span className="text-slate-600">
          Attributed to the levers{" "}
          <b className="tabular-nums text-slate-900">{fmtMoney(attributed, currency)}</b>
          <span className="mx-2 text-slate-400">+</span>
          unattributed{" "}
          <b
            className={`tabular-nums ${material ? "text-amber-800" : "text-slate-900"}`}
          >
            {fmtMoney(b.unattributed, currency)}
          </b>
          <span className="mx-2 text-slate-400">=</span>
          gross profit{" "}
          <b className="tabular-nums text-slate-900">{fmtMoney(b.gross_profit, currency)}</b>
        </span>
        <span className={material ? "text-xs text-amber-800" : "text-xs text-slate-500"}>
          {material
            ? "The residual is larger than rounding across these lines explains."
            : "Reconciles inside rounding."}
        </span>
      </div>
    </section>
  );
}

function MonthlySeries({
  months,
  currency,
}: {
  months: MarginBreakdown[];
  currency: Currency;
}) {
  if (months.length === 0) {
    return (
      <section className="card text-sm text-slate-500">
        No issued sales in this window, so there is no monthly series to show.
      </section>
    );
  }

  const profitScale = Math.max(...months.map((m) => Math.abs(num(m.gross_profit))), 1);

  return (
    <section className="card space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-slate-700">Month by month</h3>
        <p className="text-xs text-slate-500">
          The question is never "what was the margin" but "which lever is moving".
          The mix bar is the four earning levers in proportion; a shop whose profit
          is flat while the green half swallows the rest is living on the market.
        </p>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
        {EARNED.map((l) => (
          <span key={l.key} className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-3 rounded-sm ${l.chip}`} />
            {l.label}
          </span>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="py-1">Month</th>
              <th className="py-1 text-right">Inv</th>
              <th className="py-1 text-right">Revenue</th>
              <th className="py-1 text-right">Rate spread</th>
              <th className="py-1 text-right">Wastage</th>
              <th className="py-1 text-right">Making</th>
              <th className="py-1 text-right">Stones</th>
              <th className="py-1 text-right">Given away</th>
              <th className="py-1 pl-3">Earning mix</th>
              <th className="py-1 text-right">Gross profit</th>
              <th className="py-1 text-right">Margin</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {months.map((m) => {
              const given = GIVEN.reduce((s, l) => s + num(m[l.key]), 0);
              const profit = num(m.gross_profit);
              return (
                <tr key={m.period ?? "total"} className="align-middle">
                  <td className="py-1.5 font-medium">{m.period}</td>
                  <td className="py-1.5 text-right text-slate-500">{m.invoices}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    {fmtMoney(m.revenue, currency)}
                  </td>
                  {EARNED.map((l) => (
                    <td
                      key={l.key}
                      className={`py-1.5 text-right tabular-nums ${
                        num(m[l.key]) < 0 ? "text-red-600" : ""
                      }`}
                    >
                      {fmtMoney(m[l.key], currency)}
                    </td>
                  ))}
                  <td className="py-1.5 text-right tabular-nums text-red-600">
                    {fmtMoney(given, currency)}
                  </td>
                  <td className="w-40 py-1.5 pl-3">
                    <MixBar breakdown={m} />
                    <div className="mt-1">
                      <Bar
                        value={profit}
                        max={profitScale}
                        className={profit < 0 ? "bg-red-500" : "bg-slate-400"}
                      />
                    </div>
                  </td>
                  <td
                    className={`py-1.5 text-right font-semibold tabular-nums ${
                      profit < 0 ? "text-red-600" : "text-emerald-700"
                    }`}
                  >
                    {fmtMoney(m.gross_profit, currency)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{pct(m.margin_pct)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {months.some((m) => m.notes.length > 0) && (
        <div className="space-y-2">
          {months
            .filter((m) => m.notes.length > 0)
            .map((m) => (
              <div key={m.period ?? "total"}>
                <div className="text-xs font-semibold uppercase text-slate-500">{m.period}</div>
                <Notes notes={m.notes} />
              </div>
            ))}
        </div>
      )}
    </section>
  );
}

/**
 * The four earning levers as one stacked bar. Only positive parts are stacked —
 * a negative lever has no width to give, and the numeric column beside it
 * already carries the sign in red.
 */
function MixBar({ breakdown }: { breakdown: MarginBreakdown }) {
  const parts = EARNED.map((l) => ({ ...l, value: Math.max(0, num(breakdown[l.key])) }));
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (total <= 0) {
    return <div className="h-2 w-full rounded-full bg-slate-100" />;
  }
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-slate-100">
      {parts.map((p) => (
        <div
          key={p.key}
          className={p.chip}
          style={{ width: `${(p.value / total) * 100}%` }}
          title={`${p.label} ${((p.value / total) * 100).toFixed(0)}%`}
        />
      ))}
    </div>
  );
}

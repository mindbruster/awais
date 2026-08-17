import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SelectField } from "@/components/Field";
import { Currency, fmtMoney, fmtWeight } from "@/lib/money";
import {
  Bar,
  ExportCsvButton,
  Loadable,
  Notes,
  RangeToolbar,
  ReportContents,
  Stat,
  blank,
  dateParams,
  fetchInto,
  num,
  pct,
  useDateRange,
} from "@/pages/ReportsPage";

/**
 * Customers — biggest first, and then the ranking that actually matters.
 *
 * The shop asked for "customers from top spend to low spend" and "profit
 * margin from each customer" as two lines on a list. They are one table, and
 * putting them side by side is the entire value of the screen: the two orders
 * disagree, and where they disagree is the finding.
 *
 * A customer who buys heavy plain gold spends enormously at a few percent. A
 * customer buying stone-set pieces spends less and leaves more behind. Ranked
 * by spend the first looks like the shop's best relationship; ranked by margin
 * he is often third or fourth. So **Sort by** defaults to spend — that is what
 * was asked for and what people expect to see — and switching it to margin is
 * one click, with both figures on every row either way. Neither ordering is
 * hidden behind the other.
 *
 * `uncosted_lines` is surfaced per row rather than only in the total. Margin on
 * a row built from typed-in lines with no product behind them is overstated by
 * however much those lines cost, and the customer it happens to is exactly the
 * one somebody is about to make a decision about.
 */

interface CustomerRow {
  customer_id: number;
  customer_name: string;
  currency: Currency;
  invoices: number;
  revenue: string;
  cost_of_goods: string;
  gross_margin: string;
  margin_pct: string | null;
  gold_weight_g: string;
  stone_weight_ct: string;
  uncosted_lines: number;
}

interface CustomerReport {
  date_from: string | null;
  date_to: string | null;
  rows: CustomerRow[];
  customers: number;
  revenue: string;
  gross_margin: string;
}

type SortKey = "revenue" | "margin";

export function CustomerReportPage() {
  const range = useDateRange();
  const [currency, setCurrency] = useState<Currency>("PKR");
  const [sort, setSort] = useState<SortKey>("revenue");
  const [state, setState] = useState<Loadable<CustomerReport>>(blank);

  const params = { ...dateParams(range.applied) };

  useEffect(() => {
    fetchInto<CustomerReport>("/reports/customers", setState, params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range.applied.from, range.applied.to]);

  return (
    <div className="space-y-4">
      <RangeToolbar
        range={range}
        extra={
          <>
            {/* One currency at a time. Rupees and dollars do not add, and a
                mixed ranking would sort on a number that means nothing. */}
            <SelectField
              label="Currency"
              options={[
                { value: "PKR", label: "PKR" },
                { value: "USD", label: "USD" },
              ]}
              value={currency}
              onChange={(e) => setCurrency(e.target.value as Currency)}
            />
            <SelectField
              label="Sort by"
              options={[
                { value: "revenue", label: "Spend" },
                { value: "margin", label: "Margin kept" },
              ]}
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
            />
          </>
        }
      >
        <ExportCsvButton url="/reports/customers" params={params} filename="customers.csv" />
      </RangeToolbar>

      <ReportContents state={state}>
        {(d) => {
          const rows = d.rows
            .filter((r) => r.currency === currency)
            .sort((a, b) =>
              sort === "revenue"
                ? num(b.revenue) - num(a.revenue)
                : num(b.gross_margin) - num(a.gross_margin),
            );

          if (rows.length === 0)
            return (
              <p className="text-sm text-slate-500">
                No {currency} sales in this period.
              </p>
            );

          const top = Math.max(...rows.map((r) => Math.abs(num(r.revenue))), 1);
          const revenue = rows.reduce((t, r) => t + num(r.revenue), 0);
          const margin = rows.reduce((t, r) => t + num(r.gross_margin), 0);
          const uncosted = rows.reduce((t, r) => t + r.uncosted_lines, 0);

          // The blunt version of the point the table makes: how much of the
          // shop's margin a handful of names account for. Reported against
          // margin rather than spend because that is the half that pays wages.
          const byMargin = [...rows].sort((a, b) => num(b.gross_margin) - num(a.gross_margin));
          const topFive = byMargin.slice(0, 5).reduce((t, r) => t + num(r.gross_margin), 0);
          const share = margin > 0 ? (topFive / margin) * 100 : null;

          return (
            <div className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <Stat label="Customers" value={String(rows.length)} />
                <Stat label={`Spend (${currency})`} value={fmtMoney(revenue)} />
                <Stat
                  label="Margin kept"
                  value={fmtMoney(margin)}
                  hint={revenue > 0 ? `${((margin / revenue) * 100).toFixed(1)}% overall` : undefined}
                  tone={margin >= 0 ? "good" : "bad"}
                />
                <Stat
                  label="Top 5 share of margin"
                  value={share === null ? "—" : `${share.toFixed(0)}%`}
                  hint={
                    share !== null && share > 60
                      ? "Concentrated — losing one of these names hurts"
                      : "Spread across the book"
                  }
                  tone={share !== null && share > 60 ? "warn" : "plain"}
                />
              </div>

              <div className="card overflow-x-auto p-0">
                <table className="w-full min-w-[52rem] text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-3">#</th>
                      <th className="px-4 py-3">Customer</th>
                      <th className="px-4 py-3 text-right">Bills</th>
                      <th className="px-4 py-3 text-right">Spend</th>
                      <th className="px-4 py-3 text-right">Margin</th>
                      <th className="px-4 py-3 text-right">Margin %</th>
                      <th className="px-4 py-3 text-right">Gold</th>
                      <th className="px-4 py-3 text-right">Stones</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {rows.map((r, i) => (
                      <tr key={r.customer_id} className="hover:bg-slate-50">
                        <td className="px-4 py-3 text-xs text-slate-400">{i + 1}</td>
                        <td className="px-4 py-3">
                          <Link
                            to={`/customers/${r.customer_id}`}
                            className="font-medium text-brand-700 hover:underline"
                          >
                            {r.customer_name}
                          </Link>
                          <Bar
                            value={Math.abs(num(r.revenue))}
                            max={top}
                            className="mt-1 bg-brand-400"
                          />
                          {r.uncosted_lines > 0 && (
                            <span
                              className="mt-1 block text-[11px] text-amber-700"
                              title="Lines with no product behind them contribute revenue but no cost, so this row's margin is overstated."
                            >
                              {r.uncosted_lines} line{r.uncosted_lines === 1 ? "" : "s"} uncosted
                              — margin flattered
                            </span>
                          )}
                        </td>
                        <td className="num px-4 py-3 text-right">{r.invoices}</td>
                        <td className="num px-4 py-3 text-right">{fmtMoney(r.revenue)}</td>
                        <td
                          className={`num px-4 py-3 text-right ${
                            num(r.gross_margin) >= 0 ? "text-emerald-700" : "text-red-600"
                          }`}
                        >
                          {fmtMoney(r.gross_margin)}
                        </td>
                        <td className="num px-4 py-3 text-right">{pct(r.margin_pct)}</td>
                        <td className="num px-4 py-3 text-right text-slate-600">
                          {num(r.gold_weight_g) > 0 ? `${fmtWeight(r.gold_weight_g)} g` : "—"}
                        </td>
                        <td className="num px-4 py-3 text-right text-slate-600">
                          {num(r.stone_weight_ct) > 0 ? `${fmtWeight(r.stone_weight_ct)} ct` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <Notes
                notes={[
                  sort === "revenue"
                    ? "Ranked by spend. Switch to margin above — the order changes, and where it changes is worth knowing: a heavy plain-gold buyer outspends a stone buyer and leaves less behind."
                    : "Ranked by what the shop kept. A name that climbs several places coming from the spend ranking is a better customer than the totals suggest.",
                  ...(uncosted > 0
                    ? [
                        `${uncosted} invoice line${uncosted === 1 ? "" : "s"} in this period carry no product, so no cost could be attributed to them. Those rows' margins are overstated by whatever they cost, and the rows carrying them are flagged.`,
                      ]
                    : []),
                  "Cost is the same figure the Margin report uses, so the two reports cannot disagree about what a sale cost.",
                ]}
              />
            </div>
          );
        }}
      </ReportContents>
    </div>
  );
}

import { ReactNode, useEffect, useState } from "react";
import { fmtMoney, fmtWeight } from "@/lib/money";
import {
  Bar,
  EmptyRow,
  ExportCsvButton,
  Loadable,
  RangeToolbar,
  ReportContents,
  Stat,
  blank,
  daysBetween,
  fetchInto,
  num,
  pct,
  today,
  useDateRange,
} from "@/pages/ReportsPage";

/**
 * Workers — who is worth keeping.
 *
 * Two different kinds of figure sit on each row and the split matters. The
 * workshop columns are for the window; the last two — metal held and cash
 * payable — are positions read off the ledger as it stands right now. An owner
 * deciding about a worker needs both halves on one line, so they are shown
 * together and labelled apart.
 *
 * Ranked by excess by default, because excess is the grams the shop is
 * actually out of pocket for. Raw wastage just ranks whoever handles the most
 * metal, which is usually the best worker in the shop.
 */

interface WorkerRow {
  worker_id: number | null;
  worker_name: string;
  department: string | null;
  legs: number;
  gold_issued_g: string;
  gold_received_g: string;
  wastage_allowed_g: string;
  wastage_actual_g: string;
  wastage_excess_g: string;
  wastage_pct_of_issued: string;
  labour_earned: string;
  gold_balance_fine_g: string;
  cash_payable: string;
}

interface WorkerReport {
  days: number;
  period_from: string;
  period_to: string;
  rows: WorkerRow[];
  legs: number;
  gold_issued_g: string;
  wastage_actual_g: string;
  wastage_excess_g: string;
  wastage_pct_of_issued: string;
  labour_earned: string;
}

type SortKey =
  | "worker_name"
  | "legs"
  | "gold_issued_g"
  | "wastage_actual_g"
  | "wastage_excess_g"
  | "wastage_pct_of_issued"
  | "labour_earned"
  | "gold_balance_fine_g"
  | "cash_payable";

export function WorkerReportPage() {
  const range = useDateRange({ from: trailing(90) });
  const [report, setReport] = useState<Loadable<WorkerReport>>(blank());
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
    key: "wastage_excess_g",
    desc: true,
  });

  // The endpoint measures a trailing window in days, so only the opening date
  // reaches it. Rather than pretend otherwise, the closing date is converted
  // too and any gap to today is called out below the table.
  const days = daysBetween(range.applied.from, today());
  const params = { days: String(days) };

  useEffect(() => {
    fetchInto<WorkerReport>("/reports/worker-performance", setReport, {
      days: String(daysBetween(range.applied.from, today())),
    });
  }, [range.applied]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-xl text-sm text-slate-500">
          Wastage against what each worker was allowed, and what he is holding of
          yours right now. Only received legs count — metal still out on an open
          leg has not been lost, it is owed.
        </p>
        <RangeToolbar range={range}>
          <ExportCsvButton
            url="/reports/worker-performance"
            params={params}
            filename={`worker-performance_${days}d.csv`}
          />
        </RangeToolbar>
      </div>

      <ReportContents state={report}>
        {(d) => {
          const rows = sortRows(d.rows, sort);
          const excessScale = Math.max(...d.rows.map((r) => num(r.wastage_excess_g)), 0.0001);
          const stale = range.applied.to !== today();

          return (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <Stat
                  label="Legs received"
                  value={String(d.legs)}
                  hint={`${d.period_from} → ${d.period_to}`}
                />
                <Stat label="Metal issued" value={`${fmtWeight(d.gold_issued_g)} g`} />
                <Stat
                  label="Wastage"
                  value={`${fmtWeight(d.wastage_actual_g)} g`}
                  hint={`${pct(d.wastage_pct_of_issued)} of issued`}
                  tone="warn"
                />
                <Stat
                  label="Past the allowance"
                  value={`${fmtWeight(d.wastage_excess_g)} g`}
                  hint="Charged back to worker gold accounts"
                  tone={num(d.wastage_excess_g) > 0 ? "bad" : "good"}
                />
                <Stat label="Labour earned" value={fmtMoney(d.labour_earned)} />
              </div>

              {stale && (
                <p className="rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-600">
                  This report measures a window ending today, so the closing date is
                  not applied — you are looking at the {d.days} days from{" "}
                  <b>{d.period_from}</b> to <b>{d.period_to}</b>.
                </p>
              )}

              <section className="card">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs uppercase text-slate-500">
                      <tr>
                        <Th sort={sort} setSort={setSort} k="worker_name" align="left">
                          Worker
                        </Th>
                        <th className="py-1">Department</th>
                        <Th sort={sort} setSort={setSort} k="legs">
                          Legs
                        </Th>
                        <Th sort={sort} setSort={setSort} k="gold_issued_g">
                          Issued (g)
                        </Th>
                        <th className="py-1 text-right">Returned (g)</th>
                        <th className="py-1 text-right">Allowed (g)</th>
                        <Th sort={sort} setSort={setSort} k="wastage_actual_g">
                          Wastage (g)
                        </Th>
                        <Th sort={sort} setSort={setSort} k="wastage_pct_of_issued">
                          Wastage %
                        </Th>
                        <Th sort={sort} setSort={setSort} k="wastage_excess_g">
                          Excess (g)
                        </Th>
                        <Th sort={sort} setSort={setSort} k="labour_earned">
                          Labour
                        </Th>
                        <Th sort={sort} setSort={setSort} k="gold_balance_fine_g">
                          Metal held (g)
                        </Th>
                        <Th sort={sort} setSort={setSort} k="cash_payable">
                          Owed to him
                        </Th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {rows.length === 0 && (
                        <EmptyRow colSpan={12}>
                          Nothing came back off the bench in this window.
                        </EmptyRow>
                      )}
                      {rows.map((r) => {
                        const excess = num(r.wastage_excess_g);
                        const held = num(r.gold_balance_fine_g);
                        return (
                          <tr key={r.worker_id ?? "unassigned"}>
                            <td className="py-1.5 font-medium">{r.worker_name}</td>
                            <td className="py-1.5 text-slate-500">{r.department ?? "—"}</td>
                            <td className="py-1.5 text-right">{r.legs}</td>
                            <td className="py-1.5 text-right tabular-nums">
                              {fmtWeight(r.gold_issued_g)}
                            </td>
                            <td className="py-1.5 text-right tabular-nums">
                              {fmtWeight(r.gold_received_g)}
                            </td>
                            <td className="py-1.5 text-right tabular-nums text-slate-500">
                              {fmtWeight(r.wastage_allowed_g)}
                            </td>
                            <td className="py-1.5 text-right tabular-nums">
                              {fmtWeight(r.wastage_actual_g)}
                            </td>
                            <td className="py-1.5 text-right font-semibold tabular-nums">
                              {pct(r.wastage_pct_of_issued)}
                            </td>
                            <td className="w-32 py-1.5 pl-3 text-right">
                              <div
                                className={`tabular-nums ${
                                  excess > 0 ? "font-semibold text-red-600" : "text-slate-500"
                                }`}
                              >
                                {fmtWeight(r.wastage_excess_g)}
                              </div>
                              <div className="mt-1">
                                <Bar value={excess} max={excessScale} className="bg-red-400" />
                              </div>
                            </td>
                            <td className="py-1.5 text-right tabular-nums">
                              {fmtMoney(r.labour_earned)}
                            </td>
                            <td
                              className={`py-1.5 text-right tabular-nums ${
                                held > 0 ? "font-semibold text-amber-700" : "text-slate-500"
                              }`}
                            >
                              {fmtWeight(r.gold_balance_fine_g)}
                            </td>
                            <td className="py-1.5 text-right tabular-nums text-slate-700">
                              {fmtMoney(r.cash_payable)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <p className="mt-3 text-xs text-slate-500">
                  <b>Metal held</b> and <b>Owed to him</b> are today's ledger balances,
                  not window figures: what he still has of yours, and what you still owe
                  him. A worker with metal held and nothing received in the window has
                  work outstanding, not settled.
                </p>
              </section>
            </div>
          );
        }}
      </ReportContents>
    </div>
  );
}

/** A date `n` days back, for the default trailing window. */
function trailing(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  const pad = (x: number) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function sortRows(rows: WorkerRow[], sort: { key: SortKey; desc: boolean }): WorkerRow[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    if (sort.key === "worker_name") {
      return a.worker_name.localeCompare(b.worker_name) * (sort.desc ? -1 : 1);
    }
    const delta = num(a[sort.key]) - num(b[sort.key]);
    return (sort.desc ? -delta : delta) || a.worker_name.localeCompare(b.worker_name);
  });
  return copy;
}

function Th({
  k,
  sort,
  setSort,
  align = "right",
  children,
}: {
  k: SortKey;
  sort: { key: SortKey; desc: boolean };
  setSort: (s: { key: SortKey; desc: boolean }) => void;
  align?: "left" | "right";
  children: ReactNode;
}) {
  const active = sort.key === k;
  return (
    <th className={`py-1 ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        type="button"
        // Re-clicking the active column flips it; a new column starts on the
        // ordering the reader almost certainly wants — biggest first.
        onClick={() => setSort({ key: k, desc: active ? !sort.desc : k !== "worker_name" })}
        className={`uppercase ${active ? "text-slate-900" : "hover:text-slate-700"}`}
      >
        {children}
        <span className={active ? "ml-1" : "ml-1 opacity-0"} aria-hidden>
          {sort.desc ? "▼" : "▲"}
        </span>
      </button>
    </th>
  );
}

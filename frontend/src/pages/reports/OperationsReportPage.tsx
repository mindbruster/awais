import { useEffect, useState } from "react";
import { fmtMoney, fmtWeight } from "@/lib/money";
import {
  Bar,
  EmptyRow,
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
 * Operations — what the floor produced, over one date range.
 *
 * Three questions that are always asked together and answered from three
 * different places: which stage cost what and held the work longest, which
 * kinds of piece are worth making, and where the metal went. One range control
 * drives all three, because comparing them over different windows is how a
 * shop talks itself into the wrong decision.
 *
 * Each section exports separately: they are three different tables and one
 * combined CSV would be a spreadsheet nobody could pivot.
 */

interface DepartmentRow {
  department_id: number;
  department: string;
  code: string | null;
  legs_completed: number;
  gold_in_g: string;
  gold_out_g: string;
  wastage_allowed_g: string;
  wastage_actual_g: string;
  wastage_excess_g: string;
  wastage_pct_of_issued: string;
  labour_cost: string;
  avg_days_held: string | null;
}

interface DepartmentReport {
  rows: DepartmentRow[];
  legs_completed: number;
  gold_in_g: string;
  gold_out_g: string;
  wastage_actual_g: string;
  wastage_excess_g: string;
  labour_cost: string;
}

interface ItemRow {
  item_id: number;
  item_name: string;
  abbreviation: string;
  designs_started: number;
  designs_stocked: number;
  gold_consumed_g: string;
  pieces_sold: number;
  revenue: string;
  cost_of_goods: string;
  gross_margin: string;
  margin_pct: string | null;
}

interface ItemReport {
  rows: ItemRow[];
  designs_started: number;
  designs_stocked: number;
  pieces_sold: number;
  revenue: string;
  gross_margin: string;
}

interface GoldMovementReport {
  bought_old_gold_g: string;
  bought_old_gold_purchases: number;
  received_from_workers_g: string;
  issued_to_workers_g: string;
  wastage_g: string;
  excess_charged_to_workers_g: string;
  consumed_into_pieces_g: string;
  sold_g: string;
  closing_gold_in_hand_g: string;
  closing_with_workers_g: string;
  closing_finished_goods_g: string;
  closing_total_g: string;
  notes: string[];
}

export function OperationsReportPage() {
  const range = useDateRange();
  const [depts, setDepts] = useState<Loadable<DepartmentReport>>(blank());
  const [items, setItems] = useState<Loadable<ItemReport>>(blank());
  const [gold, setGold] = useState<Loadable<GoldMovementReport>>(blank());

  const params = dateParams(range.applied);

  useEffect(() => {
    const p = dateParams(range.applied);
    fetchInto<DepartmentReport>("/reports/department-throughput", setDepts, p);
    fetchInto<ItemReport>("/reports/item-performance", setItems, p);
    fetchInto<GoldMovementReport>("/reports/gold-movement", setGold, p);
  }, [range.applied]);

  const stamp = `${range.applied.from}_${range.applied.to}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-xl text-sm text-slate-500">
          Every figure below is over the same window, so the sections can be read
          against one another.
        </p>
        <RangeToolbar range={range} />
      </div>

      {/* ---------------------------------------------------------------- */}
      <section className="card space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Department throughput</h2>
            <p className="text-xs text-slate-500">
              Days held is the column that finds the bottleneck. A stage losing 2% is
              a costing question; a stage sitting on every piece for nine days is a
              delivery-date question, and the shop normally hears about that one from
              the customer.
            </p>
          </div>
          <ExportCsvButton
            url="/reports/department-throughput"
            params={params}
            filename={`department-throughput_${stamp}.csv`}
          />
        </div>
        <ReportContents state={depts}>
          {(d) => {
            const daysScale = Math.max(...d.rows.map((r) => num(r.avg_days_held)), 1);
            return (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                  <Stat label="Legs completed" value={String(d.legs_completed)} />
                  <Stat label="Metal handed out" value={`${fmtWeight(d.gold_in_g)} g`} />
                  <Stat label="Metal handed back" value={`${fmtWeight(d.gold_out_g)} g`} />
                  <Stat
                    label="Wastage"
                    value={`${fmtWeight(d.wastage_actual_g)} g`}
                    hint={`${fmtWeight(d.wastage_excess_g)} g past the allowance`}
                    tone="warn"
                  />
                  <Stat label="Labour cost" value={fmtMoney(d.labour_cost)} />
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs uppercase text-slate-500">
                      <tr>
                        <th className="py-1">Department</th>
                        <th className="py-1 text-right">Legs</th>
                        <th className="py-1 text-right">In (g)</th>
                        <th className="py-1 text-right">Out (g)</th>
                        <th className="py-1 text-right">Allowed (g)</th>
                        <th className="py-1 text-right">Wastage (g)</th>
                        <th className="py-1 text-right">Wastage %</th>
                        <th className="py-1 text-right">Excess (g)</th>
                        <th className="py-1 text-right">Labour</th>
                        <th className="py-1 pl-3">Days held</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {d.rows.length === 0 && (
                        <EmptyRow colSpan={10}>No legs completed in this window.</EmptyRow>
                      )}
                      {d.rows.map((r) => (
                        <tr key={r.department_id}>
                          <td className="py-1.5">
                            <span className="font-medium">{r.department}</span>
                            {r.code && (
                              <span className="ml-1.5 font-mono text-xs text-slate-400">
                                {r.code}
                              </span>
                            )}
                          </td>
                          <td className="py-1.5 text-right">{r.legs_completed}</td>
                          <td className="py-1.5 text-right tabular-nums">
                            {fmtWeight(r.gold_in_g)}
                          </td>
                          <td className="py-1.5 text-right tabular-nums">
                            {fmtWeight(r.gold_out_g)}
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
                          <td
                            className={`py-1.5 text-right tabular-nums ${
                              num(r.wastage_excess_g) > 0 ? "text-red-600" : "text-slate-500"
                            }`}
                          >
                            {fmtWeight(r.wastage_excess_g)}
                          </td>
                          <td className="py-1.5 text-right tabular-nums">
                            {fmtMoney(r.labour_cost)}
                          </td>
                          <td className="w-32 py-1.5 pl-3">
                            <div className="text-right tabular-nums">
                              {r.avg_days_held === null ? "—" : `${r.avg_days_held} d`}
                            </div>
                            <div className="mt-1">
                              <Bar
                                value={num(r.avg_days_held)}
                                max={daysScale}
                                className="bg-sky-500"
                              />
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            );
          }}
        </ReportContents>
      </section>

      {/* ---------------------------------------------------------------- */}
      <section className="card space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Item performance</h2>
            <p className="text-xs text-slate-500">
              Rows are the item master, because that is the unit production is decided
              in. Items with nothing sold are still listed — an item with designs
              started and none sold is exactly what you are looking for.
            </p>
          </div>
          <ExportCsvButton
            url="/reports/item-performance"
            params={params}
            filename={`item-performance_${stamp}.csv`}
          />
        </div>
        <ReportContents state={items}>
          {(d) => {
            const marginScale = Math.max(...d.rows.map((r) => Math.abs(num(r.gross_margin))), 1);
            return (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                  <Stat label="Designs started" value={String(d.designs_started)} />
                  <Stat label="Designs stocked" value={String(d.designs_stocked)} />
                  <Stat label="Pieces sold" value={String(d.pieces_sold)} />
                  <Stat label="Revenue" value={fmtMoney(d.revenue)} />
                  <Stat label="Gross margin" value={fmtMoney(d.gross_margin)} tone="good" />
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs uppercase text-slate-500">
                      <tr>
                        <th className="py-1">Item</th>
                        <th className="py-1 text-right">Started</th>
                        <th className="py-1 text-right">Stocked</th>
                        <th className="py-1 text-right">Gold in (g)</th>
                        <th className="py-1 text-right">Sold</th>
                        <th className="py-1 text-right">Revenue</th>
                        <th className="py-1 text-right">Cost</th>
                        <th className="py-1 pl-3">Gross margin</th>
                        <th className="py-1 text-right">Margin %</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {d.rows.length === 0 && (
                        <EmptyRow colSpan={9}>No items on the master yet.</EmptyRow>
                      )}
                      {d.rows.map((r) => {
                        const gm = num(r.gross_margin);
                        return (
                          <tr key={r.item_id}>
                            <td className="py-1.5">
                              <span className="font-medium">{r.item_name}</span>
                              <span className="ml-1.5 font-mono text-xs text-slate-400">
                                {r.abbreviation}
                              </span>
                            </td>
                            <td className="py-1.5 text-right">{r.designs_started}</td>
                            <td className="py-1.5 text-right">{r.designs_stocked}</td>
                            <td className="py-1.5 text-right tabular-nums">
                              {fmtWeight(r.gold_consumed_g)}
                            </td>
                            <td className="py-1.5 text-right">{r.pieces_sold}</td>
                            <td className="py-1.5 text-right tabular-nums">
                              {fmtMoney(r.revenue)}
                            </td>
                            <td className="py-1.5 text-right tabular-nums text-amber-700">
                              {fmtMoney(r.cost_of_goods)}
                            </td>
                            <td className="w-40 py-1.5 pl-3">
                              <div
                                className={`text-right font-semibold tabular-nums ${
                                  gm < 0 ? "text-red-600" : "text-emerald-700"
                                }`}
                              >
                                {fmtMoney(r.gross_margin)}
                              </div>
                              <div className="mt-1">
                                <Bar
                                  value={gm}
                                  max={marginScale}
                                  className={gm < 0 ? "bg-red-500" : "bg-emerald-500"}
                                />
                              </div>
                            </td>
                            <td className="py-1.5 text-right tabular-nums">
                              {pct(r.margin_pct)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            );
          }}
        </ReportContents>
      </section>

      {/* ---------------------------------------------------------------- */}
      <section className="card space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Gold movement</h2>
            <p className="text-xs text-slate-500">
              Fine (24k-equivalent) grams throughout. The flows are counted off the
              business records — only those know <i>why</i> metal moved; the closing
              position comes off the journal, which can always explain itself.
            </p>
          </div>
          <ExportCsvButton
            url="/reports/gold-movement"
            params={params}
            filename={`gold-movement_${stamp}.csv`}
          />
        </div>
        <ReportContents state={gold}>
          {(d) => {
            const flows = [
              num(d.bought_old_gold_g),
              num(d.received_from_workers_g),
              num(d.issued_to_workers_g),
              num(d.wastage_g),
              num(d.consumed_into_pieces_g),
              num(d.sold_g),
            ];
            const scale = Math.max(...flows.map(Math.abs), 1);
            return (
              <>
                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    <h3 className="mb-2 text-xs font-semibold uppercase text-emerald-700">
                      Came in
                    </h3>
                    <div className="space-y-3">
                      <Flow
                        label="Bought as old gold"
                        value={d.bought_old_gold_g}
                        note={`${d.bought_old_gold_purchases} purchase${
                          d.bought_old_gold_purchases === 1 ? "" : "s"
                        }`}
                        max={scale}
                        bar="bg-emerald-500"
                      />
                      <Flow
                        label="Returned by workers"
                        value={d.received_from_workers_g}
                        note="Handed back off received legs"
                        max={scale}
                        bar="bg-emerald-400"
                      />
                    </div>
                  </div>

                  <div>
                    <h3 className="mb-2 text-xs font-semibold uppercase text-red-700">Went out</h3>
                    <div className="space-y-3">
                      <Flow
                        label="Issued to workers"
                        value={d.issued_to_workers_g}
                        note="Out on the bench"
                        max={scale}
                        bar="bg-amber-500"
                      />
                      <Flow
                        label="Burned off"
                        value={d.wastage_g}
                        note={`${fmtWeight(
                          d.excess_charged_to_workers_g,
                        )} g of it charged back to the workers`}
                        max={scale}
                        bar="bg-red-400"
                      />
                      <Flow
                        label="Stocked into pieces"
                        value={d.consumed_into_pieces_g}
                        note="Stopped being loose stock"
                        max={scale}
                        bar="bg-sky-500"
                      />
                      <Flow
                        label="Sold"
                        value={d.sold_g}
                        note="Left the shop with a customer"
                        max={scale}
                        bar="bg-violet-500"
                      />
                    </div>
                  </div>
                </div>

                <div className="grid gap-3 border-t border-slate-200 pt-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Stat
                    label="In hand"
                    value={`${fmtWeight(d.closing_gold_in_hand_g)} g`}
                    hint="In the safe"
                  />
                  <Stat
                    label="With workers"
                    value={`${fmtWeight(d.closing_with_workers_g)} g`}
                    hint="Issued and not back"
                    tone="warn"
                  />
                  <Stat
                    label="In finished goods"
                    value={`${fmtWeight(d.closing_finished_goods_g)} g`}
                    hint="Stocked, unsold"
                    tone={num(d.closing_finished_goods_g) < 0 ? "bad" : "plain"}
                  />
                  <Stat
                    label="Total"
                    value={`${fmtWeight(d.closing_total_g)} g`}
                    hint="At the closing date"
                    tone="brand"
                  />
                </div>

                <Notes notes={d.notes} />
              </>
            );
          }}
        </ReportContents>
      </section>
    </div>
  );
}

function Flow({
  label,
  value,
  note,
  max,
  bar,
}: {
  label: string;
  value: string;
  note: string;
  max: number;
  bar: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-slate-800">{label}</span>
        <span className="text-sm font-semibold tabular-nums text-slate-900">
          {fmtWeight(value)} g
        </span>
      </div>
      <div className="mt-1">
        <Bar value={num(value)} max={max} className={bar} />
      </div>
      <div className="mt-0.5 text-xs text-slate-500">{note}</div>
    </div>
  );
}

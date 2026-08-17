/**
 * One salesman or broker, in full.
 *
 * The list screen could say who exists and what they were asked to hit. It
 * could not say whether any of it happened — because until now nothing in the
 * system credited a bill to anybody, so every seller target read 0% forever.
 *
 * The page is laid out as the four questions an owner actually asks, in the
 * order they are asked:
 *
 *   1. Did he sell?          revenue, bills, average, largest
 *   2. Did he sell *well*?   margin, and the discount it implies
 *   3. Did the money come?   collected against outstanding
 *   4. Against what target?  the periods, with the calendar beside them
 *
 * Two of those are easy to conflate and are deliberately kept apart. **Sales
 * are not collections**: a salesman who writes large bills nobody pays is not
 * a good salesman, and one blended figure is exactly what hides it. **Revenue
 * is not margin**: hitting a money target by discounting is a way of missing,
 * and the two sit side by side so it cannot be read as a win.
 *
 * Commission is shown as an estimate and labelled as one. Nothing in this
 * system posts a commission, so presenting it as fact would put a liability on
 * screen that is in nobody's books.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Seller {
  id: number;
  name: string;
  kind: "salesman" | "broker";
  phone: string | null;
  cnic: string | null;
  commission_pct: string;
  is_active: boolean;
  notes: string | null;
}

interface CustomerRow {
  customer_id: number;
  customer_name: string;
  invoices: number;
  revenue: string;
  gross_margin: string;
  last_sale_at: string | null;
}

interface InvoiceRow {
  invoice_id: number;
  invoice_no: string;
  issued_at: string | null;
  customer_id: number;
  customer_name: string | null;
  currency: string;
  total: string;
  paid: string;
  balance_due: string;
  status: string;
  gold_weight_g: string;
  stone_weight_ct: string;
}

interface Target {
  id: number;
  label: string | null;
  period_start: string;
  period_end: string;
  target_amount: string | null;
  target_weight_g: string | null;
  actual_amount: string;
  actual_weight_g: string;
  invoices: number;
  amount_pct: string | null;
  weight_pct: string | null;
  period_elapsed_pct: string | null;
}

interface Performance {
  seller: Seller;
  invoices: number;
  revenue: string;
  cost_of_goods: string;
  gross_margin: string;
  margin_pct: string | null;
  uncosted_lines: number;
  collected: string;
  outstanding: string;
  gold_weight_g: string;
  stone_weight_ct: string;
  average_bill: string;
  largest_bill: string;
  first_sale_at: string | null;
  last_sale_at: string | null;
  commission_pct: string;
  commission_estimate: string;
  customers: CustomerRow[];
  recent_invoices: InvoiceRow[];
  targets: Target[];
}

const n = (v: string | null) => Number(v ?? 0) || 0;
const day = (iso: string | null) => (iso ? iso.slice(0, 10) : "—");

export function SellerDetailPage() {
  const { id } = useParams();
  const [data, setData] = useState<Performance | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    api
      .get<Performance>(`/sales/sellers/${id}/performance`, { params })
      .then((r) => setData(r.data))
      .catch((e) => setError(apiError(e, "Could not load this seller")))
      .finally(() => setLoading(false));
  }, [id, from, to]);

  useEffect(load, [load]);

  if (loading && !data) return <div className="card text-sm text-slate-500">Loading…</div>;
  if (error) return <div className="card text-sm text-red-600">{error}</div>;
  if (!data) return null;

  const s = data.seller;
  const sold = n(data.revenue) + n(data.outstanding) > 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/sales" className="text-xs text-brand-700 hover:underline">
            ← Salesmen &amp; brokers
          </Link>
          <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold text-slate-900">
            {s.name}
            {/* Chipped, never blended into a total: a salesman carries the
                shop's stock and a broker holds nothing, so they settle on
                different terms. */}
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
                s.kind === "broker"
                  ? "bg-violet-50 text-violet-700 ring-violet-200"
                  : "bg-sky-50 text-sky-700 ring-sky-200"
              }`}
            >
              {s.kind}
            </span>
            {!s.is_active && <span className="chip-dead">inactive</span>}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {[s.phone, s.cnic && `CNIC ${s.cnic}`].filter(Boolean).join(" · ") ||
              "No contact details on file"}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
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
        </div>
      </div>

      {!sold ? (
        <EmptyState title="No bills are credited to this person yet">
          A sale is credited on the invoice, under <strong>Sold by</strong>. Until a bill
          names them, everything here — and every target they have been set — stays at
          zero.
        </EmptyState>
      ) : (
        <>
          {/* 1 — did he sell? */}
          <section>
            <h2 className="eyebrow">What was sold</h2>
            <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Revenue" value={fmtMoney(data.revenue)} hint="net of tax" />
              <Stat label="Bills" value={String(data.invoices)} />
              <Stat label="Average bill" value={fmtMoney(data.average_bill)} />
              <Stat label="Largest" value={fmtMoney(data.largest_bill)} />
            </div>
          </section>

          {/* 2 — did he sell well? */}
          <section>
            <h2 className="eyebrow">What it earned</h2>
            <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Cost of goods" value={fmtMoney(data.cost_of_goods)} />
              <Stat
                label="Gross margin"
                value={fmtMoney(data.gross_margin)}
                hint={data.margin_pct !== null ? `${Number(data.margin_pct).toFixed(1)}%` : undefined}
                tone={n(data.gross_margin) >= 0 ? "good" : "bad"}
              />
              <Stat label="Gold sold" value={`${Number(data.gold_weight_g).toFixed(3)} g`} />
              <Stat
                label="Stones sold"
                value={`${Number(data.stone_weight_ct).toFixed(2)} ct`}
              />
            </div>
            {data.uncosted_lines > 0 && (
              <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-900">
                {data.uncosted_lines} line{data.uncosted_lines === 1 ? "" : "s"} on these bills
                carry no product, so no cost could be attributed to them. The margin above is
                overstated by whatever they cost, and is firm only to the extent this number is
                small.
              </p>
            )}
          </section>

          {/* 3 — did the money arrive? */}
          <section>
            <h2 className="eyebrow">What came in</h2>
            <div className="mt-2 grid gap-3 sm:grid-cols-3">
              <Stat label="Collected" value={fmtMoney(data.collected)} tone="good" />
              <Stat
                label="Still outstanding"
                value={fmtMoney(data.outstanding)}
                tone={n(data.outstanding) > 0 ? "warn" : "plain"}
              />
              <Stat
                label={`Commission at ${Number(data.commission_pct)}%`}
                value={fmtMoney(data.commission_estimate)}
                hint="estimate — nothing posts this"
              />
            </div>
            <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
              Collections are held apart from sales on purpose. Someone who writes large bills
              nobody pays is not selling well, and a single figure covering both is exactly
              what hides that. The commission is worked out on revenue, not on what has been
              collected — check which basis was agreed before paying it.
            </p>
          </section>

          {/* 4 — against what target? */}
          {data.targets.length > 0 && (
            <section>
              <h2 className="eyebrow">Targets</h2>
              <div className="mt-2 grid gap-3 lg:grid-cols-2">
                {data.targets.map((t) => (
                  <TargetCard key={t.id} t={t} />
                ))}
              </div>
            </section>
          )}

          {data.customers.length > 0 && (
            <section>
              <h2 className="eyebrow">Who they sell to</h2>
              <div className="card mt-2 overflow-x-auto p-0">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Customer</th>
                      <th className="px-4 py-3 text-right">Bills</th>
                      <th className="px-4 py-3 text-right">Revenue</th>
                      <th className="px-4 py-3 text-right">Margin</th>
                      <th className="px-4 py-3">Last sale</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.customers.map((c) => (
                      <tr key={c.customer_id} className="hover:bg-slate-50">
                        <td className="px-4 py-3">
                          <Link
                            to={`/customers/${c.customer_id}`}
                            className="font-medium text-brand-700 hover:underline"
                          >
                            {c.customer_name}
                          </Link>
                        </td>
                        <td className="num px-4 py-3 text-right">{c.invoices}</td>
                        <td className="num px-4 py-3 text-right">{fmtMoney(c.revenue)}</td>
                        <td
                          className={`num px-4 py-3 text-right ${
                            n(c.gross_margin) >= 0 ? "text-emerald-700" : "text-red-600"
                          }`}
                        >
                          {fmtMoney(c.gross_margin)}
                        </td>
                        <td className="num px-4 py-3 text-xs text-slate-500">
                          {day(c.last_sale_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {data.recent_invoices.length > 0 && (
            <section>
              <h2 className="eyebrow">Bills assigned</h2>
              <div className="card mt-2 overflow-x-auto p-0">
                <table className="w-full min-w-[46rem] text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Invoice</th>
                      <th className="px-4 py-3">Customer</th>
                      <th className="px-4 py-3">Issued</th>
                      <th className="px-4 py-3 text-right">Total</th>
                      <th className="px-4 py-3 text-right">Paid</th>
                      <th className="px-4 py-3 text-right">Due</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.recent_invoices.map((i) => (
                      <tr key={i.invoice_id} className="hover:bg-slate-50">
                        <td className="px-4 py-3">
                          <Link
                            to={`/invoices/${i.invoice_id}`}
                            className="font-mono text-xs text-brand-700 hover:underline"
                          >
                            {i.invoice_no}
                          </Link>
                          <span className="ml-2 text-[11px] text-slate-400">{i.status}</span>
                        </td>
                        <td className="px-4 py-3">{i.customer_name ?? "—"}</td>
                        <td className="num px-4 py-3 text-xs text-slate-500">
                          {day(i.issued_at)}
                        </td>
                        <td className="num px-4 py-3 text-right">
                          {fmtMoney(i.total, i.currency as never)}
                        </td>
                        <td className="num px-4 py-3 text-right text-slate-600">
                          {n(i.paid) ? fmtMoney(i.paid, i.currency as never) : "—"}
                        </td>
                        <td
                          className={`num px-4 py-3 text-right ${
                            n(i.balance_due) > 0 ? "font-medium text-amber-700" : "text-slate-400"
                          }`}
                        >
                          {n(i.balance_due) > 0
                            ? fmtMoney(i.balance_due, i.currency as never)
                            : "settled"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}

      {s.notes && (
        <div className="card">
          <p className="eyebrow">Notes</p>
          <p className="mt-1 whitespace-pre-line text-sm text-slate-700">{s.notes}</p>
        </div>
      )}
    </div>
  );
}

/**
 * One target, with the calendar beside it.
 *
 * `% elapsed` is the whole point of the card: 60% of target is excellent on day
 * three and a problem on day thirty, and without the calendar the same number
 * gets read two different ways in one month. Only the halves that were set are
 * drawn — a target with no weight shows no weight bar rather than a zero one.
 */
function TargetCard({ t }: { t: Target }) {
  const elapsed = t.period_elapsed_pct === null ? null : Number(t.period_elapsed_pct);
  return (
    <div className="card">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-semibold text-slate-900">
          {t.label ?? `${t.period_start} → ${t.period_end}`}
        </p>
        {elapsed !== null && (
          <span className="text-xs text-slate-500">{elapsed.toFixed(0)}% elapsed</span>
        )}
      </div>
      <p className="mt-0.5 text-xs text-slate-400">
        {t.period_start} → {t.period_end} · {t.invoices} bill{t.invoices === 1 ? "" : "s"}
      </p>
      {t.target_amount && (
        <Progress
          label="Money"
          actual={fmtMoney(t.actual_amount)}
          target={fmtMoney(t.target_amount)}
          pct={t.amount_pct === null ? null : Number(t.amount_pct)}
          elapsed={elapsed}
        />
      )}
      {t.target_weight_g && (
        <Progress
          label="Weight"
          actual={`${Number(t.actual_weight_g).toFixed(3)} g`}
          target={`${Number(t.target_weight_g).toFixed(3)} g`}
          pct={t.weight_pct === null ? null : Number(t.weight_pct)}
          elapsed={elapsed}
        />
      )}
    </div>
  );
}

function Progress({
  label,
  actual,
  target,
  pct,
  elapsed,
}: {
  label: string;
  actual: string;
  target: string;
  pct: number | null;
  elapsed: number | null;
}) {
  const p = pct ?? 0;
  // Amber against the *calendar*, not against the target. Being at 40% is only
  // a problem if more than 40% of the period has gone.
  const behind = elapsed !== null && p < elapsed;
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className="num text-slate-700">
          {actual} <span className="text-slate-400">of {target}</span>
        </span>
      </div>
      <div className="relative mt-1 h-2 rounded-full bg-slate-200">
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${
            behind ? "bg-amber-400" : "bg-emerald-500"
          }`}
          style={{ width: `${Math.min(p, 100)}%` }}
        />
        {elapsed !== null && (
          <div
            className="absolute inset-y-0 w-px bg-slate-500"
            style={{ left: `${Math.min(elapsed, 100)}%` }}
            title={`${elapsed.toFixed(0)}% of the period has gone`}
          />
        )}
      </div>
      <p className="mt-0.5 text-[11px] text-slate-500">
        {p.toFixed(0)}% achieved
        {elapsed !== null && (behind ? " — behind the calendar" : " — ahead of the calendar")}
      </p>
    </div>
  );
}

const TONE = {
  plain: "bg-slate-50 text-slate-900 ring-slate-200",
  good: "bg-emerald-50 text-emerald-900 ring-emerald-200",
  bad: "bg-red-50 text-red-900 ring-red-200",
  warn: "bg-amber-50 text-amber-900 ring-amber-200",
};

function Stat({
  label,
  value,
  hint,
  tone = "plain",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: keyof typeof TONE;
}) {
  return (
    <div className={`rounded-lg px-3 py-2 ring-1 ${TONE[tone]}`}>
      <div className="text-xs uppercase opacity-70">{label}</div>
      <div className="num mt-0.5 text-lg font-semibold">{value}</div>
      {hint && <div className="mt-0.5 text-xs opacity-70">{hint}</div>}
    </div>
  );
}

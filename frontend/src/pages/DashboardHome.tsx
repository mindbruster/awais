import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { SetupChecklist } from "@/components/SetupChecklist";
import { AxisLabels, BarChart, ChartCard, FlowChart, LineChart } from "@/components/charts";
import { api } from "@/api/client";
import { fmtMoney } from "@/lib/money";
import { useAuthStore } from "@/store/auth";

/**
 * The opening screen, in the order a jeweller actually asks:
 *
 *   1. What is true right now — the rate, the cash, the metal, today's takings.
 *   2. What needs doing about it.
 *   3. What the last few weeks looked like.
 *   4. Where everything lives.
 *
 * The worry list sits above the charts deliberately. A shop does not open the
 * software to admire a trend; it opens it to find out which memo is overdue and
 * who is still holding metal. Charts answer a question nobody asked first.
 */
interface Today {
  gold_rate_per_g: string | null;
  gold_rate_date: string | null;
  gold_rate_is_stale: boolean;
  cash_in_hand: string;
  gold_in_hand_g: string;
  gold_with_workers_g: string;
  customer_receivable: string;
  supplier_payable: string;
  sold_today_count: number;
  sold_today_value: string;
}

interface Day {
  day: string;
  sales_value: string;
  sales_count: number;
  gold_in_g: string;
  gold_out_g: string;
  gold_rate_per_g: string | null;
}

interface Alert {
  key: string;
  label: string;
  detail: string | null;
  count: number;
  tone: "bad" | "warn" | "info";
  to: string;
}

interface Dashboard {
  as_of: string;
  days: number;
  today: Today;
  series: Day[];
  alerts: Alert[];
}

const GROUPS = [
  {
    title: "On the floor",
    tiles: [
      { label: "Designs", to: "/designs", hint: "Maker → stone fixer → lacker, and who holds it" },
      { label: "Products", to: "/products", hint: "Finished pieces: catalogue, serials, images" },
      { label: "Workers", to: "/vendors", hint: "The three stages and the people who work them" },
    ],
  },
  {
    title: "Buying and stock",
    tiles: [
      { label: "Gold purchases", to: "/purchasing/gold", hint: "Bullion bought in from a dealer" },
      { label: "Old gold", to: "/purchasing/old-gold", hint: "Metal bought back over the counter" },
      { label: "Stone purchases", to: "/purchasing/stones", hint: "Supplier bills, by graded lot" },
      { label: "Inventory", to: "/inventory", hint: "Raw metal, stones and finished stock" },
    ],
  },
  {
    title: "Selling",
    tiles: [
      { label: "Invoices", to: "/invoices", hint: "Sales, on-approval and payments" },
      { label: "Customers", to: "/customers", hint: "Buyers, balances and statements" },
      { label: "Gold rates", to: "/gold-rates", hint: "Today's rate, and the dollar" },
    ],
  },
  {
    title: "What it came to",
    tiles: [
      { label: "Reports", to: "/reports", hint: "Margin, wastage and what the floor produced" },
      { label: "Insights", to: "/insights", hint: "Where the metal and the margin are going" },
      { label: "Position", to: "/ledger/position", hint: "Cash, metal, and who owes whom" },
    ],
  },
];

const TONE: Record<string, string> = {
  bad: "border-red-200 bg-red-50 text-red-800",
  warn: "border-amber-200 bg-amber-50 text-amber-900",
  info: "border-slate-200 bg-slate-50 text-slate-700",
};

const g3 = (v: string | number) => `${Number(v).toFixed(3)} g`;
const short = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`);
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
};

/** One figure, said plainly. Tabular numerals so a column of them lines up. */
function Metric({
  label,
  value,
  sub,
  tone,
  to,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "good" | "bad";
  to?: string;
}) {
  const body = (
    <>
      <div className="eyebrow">{label}</div>
      <div
        className={`num-lg mt-1 ${
          tone === "bad" ? "text-red-700" : tone === "good" ? "text-emerald-700" : "text-slate-900"
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </>
  );
  return to ? (
    <Link to={to} className="card transition hover:shadow-md">
      {body}
    </Link>
  ) : (
    <div className="card">{body}</div>
  );
}

export function DashboardHome() {
  const user = useAuthStore((s) => s.user);
  const [data, setData] = useState<Dashboard | null>(null);
  const [days, setDays] = useState(30);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    api
      .get<Dashboard>("/dashboard", { params: { days } })
      .then((r) => setData(r.data))
      // A user without the sales-report permission gets the tiles and nothing
      // else, rather than an error where the shop's cash position would be.
      .catch(() => setDenied(true));
  }, [days]);

  const t = data?.today;
  const series = data?.series ?? [];
  const salesTotal = series.reduce((s, d) => s + Number(d.sales_value), 0);
  const inTotal = series.reduce((s, d) => s + Number(d.gold_in_g), 0);
  const outTotal = series.reduce((s, d) => s + Number(d.gold_out_g), 0);
  const labelled = series.map((d) => ({ label: short(d.day) }));

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            Welcome, {user?.full_name}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Metal in, work on it, sold, counted.
          </p>
        </div>
        {data && (
          <div className="flex gap-1">
            {[14, 30, 90].map((n) => (
              <button
                key={n}
                onClick={() => setDays(n)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                  days === n
                    ? "bg-brand-600 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {n} days
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Sits at the top because on day one it is the only thing that matters,
          and removes itself entirely once the shop can trade. */}
      <SetupChecklist />

      {t && (
        <>
          {/* --- what is true right now --- */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <Metric
              label="Gold rate"
              value={t.gold_rate_per_g ? fmtMoney(t.gold_rate_per_g) : "not set"}
              sub={
                t.gold_rate_per_g
                  ? t.gold_rate_is_stale
                    ? `stale — from ${t.gold_rate_date}`
                    : "per fine gram, today"
                  : "metal cannot be issued"
              }
              tone={t.gold_rate_is_stale || !t.gold_rate_per_g ? "bad" : undefined}
              to="/gold-rates"
            />
            <Metric
              label="Sold today"
              value={fmtMoney(t.sold_today_value)}
              sub={`${t.sold_today_count} bill(s)`}
              to="/invoices"
            />
            <Metric
              label="Cash in hand"
              value={fmtMoney(t.cash_in_hand)}
              tone={Number(t.cash_in_hand) < 0 ? "bad" : undefined}
              to="/ledger/position"
            />
            <Metric
              label="Gold in the safe"
              value={g3(t.gold_in_hand_g)}
              sub={`${g3(t.gold_with_workers_g)} out with workers`}
              to="/inventory"
            />
            <Metric
              label="Owed to you"
              value={fmtMoney(t.customer_receivable)}
              sub={
                Number(t.supplier_payable) > 0
                  ? `${fmtMoney(t.supplier_payable)} owed by you`
                  : undefined
              }
              to="/customers"
            />
          </div>

          {/* --- what needs doing --- */}
          {data.alerts.length > 0 && (
            <section>
              <h2 className="eyebrow">Needs attention</h2>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                {data.alerts.map((a) => (
                  <Link
                    key={a.key}
                    to={a.to}
                    className={`block rounded-lg border px-4 py-3 transition hover:shadow-sm ${
                      TONE[a.tone] ?? TONE.info
                    }`}
                  >
                    <div className="text-sm font-semibold">{a.label}</div>
                    {a.detail && <div className="mt-0.5 text-xs opacity-80">{a.detail}</div>}
                  </Link>
                ))}
              </div>
            </section>
          )}

          {/* --- the shape of the period --- */}
          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard
              title={`Takings · last ${data.days} days`}
              figure={fmtMoney(salesTotal)}
              note="Dollar bills converted at the rate snapshotted on them."
            >
              <BarChart
                data={series.map((d) => ({ label: short(d.day), value: Number(d.sales_value) }))}
              />
              <AxisLabels data={labelled} />
            </ChartCard>

            <ChartCard
              title="Gold rate"
              figure={t.gold_rate_per_g ? fmtMoney(t.gold_rate_per_g) : "—"}
              note="Per fine gram. Carried forward across days nobody set one."
            >
              <LineChart
                data={series.map((d) => ({
                  label: short(d.day),
                  value: d.gold_rate_per_g === null ? null : Number(d.gold_rate_per_g),
                }))}
              />
              <AxisLabels data={labelled} />
            </ChartCard>

            <ChartCard
              title="Metal in and out of the safe"
              figure={`${inTotal.toFixed(1)} in · ${outTotal.toFixed(1)} out`}
              note="Fine grams. Above the line arrived, below it went out to a worker or into a piece."
            >
              <FlowChart
                data={series.map((d) => ({
                  label: short(d.day),
                  up: Number(d.gold_in_g),
                  down: Number(d.gold_out_g),
                }))}
              />
              <AxisLabels data={labelled} />
            </ChartCard>

            <ChartCard
              title="Bills raised"
              figure={String(series.reduce((s, d) => s + d.sales_count, 0))}
              note="How busy the counter was, regardless of what each bill came to."
            >
              <BarChart
                data={series.map((d) => ({ label: short(d.day), value: d.sales_count }))}
              />
              <AxisLabels data={labelled} />
            </ChartCard>
          </div>
        </>
      )}

      {denied && (
        <p className="text-sm text-slate-500">
          Your role does not include the sales report, so the figures are hidden.
        </p>
      )}

      {/* --- where everything lives --- */}
      <div className="flex flex-col gap-8">
        {GROUPS.map((g) => (
          <section key={g.title}>
            <h2 className="eyebrow">{g.title}</h2>
            <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {g.tiles.map((t2) => (
                // Link, not a bare anchor: an <a href> tears the whole app down
                // and rebuilds it, which on a tile grid reads as the software
                // being slow.
                <Link key={t2.to} to={t2.to} className="card transition hover:shadow-md">
                  <div className="text-base font-semibold text-slate-900">{t2.label}</div>
                  <div className="mt-1 text-sm text-slate-500">{t2.hint}</div>
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

import { FormEvent, ReactNode, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { api } from "@/api/client";
import { TextField } from "@/components/Field";
import { apiError } from "@/lib/api-error";
import { Currency, fmtMoney } from "@/lib/money";

/**
 * Insights — the two watch reports, plus a question box over the books.
 *
 * Everything on this page except the answer box is computed on the server
 * without a model, so the tables render identically whether or not an API key
 * is configured. `narrative` is the only field that disappears, and a missing
 * provider is drawn as a setup note rather than an error: nothing here has
 * failed, a feature simply is not switched on.
 *
 * Pydantic serialises Decimal as a string, so every money/weight field below is
 * typed `string` and either formatted or printed verbatim — never parsed into a
 * float and re-rendered.
 */

interface WastageHalf {
  legs: number;
  issued_g: string;
  actual_g: string;
  rate_pct: string;
}

interface WastageJobRef {
  leg_id: number;
  design_no: string;
  department: string;
  received_at: string | null;
  issued_g: string;
  received_g: string;
  excess_g: string;
}

interface WastageWorkerRow {
  worker_id: number | null;
  worker_name: string;
  legs: number;
  issued_g: string;
  actual_wastage_g: string;
  allowed_g: string;
  excess_g: string;
  wastage_rate_pct: string;
  excess_to_allowance: string | null;
  earlier: WastageHalf;
  recent: WastageHalf;
  flags: string[];
  worst_legs: WastageJobRef[];
  narrative: string | null;
}

interface WastageReport {
  days: number;
  period_from: string;
  period_to: string;
  midpoint: string;
  min_legs_per_half: number;
  deterioration_ratio: string;
  shop_issued_g: string;
  shop_actual_wastage_g: string;
  shop_excess_g: string;
  shop_wastage_rate_pct: string;
  rows: WastageWorkerRow[];
  flagged_count: number;
  ai_enabled: boolean;
  ai_note: string | null;
}

interface MarginRow {
  invoice_id: number;
  invoice_no: string;
  customer_id: number;
  customer_name: string;
  currency: Currency;
  issued_at: string | null;
  revenue: string;
  cogs: string;
  profit: string;
  margin_pct: string | null;
  cogs_incomplete: boolean;
  flags: string[];
  narrative: string | null;
}

interface CustomerDiscountRow {
  customer_id: number;
  customer_name: string;
  invoices: number;
  gross: string;
  discount: string;
  discount_pct: string;
  above_shop_avg_pp: string;
  flags: string[];
  narrative: string | null;
}

interface MarginReport {
  days: number;
  period_from: string;
  period_to: string;
  floor_margin_pct: string;
  revenue: string;
  cogs: string;
  profit: string;
  margin_pct: string | null;
  shop_discount_pct: string;
  rows: MarginRow[];
  customers: CustomerDiscountRow[];
  flagged_count: number;
  ai_enabled: boolean;
  ai_note: string | null;
}

interface AskResponse {
  question: string;
  sql: string;
  model: string;
  notes: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  answer: string | null;
}

const FLAG_LABELS: Record<string, string> = {
  deteriorating: "Getting worse",
  worst_excess_ratio: "Worst overrun in shop",
  below_floor_margin: "Below floor margin",
  high_discount: "Discount above shop average",
};

type Loadable<T> = { data: T | null; forbidden: boolean; error: string | null };

const empty = <T,>(): Loadable<T> => ({ data: null, forbidden: false, error: null });

export function InsightsPage() {
  const [days, setDays] = useState("90");
  const [floor, setFloor] = useState("5");
  const [wastage, setWastage] = useState<Loadable<WastageReport>>(empty());
  const [margin, setMargin] = useState<Loadable<MarginReport>>(empty());

  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  // Held apart from askError: "not configured" is a setup note, not a failure.
  const [askSetupNote, setAskSetupNote] = useState<string | null>(null);

  const tryGet = async <T,>(
    url: string,
    setter: (s: Loadable<T>) => void,
    params: Record<string, string>,
  ) => {
    try {
      const { data } = await api.get<T>(url, { params });
      setter({ data, forbidden: false, error: null });
    } catch (err) {
      if (err instanceof AxiosError && err.response?.status === 403) {
        setter({ data: null, forbidden: true, error: null });
      } else {
        setter({ data: null, forbidden: false, error: apiError(err, "Failed to load") });
      }
    }
  };

  const load = () => {
    tryGet<WastageReport>("/insights/wastage-anomalies", setWastage, { days });
    tryGet<MarginReport>("/insights/margin-watch", setMargin, {
      days,
      floor_margin_pct: floor,
    });
  };

  useEffect(load, []); // initial

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setAskError(null);
    setAskSetupNote(null);
    try {
      const { data } = await api.post<AskResponse>("/insights/ask", { question });
      setAnswer(data);
    } catch (err) {
      setAnswer(null);
      if (err instanceof AxiosError && err.response?.status === 503) {
        setAskSetupNote(apiError(err, "AI features are not configured."));
      } else {
        setAskError(apiError(err, "Could not answer that question."));
      }
    } finally {
      setAsking(false);
    }
  };

  // Either report tells us the same thing; whichever loaded first will do.
  const aiEnabled = wastage.data?.ai_enabled ?? margin.data?.ai_enabled ?? null;
  const aiNote = wastage.data?.ai_note ?? margin.data?.ai_note ?? null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Insights</h1>
          <p className="mt-1 text-sm text-slate-500">
            Where the metal and the margin are going. The figures are computed from
            the books; a model only writes the explanations.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <TextField
            label="Window (days)"
            type="number"
            min={14}
            max={730}
            value={days}
            onChange={(e) => setDays(e.target.value)}
          />
          <TextField
            label="Floor margin %"
            type="number"
            step="0.5"
            value={floor}
            onChange={(e) => setFloor(e.target.value)}
          />
          <button className="btn-primary" onClick={load}>
            Apply
          </button>
        </div>
      </div>

      {aiEnabled === false && <NotConfigured note={aiNote} />}

      {/* ---------------------------------------------------------------- */}
      <section className="card">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-700">
            Wastage by worker — what am I losing, and to whom
          </h2>
          {wastage.data && (
            <span className="text-xs text-slate-500">
              {wastage.data.period_from} → {wastage.data.period_to} · shop rate{" "}
              <b>{wastage.data.shop_wastage_rate_pct}%</b> · {wastage.data.flagged_count} flagged
            </span>
          )}
        </div>
        <Contents state={wastage}>
          {(d) => (
            <>
              <p className="mb-3 text-xs text-slate-500">
                A worker is flagged when his rate in the recent half of the window is
                more than {d.deterioration_ratio}× his own earlier half (with at least{" "}
                {d.min_legs_per_half} finished legs each side, so a bad fortnight
                doesn't trigger it), or when his losses ran furthest past what he was
                allowed. Negative wastage means pieces came back heavier — solder and
                findings — which is normal.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-1">Worker</th>
                      <th className="py-1 text-right">Legs</th>
                      <th className="py-1 text-right">Issued (g)</th>
                      <th className="py-1 text-right">Wastage (g)</th>
                      <th className="py-1 text-right">Rate</th>
                      <th className="py-1 text-right">Earlier → recent</th>
                      <th className="py-1 text-right">Allowed (g)</th>
                      <th className="py-1 text-right">Excess (g)</th>
                      <th className="py-1 text-right">Excess ÷ allowed</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.rows.length === 0 && (
                      <tr>
                        <td className="py-2 text-slate-500" colSpan={9}>
                          No finished legs in this window.
                        </td>
                      </tr>
                    )}
                    {d.rows.map((r) => (
                      <FlaggedRows
                        key={r.worker_id ?? "unassigned"}
                        flags={r.flags}
                        narrative={r.narrative}
                        colSpan={9}
                        detail={
                          r.worst_legs.length > 0 && r.flags.length > 0 ? (
                            <span className="text-xs text-slate-500">
                              Biggest legs:{" "}
                              {r.worst_legs.map((l, i) => (
                                <span key={l.leg_id}>
                                  {i > 0 && ", "}
                                  <span className="font-mono">{l.design_no}</span> (
                                  {l.department}, {l.issued_g}g out / {l.received_g}g back)
                                </span>
                              ))}
                            </span>
                          ) : null
                        }
                      >
                        <td className="py-1.5 font-medium">{r.worker_name}</td>
                        <td className="py-1.5 text-right">{r.legs}</td>
                        <td className="py-1.5 text-right">{r.issued_g}</td>
                        <td className="py-1.5 text-right">{r.actual_wastage_g}</td>
                        <td className="py-1.5 text-right font-semibold">
                          {r.wastage_rate_pct}%
                        </td>
                        <td className="py-1.5 text-right text-xs text-slate-500">
                          {r.earlier.rate_pct}% ({r.earlier.legs}) →{" "}
                          <span
                            className={
                              r.flags.includes("deteriorating")
                                ? "font-semibold text-red-600"
                                : ""
                            }
                          >
                            {r.recent.rate_pct}% ({r.recent.legs})
                          </span>
                        </td>
                        <td className="py-1.5 text-right text-slate-500">{r.allowed_g}</td>
                        <td className="py-1.5 text-right text-red-600">{r.excess_g}</td>
                        <td className="py-1.5 text-right">
                          {r.excess_to_allowance ? `${r.excess_to_allowance}×` : "—"}
                        </td>
                      </FlaggedRows>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Contents>
      </section>

      {/* ---------------------------------------------------------------- */}
      <section className="card">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-700">
            Margin watch — thin sales and heavy discounts
          </h2>
          {margin.data && (
            <span className="text-xs text-slate-500">
              {margin.data.period_from} → {margin.data.period_to} ·{" "}
              {margin.data.flagged_count} flagged
            </span>
          )}
        </div>
        <Contents state={margin}>
          {(d) => (
            <>
              <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Stat label="Revenue" value={fmtMoney(d.revenue, "PKR")} />
                <Stat label="Cost of goods" value={fmtMoney(d.cogs, "PKR")} />
                <Stat label="Profit" value={fmtMoney(d.profit, "PKR")} />
                <Stat
                  label="Margin"
                  value={d.margin_pct === null ? "—" : `${d.margin_pct}%`}
                  hint={`Shop discount ${d.shop_discount_pct}%`}
                />
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-1">Invoice</th>
                      <th className="py-1">Customer</th>
                      <th className="py-1">Issued</th>
                      <th className="py-1 text-right">Revenue</th>
                      <th className="py-1 text-right">COGS</th>
                      <th className="py-1 text-right">Profit</th>
                      <th className="py-1 text-right">Margin</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.rows.length === 0 && (
                      <tr>
                        <td className="py-2 text-slate-500" colSpan={7}>
                          No issued or paid invoices in this window.
                        </td>
                      </tr>
                    )}
                    {d.rows.map((r) => (
                      <FlaggedRows
                        key={r.invoice_id}
                        flags={r.flags}
                        narrative={r.narrative}
                        colSpan={7}
                        detail={
                          r.cogs_incomplete ? (
                            <span className="text-xs text-amber-700">
                              Some lines have no product behind them, so this cost is a
                              floor — the real margin is lower.
                            </span>
                          ) : null
                        }
                      >
                        <td className="py-1.5 font-mono text-xs">{r.invoice_no}</td>
                        <td className="py-1.5">{r.customer_name}</td>
                        <td className="py-1.5 text-xs text-slate-500">
                          {r.issued_at ? new Date(r.issued_at).toLocaleDateString() : "—"}
                        </td>
                        <td className="py-1.5 text-right">
                          {fmtMoney(r.revenue, r.currency)}
                        </td>
                        <td className="py-1.5 text-right text-amber-700">
                          {fmtMoney(r.cogs, r.currency)}
                        </td>
                        <td className="py-1.5 text-right">
                          {fmtMoney(r.profit, r.currency)}
                        </td>
                        <td
                          className={`py-1.5 text-right font-semibold ${
                            r.flags.includes("below_floor_margin")
                              ? "text-red-600"
                              : "text-emerald-700"
                          }`}
                        >
                          {r.margin_pct === null ? "—" : `${r.margin_pct}%`}
                        </td>
                      </FlaggedRows>
                    ))}
                  </tbody>
                </table>
              </div>

              <h3 className="mb-2 mt-5 text-xs font-semibold uppercase text-slate-500">
                Discount by customer (shop average {d.shop_discount_pct}%)
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-1">Customer</th>
                      <th className="py-1 text-right">Invoices</th>
                      <th className="py-1 text-right">Gross</th>
                      <th className="py-1 text-right">Given away</th>
                      <th className="py-1 text-right">Discount</th>
                      <th className="py-1 text-right">vs shop</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.customers.length === 0 && (
                      <tr>
                        <td className="py-2 text-slate-500" colSpan={6}>
                          Nothing billed in this window.
                        </td>
                      </tr>
                    )}
                    {d.customers.map((c) => (
                      <FlaggedRows
                        key={c.customer_id}
                        flags={c.flags}
                        narrative={c.narrative}
                        colSpan={6}
                      >
                        <td className="py-1.5">{c.customer_name}</td>
                        <td className="py-1.5 text-right">{c.invoices}</td>
                        <td className="py-1.5 text-right">{fmtMoney(c.gross, "PKR")}</td>
                        <td className="py-1.5 text-right text-red-600">
                          {fmtMoney(c.discount, "PKR")}
                        </td>
                        <td className="py-1.5 text-right font-semibold">
                          {c.discount_pct}%
                        </td>
                        <td className="py-1.5 text-right text-xs text-slate-500">
                          {Number(c.above_shop_avg_pp) > 0 ? "+" : ""}
                          {c.above_shop_avg_pp} pp
                        </td>
                      </FlaggedRows>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Contents>
      </section>

      {/* ---------------------------------------------------------------- */}
      <section className="card">
        <h2 className="mb-1 text-sm font-semibold text-slate-700">Ask the books</h2>
        <p className="mb-3 text-xs text-slate-500">
          A question in English, Urdu or Roman-Urdu — "kis karigar ka nuqsan sab se
          zyada hai?". The query it runs is shown with the answer, so you can check it.
        </p>
        <form onSubmit={ask} className="flex flex-wrap items-end gap-2">
          <div className="min-w-[18rem] flex-1">
            <TextField
              label="Question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Which customer bought the most this quarter?"
            />
          </div>
          <button className="btn-primary" disabled={asking || !question.trim()}>
            {asking ? "Asking…" : "Ask"}
          </button>
        </form>

        {askSetupNote && <NotConfigured note={askSetupNote} className="mt-4" />}
        {askError && <div className="mt-4 text-sm text-red-600">{askError}</div>}

        {answer && (
          <div className="mt-4 space-y-3">
            {answer.answer && (
              <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-900 ring-1 ring-brand-200">
                {answer.answer}
              </p>
            )}
            {answer.notes && <p className="text-xs text-slate-500">{answer.notes}</p>}

            <details className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">
                Generated SQL ({answer.model})
              </summary>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-slate-700">
                {answer.sql}
              </pre>
            </details>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    {answer.columns.map((c) => (
                      <th key={c} className="py-1 pr-3">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {answer.rows.length === 0 && (
                    <tr>
                      <td
                        className="py-2 text-slate-500"
                        colSpan={Math.max(answer.columns.length, 1)}
                      >
                        No rows matched.
                      </td>
                    </tr>
                  )}
                  {answer.rows.map((row, i) => (
                    <tr key={i}>
                      {answer.columns.map((c) => (
                        <td key={c} className="py-1.5 pr-3">
                          {row[c] === null || row[c] === undefined ? "—" : String(row[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-500">
              {answer.row_count} row{answer.row_count === 1 ? "" : "s"}
              {answer.truncated && " (capped — narrow the question for the rest)"}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

/**
 * A data row plus, when it is flagged, a callout row underneath carrying the
 * flags, the model's sentence and any supporting detail. Kept as one component
 * so both tables highlight and explain a flagged row identically.
 */
function FlaggedRows({
  flags,
  narrative,
  detail,
  colSpan,
  children,
}: {
  flags: string[];
  narrative: string | null;
  detail?: ReactNode;
  colSpan: number;
  children: ReactNode;
}) {
  const flagged = flags.length > 0;
  return (
    <>
      <tr className={flagged ? "bg-amber-50/60" : undefined}>{children}</tr>
      {flagged && (
        <tr className="bg-amber-50/60">
          <td colSpan={colSpan} className="pb-2 pl-1">
            <div className="flex flex-wrap items-center gap-2">
              {flags.map((f) => (
                <span
                  key={f}
                  className="rounded-full bg-amber-200/70 px-2 py-0.5 text-xs font-medium text-amber-900"
                >
                  {FLAG_LABELS[f] ?? f}
                </span>
              ))}
              {narrative && <span className="text-sm text-slate-700">{narrative}</span>}
            </div>
            {detail && <div className="mt-1">{detail}</div>}
          </td>
        </tr>
      )}
    </>
  );
}

/** Not an error state: the numbers are all there, the prose simply is not. */
function NotConfigured({ note, className = "" }: { note: string | null; className?: string }) {
  return (
    <div className={`card bg-slate-50 text-sm text-slate-600 ring-1 ring-slate-200 ${className}`}>
      <div className="font-medium text-slate-700">AI features are not configured</div>
      <p className="mt-1">
        {note ??
          "Set AI_PROVIDER=anthropic and ANTHROPIC_API_KEY (optionally AI_MODEL) in the backend environment and restart the API."}
      </p>
      <p className="mt-1 text-xs text-slate-500">
        Environment variables:{" "}
        <code className="font-mono">AI_PROVIDER</code>,{" "}
        <code className="font-mono">ANTHROPIC_API_KEY</code>,{" "}
        <code className="font-mono">AI_MODEL</code>. Every figure on this page is
        computed without a model and keeps working either way.
      </p>
    </div>
  );
}

function Contents<T>({
  state,
  children,
}: {
  state: Loadable<T>;
  children: (d: T) => ReactNode;
}) {
  if (state.forbidden)
    return (
      <div className="text-sm text-slate-500">
        Your role doesn't have permission to view this report.
      </div>
    );
  if (state.error) return <div className="text-sm text-red-600">{state.error}</div>;
  if (!state.data) return <div className="text-sm text-slate-500">Loading…</div>;
  return <>{children(state.data)}</>;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
      <div className="text-xs uppercase text-slate-500">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-slate-900">{value}</div>
      {hint && <div className="text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

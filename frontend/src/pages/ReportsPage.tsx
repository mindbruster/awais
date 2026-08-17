import { ReactNode, useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { TextField } from "@/components/Field";
import { apiError } from "@/lib/api-error";
import { Currency, fmtMoney, fmtWeight } from "@/lib/money";
import { MarginReportPage } from "@/pages/reports/MarginReportPage";
import { CustomerReportPage } from "@/pages/reports/CustomerReportPage";
import { WorkerReportPage } from "@/pages/reports/WorkerReportPage";
import { OperationsReportPage } from "@/pages/reports/OperationsReportPage";

/**
 * Reports — one route, five views.
 *
 * The sidebar and the router are shared surfaces this section does not own, so
 * the sub-reports are tabs under `?tab=` rather than routes of their own. That
 * still leaves every report linkable ("/reports?tab=margin") without minting a
 * nav entry per report, which is what a reports section otherwise always ends
 * up doing.
 *
 * The shared kit below — date range, CSV button, load-state wrapper — lives
 * here with the hub because all four views need it. The sub-pages importing
 * back from this module is a cycle only on paper: everything they reach for is
 * a hoisted function declaration, initialised before any component body runs.
 */

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "margin", label: "Margin" },
  { key: "customers", label: "Customers" },
  { key: "workers", label: "Workers" },
  { key: "operations", label: "Operations" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab") ?? "overview";
  const tab: TabKey = TABS.some((t) => t.key === raw) ? (raw as TabKey) : "overview";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Reports</h1>
        <p className="mt-1 text-sm text-slate-500">
          Where the money came from, who is holding the metal, and what the floor
          actually produced.
        </p>
      </div>

      <nav className="flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setParams(t.key === "overview" ? {} : { tab: t.key })}
            className={`-mb-px rounded-t-lg border-b-2 px-4 py-2 text-sm font-medium transition ${
              t.key === tab
                ? "border-brand-600 text-brand-700"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "overview" && <OverviewTab />}
      {tab === "margin" && <MarginReportPage />}
      {tab === "customers" && <CustomerReportPage />}
      {tab === "workers" && <WorkerReportPage />}
      {tab === "operations" && <OperationsReportPage />}
    </div>
  );
}

/* ================================================================== */
/* Shared report kit                                                   */
/* ================================================================== */

export interface Loadable<T> {
  data: T | null;
  loading: boolean;
  forbidden: boolean;
  error: string | null;
}

export function blank<T>(): Loadable<T> {
  return { data: null, loading: true, forbidden: false, error: null };
}

/**
 * GET into a `Loadable`. A 403 is held apart from a failure: the report did
 * not break, the reader is simply not allowed to see it, and the two want very
 * different words on screen.
 */
export async function fetchInto<T>(
  url: string,
  setter: (s: Loadable<T>) => void,
  params: Record<string, string> = {},
): Promise<void> {
  setter({ data: null, loading: true, forbidden: false, error: null });
  try {
    const { data } = await api.get<T>(url, { params });
    setter({ data, loading: false, forbidden: false, error: null });
  } catch (err) {
    if (err instanceof AxiosError && err.response?.status === 403) {
      setter({ data: null, loading: false, forbidden: true, error: null });
    } else {
      setter({
        data: null,
        loading: false,
        forbidden: false,
        error: apiError(err, "Failed to load"),
      });
    }
  }
}

export interface DateRange {
  from: string;
  to: string;
}

/**
 * Draft range plus the range the tables on screen were actually built from.
 * Held apart so a half-typed date never re-queries — the reader presses Apply,
 * and until then every heading still describes what he is looking at.
 */
export function useDateRange(initial?: Partial<DateRange>) {
  const [draft, setDraft] = useState<DateRange>({
    from: initial?.from ?? monthsAgo(11),
    to: initial?.to ?? today(),
  });
  const [applied, setApplied] = useState<DateRange>(draft);
  return { draft, setDraft, applied, apply: () => setApplied(draft) };
}

export function today(): string {
  return localDate(new Date());
}

/** Start of the month `n` months back, so a monthly series arrives populated. */
export function monthsAgo(n: number): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - n);
  return localDate(d);
}

/**
 * The shop's own calendar day. `toISOString` would shift a Karachi evening back
 * to the previous date, which quietly drops a day off the front of every range.
 */
function localDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Whole days between two YYYY-MM-DD dates, floored at 1. */
export function daysBetween(from: string, to: string): number {
  const ms = Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`);
  if (Number.isNaN(ms)) return 1;
  return Math.max(1, Math.round(ms / 86_400_000));
}

/** Plain dates — what /margin, /item-performance and friends take. */
export function dateParams(r: DateRange): Record<string, string> {
  const p: Record<string, string> = {};
  if (r.from) p.date_from = r.from;
  if (r.to) p.date_to = r.to;
  return p;
}

/**
 * Plain dates under the `range_*` names, which is what /sales and /profit take.
 *
 * These two used to be sent as instants, widened here to `T23:59:59Z` so an
 * invoice issued at 18:00 on the closing date stayed inside the range. That
 * widening now happens on the server, where it belongs — every report shares
 * one window helper, so the same requested month can no longer give a
 * different answer depending on which report you opened. Sending an instant to
 * them is now rejected outright, so the only difference left from
 * `dateParams` is the parameter names.
 */
export function rangeParams(r: DateRange): Record<string, string> {
  const p: Record<string, string> = {};
  if (r.from) p.range_from = r.from;
  if (r.to) p.range_to = r.to;
  return p;
}

export function RangeToolbar({
  range,
  extra,
  children,
}: {
  range: ReturnType<typeof useDateRange>;
  /** Report-specific controls, rendered between the dates and Apply. */
  extra?: ReactNode;
  /** Export buttons, rendered after Apply. */
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end gap-2">
      <TextField
        label="From"
        type="date"
        value={range.draft.from}
        onChange={(e) => range.setDraft({ ...range.draft, from: e.target.value })}
      />
      <TextField
        label="To"
        type="date"
        value={range.draft.to}
        onChange={(e) => range.setDraft({ ...range.draft, to: e.target.value })}
      />
      {extra}
      <button className="btn-primary" onClick={range.apply}>
        Apply
      </button>
      {children}
    </div>
  );
}

/**
 * Downloads `?format=csv` from the same endpoint and with the same parameters
 * the table came from, so the spreadsheet can never disagree with the screen.
 */
export function ExportCsvButton({
  url,
  params,
  filename,
  label = "Export CSV",
}: {
  url: string;
  params: Record<string, string>;
  filename: string;
  label?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.get(url, {
        params: { ...params, format: "csv" },
        responseType: "blob",
      });
      // The endpoint names the file when it can; ours is only the fallback.
      const disposition = String(res.headers["content-disposition"] ?? "");
      const named = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition)?.[1];
      const href = URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = named ? decodeURIComponent(named) : filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    } catch (err) {
      setError(apiError(err, "Export failed"));
    } finally {
      setBusy(false);
    }
  }, [url, params, filename]);

  return (
    <div>
      <button
        className="btn-ghost ring-1 ring-slate-200"
        onClick={run}
        disabled={busy}
        type="button"
      >
        {busy ? "Exporting…" : label}
      </button>
      {error && <div className="mt-1 text-xs text-red-600">{error}</div>}
    </div>
  );
}

export function ReportContents<T>({
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

const STAT_TONE = {
  plain: "bg-slate-50 text-slate-900 ring-slate-200",
  good: "bg-emerald-50 text-emerald-900 ring-emerald-200",
  bad: "bg-red-50 text-red-900 ring-red-200",
  warn: "bg-amber-50 text-amber-900 ring-amber-200",
  brand: "bg-brand-50 text-brand-900 ring-brand-200",
};

export function Stat({
  label,
  value,
  hint,
  tone = "plain",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: keyof typeof STAT_TONE;
}) {
  return (
    <div className={`rounded-lg px-3 py-2 ring-1 ${STAT_TONE[tone]}`}>
      <div className="text-xs uppercase opacity-70">{label}</div>
      <div className="mt-0.5 text-lg font-semibold">{value}</div>
      {hint && <div className="mt-0.5 text-xs opacity-70">{hint}</div>}
    </div>
  );
}

/**
 * A proportional bar, drawn in CSS.
 *
 * Every comparison on these pages is a handful of magnitudes against one
 * another. A charting library would add more bytes to the bundle than this
 * entire section costs to render.
 */
export function Bar({
  value,
  max,
  className = "bg-emerald-500",
}: {
  value: number;
  max: number;
  className?: string;
}) {
  const width = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
      <div className={`h-full rounded-full ${className}`} style={{ width: `${width}%` }} />
    </div>
  );
}

/**
 * Findings the report raised about itself. Always drawn when present — a
 * report that swallows its own discrepancies is worse than one that admits
 * them, because the reader then trusts the wrong number.
 */
export function Notes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <ul className="space-y-1 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
      {notes.map((n, i) => (
        <li key={i} className="flex gap-2">
          <span aria-hidden>!</span>
          <span>{n}</span>
        </li>
      ))}
    </ul>
  );
}

/** Decimal-as-string straight from Pydantic; parsed only to compare or scale. */
export function num(v: string | number | null | undefined): number {
  if (v === null || v === undefined || v === "") return 0;
  const n = typeof v === "string" ? Number(v) : v;
  return Number.isNaN(n) ? 0 : n;
}

export function pct(v: string | null | undefined): string {
  return v === null || v === undefined || v === "" ? "—" : `${v}%`;
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td className="py-3 text-sm text-slate-500" colSpan={colSpan}>
        {children}
      </td>
    </tr>
  );
}

/* ================================================================== */
/* Overview tab                                                        */
/* ================================================================== */

interface StockReport {
  by_type: {
    type: string;
    items: number;
    total_quantity: number;
    total_weight_g: string;
    total_weight_ct: string;
  }[];
  items_count: number;
}

interface SalesReport {
  by_sale_type: {
    currency: Currency;
    sale_type: string;
    invoice_count: number;
    subtotal: string;
    discount: string;
    total: string;
  }[];
  by_currency: { currency: Currency; invoice_count: number; total: string }[];
  invoice_count: number;
}

interface LossReport {
  overall_karigar_loss_g: string;
  overall_polish_loss_g: string;
  by_vendor: {
    vendor_id: number | null;
    vendor_name: string | null;
    role: string;
    jobs: number;
    total_loss_g: string;
    source: string;
  }[];
  legs: number;
  overall_issued_g: string;
  overall_received_g: string;
  overall_allowed_g: string;
  overall_actual_loss_g: string;
  overall_excess_g: string;
  legacy_loss_g: string;
  notes: string[];
}

interface ProfitReport {
  rows: {
    invoice_id: number;
    invoice_no: string;
    currency: Currency;
    issued_at: string | null;
    revenue: string;
    making_cost: string;
    profit: string;
  }[];
  by_currency: {
    currency: Currency;
    revenue: string;
    making_cost: string;
    profit: string;
  }[];
}

function OverviewTab() {
  const range = useDateRange();
  const [stock, setStock] = useState<Loadable<StockReport>>(blank());
  const [sales, setSales] = useState<Loadable<SalesReport>>(blank());
  const [loss, setLoss] = useState<Loadable<LossReport>>(blank());
  const [profit, setProfit] = useState<Loadable<ProfitReport>>(blank());

  useEffect(() => {
    fetchInto<StockReport>("/reports/stock", setStock);
    fetchInto<SalesReport>("/reports/sales", setSales, rangeParams(range.applied));
    fetchInto<LossReport>("/reports/manufacturing-loss", setLoss, dateParams(range.applied));
    fetchInto<ProfitReport>("/reports/profit", setProfit, rangeParams(range.applied));
  }, [range.applied]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p className="max-w-xl text-sm text-slate-500">
          Stock on hand, what was billed, what the bench burned off, and the headline
          profit per invoice. The Margin tab pulls that profit apart into the levers
          that produced it.
        </p>
        <RangeToolbar range={range}>
          <ExportCsvButton
            url="/reports/profit"
            params={rangeParams(range.applied)}
            filename={`profit_${range.applied.from}_${range.applied.to}.csv`}
            label="Export profit CSV"
          />
        </RangeToolbar>
      </div>

      {profit.forbidden ? (
        <div className="card text-sm text-slate-500">
          Profit summary requires admin or accountant access.
        </div>
      ) : profit.data && profit.data.by_currency.length > 0 ? (
        <div className="space-y-2">
          {profit.data.by_currency.map((b) => (
            <div key={b.currency} className="grid gap-3 md:grid-cols-3">
              <Stat
                label={`Revenue (${b.currency})`}
                value={fmtMoney(b.revenue, b.currency)}
                tone="good"
              />
              <Stat
                label={`Cost of goods (${b.currency})`}
                value={fmtMoney(b.making_cost, b.currency)}
                tone="warn"
              />
              <Stat
                label={`Profit (${b.currency})`}
                value={fmtMoney(b.profit, b.currency)}
                tone="brand"
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="card text-sm text-slate-500">
          No issued sales in the selected range yet.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Stock by type</h3>
          <ReportContents state={stock}>
            {(d) => (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-1">Type</th>
                      <th className="py-1 text-right">Items</th>
                      <th className="py-1 text-right">Qty</th>
                      <th className="py-1 text-right">Gold (g)</th>
                      <th className="py-1 text-right">Stones (ct)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.by_type.length === 0 && <EmptyRow colSpan={5}>Nothing in stock.</EmptyRow>}
                    {d.by_type.map((b) => (
                      <tr key={b.type}>
                        <td className="py-1.5">{b.type}</td>
                        <td className="py-1.5 text-right">{b.items}</td>
                        <td className="py-1.5 text-right">{b.total_quantity}</td>
                        <td className="py-1.5 text-right">{fmtWeight(b.total_weight_g)}</td>
                        <td className="py-1.5 text-right">{fmtWeight(b.total_weight_ct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </ReportContents>
        </section>

        <section className="card">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">
            Sales by currency / type
          </h3>
          <ReportContents state={sales}>
            {(d) => (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-1">Currency</th>
                      <th className="py-1">Sale type</th>
                      <th className="py-1 text-right">Count</th>
                      <th className="py-1 text-right">Subtotal</th>
                      <th className="py-1 text-right">Discount</th>
                      <th className="py-1 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.by_sale_type.length === 0 && (
                      <EmptyRow colSpan={6}>No issued sales in range.</EmptyRow>
                    )}
                    {d.by_sale_type.map((b, i) => (
                      <tr key={`${b.currency}-${b.sale_type}-${i}`}>
                        <td className="py-1.5 font-mono text-xs">{b.currency}</td>
                        <td className="py-1.5">{b.sale_type}</td>
                        <td className="py-1.5 text-right">{b.invoice_count}</td>
                        <td className="py-1.5 text-right">{fmtMoney(b.subtotal, b.currency)}</td>
                        <td className="py-1.5 text-right text-red-600">
                          {fmtMoney(b.discount, b.currency)}
                        </td>
                        <td className="py-1.5 text-right font-semibold">
                          {fmtMoney(b.total, b.currency)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </ReportContents>
        </section>
      </div>

      <section className="card space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold text-slate-700">Metal lost on the bench</h3>
          <ExportCsvButton
            url="/reports/manufacturing-loss"
            params={dateParams(range.applied)}
            filename={`manufacturing-loss_${range.applied.from}_${range.applied.to}.csv`}
          />
        </div>
        <ReportContents state={loss}>
          {(d) => (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <Stat label="Legs received" value={String(d.legs)} />
                <Stat label="Issued" value={`${fmtWeight(d.overall_issued_g)} g`} />
                <Stat label="Returned" value={`${fmtWeight(d.overall_received_g)} g`} />
                <Stat
                  label="Burned off"
                  value={`${fmtWeight(d.overall_actual_loss_g)} g`}
                  hint={
                    num(d.legacy_loss_g) > 0
                      ? `${fmtWeight(d.overall_allowed_g)} g allowed · ${fmtWeight(
                          d.legacy_loss_g,
                        )} g more sits in retired records below`
                      : `${fmtWeight(d.overall_allowed_g)} g was allowed`
                  }
                  tone="warn"
                />
                <Stat
                  label="Past the allowance"
                  value={`${fmtWeight(d.overall_excess_g)} g`}
                  hint="Charged back to the workers"
                  tone={num(d.overall_excess_g) > 0 ? "bad" : "good"}
                />
              </div>

              <Notes notes={d.notes} />

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-1">Worker</th>
                      <th className="py-1">Stage</th>
                      <th className="py-1 text-right">Jobs / legs</th>
                      <th className="py-1 text-right">Loss (g)</th>
                      <th className="py-1">Source</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.by_vendor.length === 0 && (
                      <EmptyRow colSpan={5}>Nothing came back off the bench in range.</EmptyRow>
                    )}
                    {d.by_vendor.map((r, i) => (
                      <tr key={`${r.vendor_id}-${r.role}-${r.source}-${i}`}>
                        <td className="py-1.5">{r.vendor_name ?? "(unassigned)"}</td>
                        <td className="py-1.5 text-slate-500">{r.role}</td>
                        <td className="py-1.5 text-right">{r.jobs}</td>
                        <td className="py-1.5 text-right text-red-600">
                          {fmtWeight(r.total_loss_g)}
                        </td>
                        <td className="py-1.5">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs ${
                              r.source === "legacy"
                                ? "bg-slate-200 text-slate-600"
                                : "bg-emerald-100 text-emerald-800"
                            }`}
                          >
                            {r.source}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-500">
                Rows tagged <b>legacy</b> come off the retired manufacturing_jobs table.
                Nothing has been written there since the routing engine took over — see
                the Workers tab for who is losing metal now.
              </p>
            </>
          )}
        </ReportContents>
      </section>

      <section className="card">
        <h3 className="mb-3 text-sm font-semibold text-slate-700">Profit per invoice</h3>
        <ReportContents state={profit}>
          {(d) => (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-1">Invoice</th>
                    <th className="py-1">Cur</th>
                    <th className="py-1">Issued</th>
                    <th className="py-1 text-right">Revenue</th>
                    <th className="py-1 text-right">Cost</th>
                    <th className="py-1 text-right">Profit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {d.rows.length === 0 && <EmptyRow colSpan={6}>No issued sales in range.</EmptyRow>}
                  {d.rows.map((r) => (
                    <tr key={r.invoice_id}>
                      <td className="py-1.5 font-mono text-xs">{r.invoice_no}</td>
                      <td className="py-1.5 text-xs">{r.currency}</td>
                      <td className="py-1.5 text-xs text-slate-500">
                        {r.issued_at ? new Date(r.issued_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="py-1.5 text-right">{fmtMoney(r.revenue, r.currency)}</td>
                      <td className="py-1.5 text-right text-amber-700">
                        {fmtMoney(r.making_cost, r.currency)}
                      </td>
                      <td className="py-1.5 text-right font-semibold text-emerald-700">
                        {fmtMoney(r.profit, r.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ReportContents>
      </section>
    </div>
  );
}

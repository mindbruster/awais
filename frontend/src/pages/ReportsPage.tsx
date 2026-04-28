import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { api } from "@/api/client";
import { TextField } from "@/components/Field";
import { apiError } from "@/lib/api-error";

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
    sale_type: string;
    invoice_count: number;
    subtotal: string;
    discount: string;
    total: string;
  }[];
  invoice_count: number;
  grand_total: string;
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
  }[];
}

interface ProfitReport {
  rows: {
    invoice_id: number;
    invoice_no: string;
    issued_at: string | null;
    revenue: string;
    making_cost: string;
    profit: string;
  }[];
  total_revenue: string;
  total_making_cost: string;
  total_profit: string;
}

type ReportState<T> = { data: T | null; forbidden: boolean; error: string | null };

const empty = <T,>(): ReportState<T> => ({ data: null, forbidden: false, error: null });

export function ReportsPage() {
  const [stock, setStock] = useState<ReportState<StockReport>>(empty());
  const [sales, setSales] = useState<ReportState<SalesReport>>(empty());
  const [loss, setLoss] = useState<ReportState<LossReport>>(empty());
  const [profit, setProfit] = useState<ReportState<ProfitReport>>(empty());

  // Date filter (YYYY-MM-DD)
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const dateParams = () => {
    const params: Record<string, string> = {};
    if (from) params.range_from = `${from}T00:00:00Z`;
    if (to) params.range_to = `${to}T23:59:59Z`;
    return params;
  };

  const tryGet = async <T,>(
    url: string,
    setter: (s: ReportState<T>) => void,
    params: Record<string, string> = {},
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
    tryGet<StockReport>("/reports/stock", setStock);
    tryGet<LossReport>("/reports/manufacturing-loss", setLoss);
    tryGet<SalesReport>("/reports/sales", setSales, dateParams());
    tryGet<ProfitReport>("/reports/profit", setProfit, dateParams());
  };

  useEffect(load, []); // initial

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">Reports</h1>
        <div className="flex items-end gap-2">
          <TextField label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <TextField label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          <button className="btn-primary" onClick={load}>
            Apply
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <KPI
          label="Total revenue"
          value={profit.data?.total_revenue ?? (profit.forbidden ? "—" : "…")}
          accent="emerald"
          locked={profit.forbidden}
        />
        <KPI
          label="Making cost"
          value={profit.data?.total_making_cost ?? (profit.forbidden ? "—" : "…")}
          accent="amber"
          locked={profit.forbidden}
        />
        <KPI
          label="Profit"
          value={profit.data?.total_profit ?? (profit.forbidden ? "—" : "…")}
          accent="brand"
          locked={profit.forbidden}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Stock by type</h3>
          <ReportContents state={stock}>
            {(d) => (
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
                  {d.by_type.map((b) => (
                    <tr key={b.type}>
                      <td className="py-1.5">{b.type}</td>
                      <td className="py-1.5 text-right">{b.items}</td>
                      <td className="py-1.5 text-right">{b.total_quantity}</td>
                      <td className="py-1.5 text-right">{b.total_weight_g}</td>
                      <td className="py-1.5 text-right">{b.total_weight_ct}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </ReportContents>
        </section>

        <section className="card">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Sales by type</h3>
          <ReportContents state={sales}>
            {(d) => (
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-1">Sale type</th>
                    <th className="py-1 text-right">Count</th>
                    <th className="py-1 text-right">Subtotal</th>
                    <th className="py-1 text-right">Discount</th>
                    <th className="py-1 text-right">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {d.by_sale_type.length === 0 && (
                    <tr><td className="py-2 text-slate-500" colSpan={5}>No issued sales in range.</td></tr>
                  )}
                  {d.by_sale_type.map((b) => (
                    <tr key={b.sale_type}>
                      <td className="py-1.5">{b.sale_type}</td>
                      <td className="py-1.5 text-right">{b.invoice_count}</td>
                      <td className="py-1.5 text-right">{b.subtotal}</td>
                      <td className="py-1.5 text-right text-red-600">{b.discount}</td>
                      <td className="py-1.5 text-right font-semibold">{b.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </ReportContents>
        </section>

        <section className="card">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Manufacturing loss</h3>
          <ReportContents state={loss}>
            {(d) => (
              <>
                <div className="mb-3 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="text-xs text-slate-500">Karigar loss</div>
                    <div className="font-semibold text-red-600">{d.overall_karigar_loss_g} g</div>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <div className="text-xs text-slate-500">Polish loss</div>
                    <div className="font-semibold text-red-600">{d.overall_polish_loss_g} g</div>
                  </div>
                </div>
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr>
                      <th className="py-1">Vendor</th>
                      <th className="py-1">Role</th>
                      <th className="py-1 text-right">Jobs</th>
                      <th className="py-1 text-right">Loss (g)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {d.by_vendor.length === 0 && (
                      <tr><td className="py-2 text-slate-500" colSpan={4}>No completed jobs yet.</td></tr>
                    )}
                    {d.by_vendor.map((r, i) => (
                      <tr key={`${r.vendor_id}-${r.role}-${i}`}>
                        <td className="py-1.5">{r.vendor_name ?? "(unknown)"}</td>
                        <td className="py-1.5 text-slate-500">{r.role}</td>
                        <td className="py-1.5 text-right">{r.jobs}</td>
                        <td className="py-1.5 text-right text-red-600">{r.total_loss_g}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </ReportContents>
        </section>

        <section className="card">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Profit per invoice</h3>
          <ReportContents state={profit}>
            {(d) => (
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="py-1">Invoice</th>
                    <th className="py-1">Issued</th>
                    <th className="py-1 text-right">Revenue</th>
                    <th className="py-1 text-right">Cost</th>
                    <th className="py-1 text-right">Profit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {d.rows.length === 0 && (
                    <tr><td className="py-2 text-slate-500" colSpan={5}>No issued sales in range.</td></tr>
                  )}
                  {d.rows.map((r) => (
                    <tr key={r.invoice_id}>
                      <td className="py-1.5 font-mono text-xs">{r.invoice_no}</td>
                      <td className="py-1.5 text-xs text-slate-500">
                        {r.issued_at ? new Date(r.issued_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="py-1.5 text-right">{r.revenue}</td>
                      <td className="py-1.5 text-right text-amber-700">{r.making_cost}</td>
                      <td className="py-1.5 text-right font-semibold text-emerald-700">{r.profit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </ReportContents>
        </section>
      </div>
    </div>
  );
}

function ReportContents<T>({
  state,
  children,
}: {
  state: ReportState<T>;
  children: (d: T) => React.ReactNode;
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

function KPI({
  label,
  value,
  accent,
  locked,
}: {
  label: string;
  value: string;
  accent: string;
  locked?: boolean;
}) {
  const map: Record<string, string> = {
    emerald: "text-emerald-700 ring-emerald-200 bg-emerald-50",
    amber: "text-amber-800 ring-amber-200 bg-amber-50",
    brand: "text-brand-700 ring-brand-200 bg-brand-50",
  };
  return (
    <div className={`card ring-1 ${map[accent]}`}>
      <div className="text-xs uppercase opacity-70">
        {label}
        {locked && <span className="ml-1">(restricted)</span>}
      </div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

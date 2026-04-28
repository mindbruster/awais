import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";

interface Customer {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  address: string | null;
  notes: string | null;
  created_at: string;
}

interface InvoiceRow {
  id: number;
  invoice_no: string;
  sale_type: string;
  status: string;
  total: string;
  issued_at: string | null;
  created_at: string;
}

const STATUS_COLOR: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  issued: "bg-blue-100 text-blue-800",
  paid: "bg-emerald-100 text-emerald-800",
  void: "bg-red-100 text-red-700",
  returned: "bg-amber-100 text-amber-800",
};

export function CustomerDetailPage() {
  const { id } = useParams<{ id: string }>();
  const cid = Number(id);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [invoices, setInvoices] = useState<InvoiceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [c, inv] = await Promise.all([
        api.get<Customer>(`/customers/${cid}`),
        api.get<InvoiceRow[]>("/invoices", { params: { customer_id: cid, limit: 200 } }),
      ]);
      setCustomer(c.data);
      setInvoices(inv.data);
    } catch (e) {
      setError(apiError(e, "Failed to load customer"));
    }
  }, [cid]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!customer || invoices === null)
    return <div className="text-sm text-slate-500">Loading…</div>;

  const lifetime = invoices
    .filter((i) => i.status === "paid" || i.status === "issued")
    .reduce((sum, i) => sum + Number(i.total), 0);
  const paidCount = invoices.filter((i) => i.status === "paid").length;
  const outstanding = invoices
    .filter((i) => i.status === "issued")
    .reduce((sum, i) => sum + Number(i.total), 0);

  return (
    <div className="space-y-6">
      <div>
        <Link to="/customers" className="text-sm text-slate-500 hover:underline">
          ← Customers
        </Link>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">{customer.name}</h1>
        <p className="text-xs text-slate-500">
          Customer since {new Date(customer.created_at).toLocaleDateString()}
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="card lg:col-span-1">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Contact</h3>
          <dl className="space-y-2 text-sm">
            <Row label="Phone">{customer.phone ?? "—"}</Row>
            <Row label="Email">{customer.email ?? "—"}</Row>
            <Row label="Address" multiline>
              {customer.address ?? "—"}
            </Row>
            {customer.notes && (
              <Row label="Notes" multiline>
                {customer.notes}
              </Row>
            )}
          </dl>
        </section>

        <section className="lg:col-span-2 grid gap-4 sm:grid-cols-3">
          <KPI label="Lifetime spend" value={`₹${lifetime.toFixed(2)}`} accent="brand" />
          <KPI label="Paid invoices" value={String(paidCount)} accent="emerald" />
          <KPI
            label="Outstanding"
            value={`₹${outstanding.toFixed(2)}`}
            accent={outstanding > 0 ? "amber" : "slate"}
          />
        </section>
      </div>

      <section className="card overflow-hidden p-0">
        <div className="border-b border-slate-200 px-5 py-3 text-sm font-semibold text-slate-700">
          Purchase history ({invoices.length})
        </div>
        {invoices.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">No invoices yet for this customer.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Invoice #</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Issued / Created</th>
                <th className="px-4 py-3 text-right">Total</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {invoices.map((i) => (
                <tr key={i.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-xs">{i.invoice_no}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                      {i.sale_type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        STATUS_COLOR[i.status] ?? "bg-slate-100"
                      }`}
                    >
                      {i.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {i.issued_at
                      ? new Date(i.issued_at).toLocaleDateString()
                      : new Date(i.created_at).toLocaleDateString() + " (draft)"}
                  </td>
                  <td className="px-4 py-3 text-right font-semibold">{i.total}</td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/invoices/${i.id}`}
                      className="text-xs text-brand-700 hover:underline"
                    >
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Row({
  label,
  children,
  multiline,
}: {
  label: string;
  children: React.ReactNode;
  multiline?: boolean;
}) {
  return (
    <div className={multiline ? "" : "flex justify-between gap-3"}>
      <dt className="text-xs uppercase text-slate-500">{label}</dt>
      <dd className={multiline ? "mt-0.5 whitespace-pre-line" : "text-right"}>{children}</dd>
    </div>
  );
}

function KPI({ label, value, accent }: { label: string; value: string; accent: string }) {
  const map: Record<string, string> = {
    emerald: "text-emerald-700 ring-emerald-200 bg-emerald-50",
    amber: "text-amber-800 ring-amber-200 bg-amber-50",
    brand: "text-brand-700 ring-brand-200 bg-brand-50",
    slate: "text-slate-700 ring-slate-200 bg-slate-50",
  };
  return (
    <div className={`card ring-1 ${map[accent]}`}>
      <div className="text-xs uppercase opacity-70">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

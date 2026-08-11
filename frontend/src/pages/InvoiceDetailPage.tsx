import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { Currency, fmtMoney } from "@/lib/money";

interface InvoiceItem {
  id: number;
  description: string;
  quantity: number;
  gold_weight_g: string;
  gold_purity: number | null;
  gold_rate_per_g: string;
  gold_amount: string;
  stone_weight_ct: string;
  stone_rate_per_ct: string;
  stone_amount: string;
  labor_amount: string;
  line_discount: string;
  discount_ratti: string;
  ratti_base: number;
  // Server-derived (weight / base * (base - ratti)) — never recomputed here, so
  // the printed document can only ever agree with what was billed.
  billable_gold_weight_g: string;
  line_total: string;
}

interface Invoice {
  id: number;
  invoice_no: string;
  sale_type: string;
  status: string;
  customer_id: number;
  currency: Currency;
  gold_rate_per_g: string;
  subtotal: string;
  discount_amount: string;
  discount_weight_g: string;
  tax_amount: string;
  total: string;
  issued_at: string | null;
  paid_at: string | null;
  notes: string | null;
  items: InvoiceItem[];
}

interface Customer {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  address: string | null;
}

const STATUS_COLOR: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  issued: "bg-blue-100 text-blue-800",
  paid: "bg-emerald-100 text-emerald-800",
  returned: "bg-amber-100 text-amber-800",
  void: "bg-red-100 text-red-700",
};

export function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const invId = Number(id);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [voiding, setVoiding] = useState(false);
  const [issuing, setIssuing] = useState(false);
  const [sendingWa, setSendingWa] = useState(false);

  const load = useCallback(async () => {
    try {
      const inv = (await api.get<Invoice>(`/invoices/${invId}`)).data;
      setInvoice(inv);
      const c = (await api.get<Customer>(`/customers/${inv.customer_id}`)).data;
      setCustomer(c);
    } catch (e) {
      setError(apiError(e, "Failed to load invoice"));
    }
  }, [invId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!invoice) return <div className="text-sm text-slate-500">Loading…</div>;

  const action = async (path: string, msg: string) => {
    try {
      await api.post(`/invoices/${invoice.id}/${path}`);
      toast("success", msg);
      load();
    } catch (err) {
      toast("error", apiError(err, "Action failed"));
    }
  };

  const confirmVoid = async (password: string) => {
    try {
      await api.post(
        `/invoices/${invoice.id}/void`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", "Invoice voided");
      setVoiding(false);
      load();
    } catch (err) {
      toast("error", apiError(err, "Void failed"));
    }
  };

  const confirmIssue = async (password: string) => {
    try {
      await api.post(
        `/invoices/${invoice.id}/issue`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", "Invoice issued");
      setIssuing(false);
      load();
    } catch (err) {
      toast("error", apiError(err, "Issue failed"));
    }
  };

  const sendWhatsapp = async () => {
    setSendingWa(true);
    try {
      const { data } = await api.post(`/invoices/${invoice.id}/send-whatsapp`);
      toast("success", `Sent via ${data.provider}${data.message_sid ? ` (${data.message_sid})` : ""}`);
    } catch (err) {
      toast("error", apiError(err, "WhatsApp send failed"));
    } finally {
      setSendingWa(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/invoices" className="text-sm text-slate-500 hover:underline">
            ← Invoices
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">{invoice.invoice_no}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => window.print()}>
            Print
          </button>
          <button className="btn-ghost" onClick={sendWhatsapp} disabled={sendingWa || !customer?.phone}>
            {sendingWa ? "Sending…" : "Send WhatsApp"}
          </button>
          {invoice.status === "draft" && (
            <button className="btn-primary" onClick={() => setIssuing(true)}>
              Issue
            </button>
          )}
          {invoice.status === "issued" && (
            <>
              <button className="btn-primary" onClick={() => action("mark-paid", "Marked paid")}>
                Mark paid
              </button>
              <button
                className="btn inline-flex items-center justify-center rounded-lg bg-red-100 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-200"
                onClick={() => setVoiding(true)}
              >
                Void
              </button>
            </>
          )}
        </div>
      </div>

      <div className="card print-page mx-auto max-w-3xl">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-4">
          <div>
            <div className="text-2xl font-bold text-brand-700">Jewelry ERP</div>
            <div className="text-xs text-slate-500">Tax Invoice / Receipt</div>
          </div>
          <div className="text-right">
            <div className="text-sm text-slate-500">Invoice #</div>
            <div className="font-mono text-lg font-semibold">{invoice.invoice_no}</div>
            <span
              className={`mt-2 inline-block rounded-full px-2 py-0.5 text-xs ${
                STATUS_COLOR[invoice.status] ?? "bg-slate-100"
              }`}
            >
              {invoice.status}
            </span>
            <div className="mt-1 text-xs uppercase text-slate-500">{invoice.sale_type}</div>
          </div>
        </header>

        <section className="mt-4 grid grid-cols-2 gap-6 text-sm">
          <div>
            <div className="mb-1 text-xs uppercase text-slate-500">Bill to</div>
            <div className="font-semibold">{customer?.name ?? "—"}</div>
            {customer?.phone && <div>{customer.phone}</div>}
            {customer?.email && <div className="text-slate-600">{customer.email}</div>}
            {customer?.address && (
              <div className="mt-1 whitespace-pre-line text-xs text-slate-500">
                {customer.address}
              </div>
            )}
          </div>
          <div className="text-right">
            <Row label="Issued">
              {invoice.issued_at
                ? new Date(invoice.issued_at).toLocaleString()
                : "(draft — not issued)"}
            </Row>
            {invoice.paid_at && (
              <Row label="Paid">{new Date(invoice.paid_at).toLocaleString()}</Row>
            )}
            <Row label="Currency">{invoice.currency}</Row>
            <Row label="Gold rate">{fmtMoney(invoice.gold_rate_per_g, invoice.currency)} / g</Row>
          </div>
        </section>

        <table className="mt-6 w-full text-sm">
          <thead className="border-b border-slate-200 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="py-2">Description</th>
              <th className="py-2 text-right">Qty</th>
              <th className="py-2 text-right">Gold (g)</th>
              <th className="py-2 text-right">Stone (ct)</th>
              <th className="py-2 text-right">Labor</th>
              <th className="py-2 text-right">Discount</th>
              <th className="py-2 text-right">Line total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {invoice.items.map((it) => {
              const ratti = Number(it.discount_ratti) > 0;
              return (
              <tr key={it.id}>
                <td className="py-2">
                  {it.description}
                  {it.gold_purity ? (
                    <div className="text-xs text-slate-500">
                      {it.gold_purity}k @ {fmtMoney(it.gold_rate_per_g, invoice.currency)}/g · gold {fmtMoney(it.gold_amount, invoice.currency)} · stone {fmtMoney(it.stone_amount, invoice.currency)}
                    </div>
                  ) : null}
                  {/* Spelled out on the customer's copy: the gold amount above
                      is charged on less metal than the piece contains, and the
                      document has to say so on its own. */}
                  {ratti && (
                    <div className="text-xs text-amber-700">
                      Ratti discount {it.discount_ratti} / {it.ratti_base} — billed on{" "}
                      {it.billable_gold_weight_g} g of {it.gold_weight_g} g
                    </div>
                  )}
                </td>
                <td className="py-2 text-right">{it.quantity}</td>
                <td className="py-2 text-right">
                  {ratti ? (
                    <>
                      <span className="text-slate-400 line-through">{it.gold_weight_g}</span>{" "}
                      <span className="font-medium">{it.billable_gold_weight_g}</span>
                    </>
                  ) : (
                    it.gold_weight_g
                  )}
                </td>
                <td className="py-2 text-right">{it.stone_weight_ct}</td>
                <td className="py-2 text-right">{fmtMoney(it.labor_amount, invoice.currency)}</td>
                <td className="py-2 text-right text-red-600">
                  {Number(it.line_discount) > 0 ? `-${fmtMoney(it.line_discount, invoice.currency)}` : "—"}
                </td>
                <td className="py-2 text-right font-medium">{fmtMoney(it.line_total, invoice.currency)}</td>
              </tr>
              );
            })}
          </tbody>
        </table>

        <section className="mt-4 ml-auto w-full max-w-xs space-y-1 border-t border-slate-200 pt-3 text-sm">
          <Row label="Subtotal">{fmtMoney(invoice.subtotal, invoice.currency)}</Row>
          {Number(invoice.discount_amount) > 0 && (
            <Row label="Discount" negative>
              -{fmtMoney(invoice.discount_amount, invoice.currency)}
            </Row>
          )}
          {Number(invoice.discount_weight_g) > 0 && (
            <Row label={`Weight discount (${invoice.discount_weight_g}g)`} negative>
              -{fmtMoney(
                Number(invoice.discount_weight_g) * Number(invoice.gold_rate_per_g),
                invoice.currency,
              )}
            </Row>
          )}
          {Number(invoice.tax_amount) > 0 && (
            <Row label="Tax">{fmtMoney(invoice.tax_amount, invoice.currency)}</Row>
          )}
          <Row label="Total" bold>
            {fmtMoney(invoice.total, invoice.currency)}
          </Row>
        </section>

        {invoice.notes && (
          <section className="mt-6 border-t border-slate-200 pt-3 text-xs text-slate-500">
            <div className="mb-1 uppercase">Notes</div>
            <p className="whitespace-pre-line">{invoice.notes}</p>
          </section>
        )}

        <footer className="mt-6 border-t border-slate-200 pt-3 text-xs text-slate-400">
          Thank you for your business.
        </footer>
      </div>

      <PasswordConfirm
        open={voiding}
        onClose={() => setVoiding(false)}
        title={`Void ${invoice.invoice_no}?`}
        description="Voiding will reverse stock movements (for normal sales) and reset product status. Confirm with your password."
        confirmLabel="Void invoice"
        onConfirm={confirmVoid}
      />
      <PasswordConfirm
        open={issuing}
        onClose={() => setIssuing(false)}
        title={`Issue ${invoice.invoice_no}?`}
        description={
          invoice.sale_type === "on_approval"
            ? "Issuing an on-approval invoice marks linked products as on_approval (stock untouched)."
            : "Issuing a normal sale will deduct stock from inventory."
        }
        confirmLabel="Issue invoice"
        destructive={false}
        onConfirm={confirmIssue}
      />
    </div>
  );
}

function Row({
  label,
  children,
  bold,
  negative,
}: {
  label: string;
  children: React.ReactNode;
  bold?: boolean;
  negative?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className={`text-xs ${bold ? "font-semibold uppercase text-slate-700" : "text-slate-500"}`}>
        {label}
      </span>
      <span
        className={
          (bold ? "text-base font-semibold text-slate-900 " : "text-sm ") +
          (negative ? "text-red-600" : "")
        }
      >
        {children}
      </span>
    </div>
  );
}

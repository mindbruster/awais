import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextArea, TextField } from "@/components/Field";
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
  sale_wastage_pct: string;
  sale_wastage_g: string;
  // Both server-derived: charged = net + wastage, billable = charged less the
  // ratti discount. Never recomputed here, so the printed document can only
  // ever agree with what was billed.
  charged_gold_weight_g: string;
  billable_gold_weight_g: string;
  line_total: string;
  // The piece itself. `description` is typed at the counter and is often just
  // "ring"; these identify the physical object the customer is holding.
  product_id: number | null;
  product_name: string | null;
  product_serial_no: string | null;
  product_image_url: string | null;
}

interface Payment {
  id: number;
  payment_no: string;
  invoice_id: number | null;
  customer_id: number;
  method: string;
  direction: string;
  amount: string;
  gold_weight_g: string | null;
  gold_purity: number | null;
  gold_rate_per_g: string | null;
  gold_fine_g: string | null;
  bank_account_label: string | null;
  paid_at: string;
  reference: string | null;
  notes: string | null;
  entry_no: string | null;
  is_reversed: boolean;
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
  round_off: string;
  total: string;
  bill_book_no: string | null;
  issued_at: string | null;
  paid_at: string | null;
  notes: string | null;
  items: InvoiceItem[];
  // Summed from the payment rows on the server every read — never stored, so
  // it cannot drift from the money that was actually taken.
  amount_paid: string;
  balance_due: string;
  customer_balance: string;
  payments: Payment[];
}

const METHOD_LABEL: Record<string, string> = {
  cash: "Cash",
  bank: "Bank transfer",
  gold_exchange: "Gold exchange",
  advance: "Advance",
};

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
  const [takingPayment, setTakingPayment] = useState(false);
  const [reversing, setReversing] = useState<Payment | null>(null);

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

  const confirmReverse = async (password: string) => {
    if (!reversing) return;
    try {
      await api.post(
        `/payments/${reversing.id}/reverse`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${reversing.payment_no} reversed`);
      setReversing(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Reversal failed"));
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
          {(invoice.status === "issued" || invoice.status === "paid") && (
            <button className="btn-primary" onClick={() => setTakingPayment(true)}>
              Take payment
            </button>
          )}
          {invoice.status === "issued" && (
            <>
              {/* Not a flag any more: this records a cash payment for the
                  outstanding balance, and the status follows from it. */}
              <button
                className="btn-ghost"
                title="Records a cash payment for the outstanding balance"
                onClick={() => action("mark-paid", "Cash payment recorded for the balance")}
              >
                Cash in full
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

        {/* The weight maths gets a column each rather than a sentence under the
            description. A jeweller checking a bill reads down one number at a
            time — net, what was added for wastage, what the ratti discount took
            off, what was actually billed — and prose forces them to re-derive
            it. Wide by nature, so it scrolls inside its own box and never makes
            the page scroll sideways. */}
        <div className="mt-6 overflow-x-auto">
          <table className="w-full min-w-[64rem] text-sm tabular-nums">
            <thead className="border-b border-slate-200 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2 pr-3 font-medium">Piece</th>
                <th className="py-2 px-2 text-right font-medium">Qty</th>
                <th className="py-2 px-2 text-right font-medium">Purity</th>
                <th className="py-2 px-2 text-right font-medium">Net g</th>
                <th className="py-2 px-2 text-right font-medium">+ Wastage</th>
                <th className="py-2 px-2 text-right font-medium">− Ratti</th>
                <th className="py-2 px-2 text-right font-medium">Billed g</th>
                <th className="py-2 px-2 text-right font-medium">Rate/g</th>
                <th className="py-2 px-2 text-right font-medium">Gold</th>
                <th className="py-2 px-2 text-right font-medium">Stone</th>
                <th className="py-2 px-2 text-right font-medium">Making</th>
                <th className="py-2 px-2 text-right font-medium">Disc</th>
                <th className="py-2 pl-2 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 align-top">
              {invoice.items.map((it) => {
                const net = Number(it.gold_weight_g);
                const charged = Number(it.charged_gold_weight_g);
                const billable = Number(it.billable_gold_weight_g);
                // Derived by subtraction from the server's own figures rather
                // than recomputed from the percentage, so the printed document
                // can only ever agree with what was billed.
                const addedByWastage = charged - net;
                const takenByRatti = charged - billable;
                const ct = Number(it.stone_weight_ct);
                return (
                  <tr key={it.id}>
                    <td className="py-3 pr-3">
                      <div className="flex items-start gap-3">
                        {it.product_image_url ? (
                          <img
                            src={it.product_image_url}
                            alt={it.product_name ?? it.description}
                            className="h-12 w-12 flex-none rounded object-cover ring-1 ring-slate-200"
                          />
                        ) : (
                          <div
                            className="flex h-12 w-12 flex-none items-center justify-center rounded bg-slate-100 text-[10px] text-slate-400 ring-1 ring-slate-200"
                            title="No photograph on this piece"
                          >
                            no photo
                          </div>
                        )}
                        <div className="min-w-0">
                          <div className="font-medium text-slate-900">{it.description}</div>
                          {it.product_serial_no && (
                            <div className="font-mono text-xs text-slate-500">
                              {it.product_id ? (
                                <Link className="hover:underline" to={`/products/${it.product_id}`}>
                                  {it.product_serial_no}
                                </Link>
                              ) : (
                                it.product_serial_no
                              )}
                            </div>
                          )}
                          {it.product_name && it.product_name !== it.description && (
                            <div className="text-xs text-slate-500">{it.product_name}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-2 text-right">{it.quantity}</td>
                    <td className="py-3 px-2 text-right">
                      {it.gold_purity ? `${it.gold_purity}k` : "—"}
                    </td>
                    <td className="py-3 px-2 text-right">{net ? net.toFixed(3) : "—"}</td>
                    {/* Wastage is money the shop earns and the ratti discount is
                        money it gives away. Coloured against each other so the
                        customer can see both halves of the negotiation. */}
                    <td className="py-3 px-2 text-right">
                      {addedByWastage > 0 ? (
                        <span className="text-amber-700">
                          +{addedByWastage.toFixed(3)}
                          <span className="block text-[10px] text-slate-400">
                            {Number(it.sale_wastage_pct) > 0 ? `${Number(it.sale_wastage_pct)}%` : ""}
                            {Number(it.sale_wastage_g) > 0 ? ` +${Number(it.sale_wastage_g)}g` : ""}
                          </span>
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-3 px-2 text-right">
                      {takenByRatti > 0 ? (
                        <span className="text-emerald-700">
                          −{takenByRatti.toFixed(3)}
                          <span className="block text-[10px] text-slate-400">
                            {Number(it.discount_ratti)} of {it.ratti_base} ratti
                          </span>
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-3 px-2 text-right font-medium text-slate-900">
                      {billable ? billable.toFixed(3) : "—"}
                    </td>
                    <td className="py-3 px-2 text-right">
                      {Number(it.gold_rate_per_g)
                        ? fmtMoney(it.gold_rate_per_g, invoice.currency)
                        : "—"}
                    </td>
                    <td className="py-3 px-2 text-right">
                      {fmtMoney(it.gold_amount, invoice.currency)}
                    </td>
                    <td className="py-3 px-2 text-right">
                      {ct > 0 ? (
                        <>
                          {fmtMoney(it.stone_amount, invoice.currency)}
                          <span className="block text-[10px] text-slate-400">
                            {ct.toFixed(2)} ct @ {fmtMoney(it.stone_rate_per_ct, invoice.currency)}
                          </span>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-3 px-2 text-right">
                      {Number(it.labor_amount)
                        ? fmtMoney(it.labor_amount, invoice.currency)
                        : "—"}
                    </td>
                    <td className="py-3 px-2 text-right text-red-600">
                      {Number(it.line_discount) > 0
                        ? `−${fmtMoney(it.line_discount, invoice.currency)}`
                        : "—"}
                    </td>
                    <td className="py-3 pl-2 text-right font-medium text-slate-900">
                      {fmtMoney(it.line_total, invoice.currency)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

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
          {Number(invoice.round_off) !== 0 && (
            <Row label="Round off" negative={Number(invoice.round_off) > 0}>
              {Number(invoice.round_off) > 0 ? "-" : "+"}
              {fmtMoney(Math.abs(Number(invoice.round_off)), invoice.currency)}
            </Row>
          )}
          <Row label="Total" bold>
            {fmtMoney(invoice.total, invoice.currency)}
          </Row>
          {Number(invoice.amount_paid) !== 0 && (
            <>
              <Row label="Paid">-{fmtMoney(invoice.amount_paid, invoice.currency)}</Row>
              <Row label="Balance due" bold>
                {fmtMoney(invoice.balance_due, invoice.currency)}
              </Row>
            </>
          )}
        </section>

        {invoice.bill_book_no && (
          <div className="mt-3 text-xs text-slate-500">
            Bill book #{invoice.bill_book_no}
          </div>
        )}

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

      {/* Payments live outside the printed document: the customer's copy shows
          the bill, the shop's screen shows what has been settled against it. */}
      <section className="no-print card mx-auto w-full max-w-3xl">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-3">
          <div>
            <h2 className="text-sm font-semibold uppercase text-slate-700">Payments</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              Cash, transfers and old gold taken against this bill.
            </p>
          </div>
          <div className="text-right">
            <div className="text-xs uppercase text-slate-500">Balance due</div>
            <div
              className={`text-2xl font-semibold ${
                Number(invoice.balance_due) > 0 ? "text-red-600" : "text-emerald-600"
              }`}
            >
              {fmtMoney(invoice.balance_due, invoice.currency)}
            </div>
            <div className="text-xs text-slate-500">
              {fmtMoney(invoice.amount_paid, invoice.currency)} of{" "}
              {fmtMoney(invoice.total, invoice.currency)} settled
            </div>
          </div>
        </div>

        {/* An advance sitting on the account is not settlement of this bill —
            it is credit the counter can choose to apply, so it is shown rather
            than silently netted off. */}
        {Number(invoice.customer_balance) < 0 && (
          <div className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            This customer is in credit by{" "}
            {fmtMoney(Math.abs(Number(invoice.customer_balance)), invoice.currency)} across their
            account — take it as a payment here to apply it.
          </div>
        )}

        {invoice.payments.length === 0 ? (
          <p className="mt-4 text-sm text-slate-500">Nothing taken yet.</p>
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2">Payment #</th>
                <th className="py-2">Method</th>
                <th className="py-2">Taken</th>
                <th className="py-2 text-right">Amount</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {invoice.payments.map((p) => (
                <tr key={p.id} className={p.is_reversed ? "text-slate-400" : ""}>
                  <td className="py-2 font-mono text-xs">
                    {p.payment_no}
                    {p.entry_no && <div className="text-[10px] text-slate-400">{p.entry_no}</div>}
                  </td>
                  <td className="py-2">
                    {METHOD_LABEL[p.method] ?? p.method}
                    {p.method === "gold_exchange" && (
                      <div className="text-xs text-slate-500">
                        {p.gold_weight_g} g @ {p.gold_purity ?? 24}k = {p.gold_fine_g} g fine ·{" "}
                        {fmtMoney(p.gold_rate_per_g, invoice.currency)}/g fine
                      </div>
                    )}
                    {p.bank_account_label && (
                      <div className="text-xs text-slate-500">{p.bank_account_label}</div>
                    )}
                    {p.reference && <div className="text-xs text-slate-500">{p.reference}</div>}
                  </td>
                  <td className="py-2 text-xs text-slate-500">
                    {new Date(p.paid_at).toLocaleString()}
                    {p.is_reversed && (
                      <span className="ml-1 rounded bg-red-100 px-1.5 py-0.5 text-[10px] text-red-700">
                        reversed
                      </span>
                    )}
                  </td>
                  <td
                    className={`py-2 text-right font-medium ${
                      p.is_reversed ? "line-through" : p.direction === "paid" ? "text-red-600" : ""
                    }`}
                  >
                    {p.direction === "paid" ? "-" : ""}
                    {fmtMoney(p.amount, invoice.currency)}
                  </td>
                  <td className="py-2 text-right">
                    {!p.is_reversed && (
                      <button
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => setReversing(p)}
                      >
                        Reverse
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <TakePaymentModal
        open={takingPayment}
        onClose={() => setTakingPayment(false)}
        invoice={invoice}
        onTaken={() => {
          setTakingPayment(false);
          load();
        }}
      />

      <PasswordConfirm
        open={!!reversing}
        onClose={() => setReversing(null)}
        title={`Reverse ${reversing?.payment_no ?? "payment"}?`}
        description="The payment row is kept and marked reversed — a mirror entry goes into the ledger so both the receipt and its cancellation stay visible. The balance goes back up. Confirm with your password."
        confirmLabel="Reverse payment"
        onConfirm={confirmReverse}
      />

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

interface BankAccount {
  id: number;
  account_no: string;
  title: string | null;
  bank_name?: string | null;
}

/**
 * Taking money at the counter.
 *
 * Gold handed over is entered as it was weighed, with the purity and the rate
 * agreed there and then; the rupee value shown is the same arithmetic the
 * server performs (fine grams x rate), and the server's figure is the one that
 * is stored — this is only so nobody is asked to agree to a number they cannot
 * see.
 */
function TakePaymentModal({
  open,
  onClose,
  invoice,
  onTaken,
}: {
  open: boolean;
  onClose: () => void;
  invoice: Invoice;
  onTaken: () => void;
}) {
  const [method, setMethod] = useState("cash");
  const [direction, setDirection] = useState("received");
  const [amount, setAmount] = useState("0");
  const [weight, setWeight] = useState("0");
  const [purity, setPurity] = useState("22");
  const [rate, setRate] = useState(invoice.gold_rate_per_g);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [bankAccountId, setBankAccountId] = useState(0);
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    // Pre-fill with what is actually outstanding — the common case is the
    // customer settling the rest of the bill.
    setAmount(Number(invoice.balance_due) > 0 ? invoice.balance_due : "0");
    setRate(invoice.gold_rate_per_g);
    api
      .get<BankAccount[]>("/bank-accounts")
      .then((r) => {
        setBankAccounts(r.data);
        if (r.data.length) setBankAccountId(r.data[0].id);
      })
      .catch(() => {
        /* no bank accounts configured — cash and gold still work */
      });
  }, [open, invoice.balance_due, invoice.gold_rate_per_g]);

  const fine = ((Number(weight) || 0) * (Number(purity) || 24)) / 24;
  const goldValue = fine * (Number(rate) || 0);
  const isGold = method === "gold_exchange";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.post("/payments", {
        customer_id: invoice.customer_id,
        invoice_id: invoice.id,
        method,
        direction,
        // For a gold exchange the server derives the rupee value from the
        // weight and rate, so whatever is sent here is ignored.
        amount: isGold ? "0" : amount || "0",
        gold_weight_g: isGold ? weight || "0" : null,
        gold_purity: isGold ? Number(purity) || null : null,
        gold_rate_per_g: isGold ? rate || "0" : null,
        bank_account_id: method === "bank" ? bankAccountId || null : null,
        reference: reference || null,
        notes: notes || null,
      });
      toast("success", "Payment recorded");
      setReference("");
      setNotes("");
      onTaken();
    } catch (err) {
      toast("error", apiError(err, "Could not record the payment"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={`Take payment — ${invoice.invoice_no}`}>
      <form onSubmit={submit} className="space-y-4">
        <div className="rounded-lg bg-slate-50 px-3 py-2 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-500">Balance due</span>
            <span className="font-semibold">
              {fmtMoney(invoice.balance_due, invoice.currency)}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Method"
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            options={[
              { value: "cash", label: "Cash" },
              { value: "bank", label: "Bank transfer" },
              { value: "gold_exchange", label: "Gold exchange (old jewellery)" },
            ]}
          />
          <SelectField
            label="Direction"
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            options={[
              { value: "received", label: "Received from customer" },
              { value: "paid", label: "Paid back (change)" },
            ]}
            hint="Change given when old gold beats the bill"
          />
        </div>

        {isGold ? (
          <>
            <div className="grid grid-cols-3 gap-3">
              <TextField
                label="Weight (g)"
                type="number"
                step="0.0001"
                min={0}
                required
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
              />
              <TextField
                label="Purity (k)"
                type="number"
                min={1}
                max={24}
                value={purity}
                onChange={(e) => setPurity(e.target.value)}
              />
              <TextField
                label="Rate / fine g"
                type="number"
                step="0.0001"
                min={0}
                required
                value={rate}
                onChange={(e) => setRate(e.target.value)}
                hint="Agreed at the counter"
              />
            </div>
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {weight || 0} g at {purity || 24}k is{" "}
              <span className="font-semibold">{fine.toFixed(4)} g</span> fine ={" "}
              <span className="font-semibold">{fmtMoney(goldValue, invoice.currency)}</span>
              {Number(invoice.balance_due) > 0 && goldValue > Number(invoice.balance_due) && (
                <div className="mt-1">
                  That beats the balance by{" "}
                  {fmtMoney(goldValue - Number(invoice.balance_due), invoice.currency)} — record
                  the change back as a second payment with direction “Paid back”.
                </div>
              )}
            </div>
          </>
        ) : (
          <TextField
            label="Amount"
            type="number"
            step="0.01"
            min={0}
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        )}

        {method === "bank" && (
          <SelectField
            label="Bank account"
            required
            value={String(bankAccountId)}
            onChange={(e) => setBankAccountId(Number(e.target.value))}
            options={[
              { value: 0, label: "— pick —" },
              ...bankAccounts.map((b) => ({
                value: b.id,
                label: `${b.bank_name ?? b.title ?? "Account"} · ${b.account_no}`,
              })),
            ]}
            hint="A transfer that names no account cannot be reconciled"
          />
        )}

        <TextField
          label="Reference"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          placeholder="Slip no, cheque no…"
        />
        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn-primary"
            disabled={submitting || (method === "bank" && !bankAccountId)}
          >
            {submitting ? "Recording…" : "Record payment"}
          </button>
        </div>
      </form>
    </Modal>
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

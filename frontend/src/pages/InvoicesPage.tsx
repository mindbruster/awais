import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { SearchBox, FilterSelect, Toolbar } from "@/components/Toolbar";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { CURRENCY_OPTIONS, Currency, fmtMoney } from "@/lib/money";

const STATUSES = [
  { value: "draft", label: "Draft" },
  { value: "issued", label: "Issued" },
  { value: "paid", label: "Paid" },
  { value: "void", label: "Void" },
  { value: "returned", label: "Returned" },
];

const SALE_TYPES = [
  { value: "normal", label: "Normal" },
  { value: "on_approval", label: "On approval" },
];

interface Invoice {
  id: number;
  invoice_no: string;
  sale_type: string;
  status: string;
  customer_id: number;
  customer_name: string | null;
  seller_name: string | null;
  currency: Currency;
  subtotal: string;
  discount_amount: string;
  total: string;
  issued_at: string | null;
}

/**
 * A salesman or a broker, as the invoice form offers them.
 *
 * `kind` is carried so the two can be labelled apart in the picker. A salesman
 * carries the shop's stock; a broker introduces a buyer and holds nothing.
 * They settle differently and a bill credited to the wrong sort is a
 * commission paid on the wrong basis.
 */
interface Seller {
  id: number;
  name: string;
  kind: "salesman" | "broker";
  commission_pct: string;
}

interface Customer {
  id: number;
  name: string;
}

interface Product {
  id: number;
  serial_no: string;
  name: string;
  gold_weight_g: string;
  gold_purity: number | null;
  stone_weight_ct: string;
  status: string;
}

const STATUS_COLOR: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  issued: "bg-blue-100 text-blue-800",
  paid: "bg-emerald-100 text-emerald-800",
  returned: "bg-amber-100 text-amber-800",
  void: "bg-red-100 text-red-700",
};

export function InvoicesPage() {
  const [items, setItems] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openCreate, setOpenCreate] = useState(false);
  const [voiding, setVoiding] = useState<Invoice | null>(null);
  const [issuing, setIssuing] = useState<Invoice | null>(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [saleType, setSaleType] = useState("");

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (status) params.status = status;
    if (saleType) params.sale_type = saleType;
    api
      .get<Invoice[]>("/invoices", { params })
      .then((res) => setItems(res.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q, status, saleType]);

  const action = async (id: number, path: string, msg: string) => {
    try {
      await api.post(`/invoices/${id}/${path}`);
      toast("success", msg);
      load();
    } catch (err) {
      toast("error", apiError(err, "Action failed"));
    }
  };

  const confirmVoid = async (password: string) => {
    if (!voiding) return;
    try {
      await api.post(
        `/invoices/${voiding.id}/void`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `Invoice ${voiding.invoice_no} voided`);
      setVoiding(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Void failed"));
    }
  };

  const confirmIssue = async (password: string) => {
    if (!issuing) return;
    try {
      await api.post(
        `/invoices/${issuing.id}/issue`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `Invoice ${issuing.invoice_no} issued`);
      setIssuing(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Issue failed"));
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Invoices</h1>
        <button className="btn-primary" onClick={() => setOpenCreate(true)}>
          New invoice
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Normal sales deduct stock on issue. On-approval sales don't.
      </p>
      <Toolbar>
        <SearchBox value={q} onChange={setQ} placeholder="Search invoice #" className="w-64" />
        <FilterSelect value={status} onChange={setStatus} options={STATUSES} allLabel="All statuses" />
        <FilterSelect value={saleType} onChange={setSaleType} options={SALE_TYPES} allLabel="All types" />
        <span className="ml-auto text-xs text-slate-500">{items.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="p-6 text-sm text-slate-500">No invoices yet.</div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Invoice #</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Sold by</th>
                <th className="px-4 py-3 text-right">Subtotal</th>
                <th className="px-4 py-3 text-right">Discount</th>
                <th className="px-4 py-3 text-right">Total</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((inv) => (
                <tr key={inv.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-xs">
                    <Link to={`/invoices/${inv.id}`} className="text-brand-700 hover:underline">
                      {inv.invoice_no}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                      {inv.sale_type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        STATUS_COLOR[inv.status] ?? "bg-slate-100"
                      }`}
                    >
                      {inv.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {inv.customer_name ?? (
                      <span className="text-slate-400">#{inv.customer_id}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {inv.seller_name ?? <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right">{fmtMoney(inv.subtotal, inv.currency)}</td>
                  <td className="px-4 py-3 text-right text-red-600">
                    {fmtMoney(inv.discount_amount, inv.currency)}
                  </td>
                  <td className="px-4 py-3 text-right font-semibold">
                    {fmtMoney(inv.total, inv.currency)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {inv.status === "draft" && (
                        <button
                          className="rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-700"
                          onClick={() => setIssuing(inv)}
                        >
                          Issue
                        </button>
                      )}
                      {inv.status === "issued" && (
                        <>
                          {/* No longer a flag: this records a cash payment for
                              whatever is still outstanding, which is why it
                              says what it does. Part payments, transfers and
                              gold exchange live on the invoice's detail page. */}
                          <button
                            className="rounded bg-emerald-600 px-2 py-1 text-xs text-white hover:bg-emerald-700"
                            title="Records a cash payment for the outstanding balance"
                            onClick={() =>
                              action(inv.id, "mark-paid", "Cash payment recorded for the balance")
                            }
                          >
                            Cash in full
                          </button>
                          <button
                            className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200"
                            onClick={() => setVoiding(inv)}
                          >
                            Void
                          </button>
                        </>
                      )}
                      {inv.status === "draft" && (
                        <button
                          className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700 hover:bg-slate-200"
                          onClick={() => setVoiding(inv)}
                        >
                          Discard
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <NewInvoiceModal
        open={openCreate}
        onClose={() => setOpenCreate(false)}
        onCreated={() => {
          setOpenCreate(false);
          load();
        }}
      />

      <PasswordConfirm
        open={!!voiding}
        onClose={() => setVoiding(null)}
        title={`Void ${voiding?.invoice_no ?? "invoice"}?`}
        description={
          voiding?.status === "draft"
            ? "Discarding a draft is reversible only by re-creating it. Confirm with your password."
            : "Voiding an issued invoice will reverse stock movements and reset product status. Confirm with your password."
        }
        confirmLabel="Void invoice"
        onConfirm={confirmVoid}
      />
      <PasswordConfirm
        open={!!issuing}
        onClose={() => setIssuing(null)}
        title={`Issue ${issuing?.invoice_no ?? "invoice"}?`}
        description={
          issuing?.sale_type === "on_approval"
            ? "Issuing an on-approval invoice marks linked products as on_approval (stock untouched). Confirm with your password."
            : "Issuing a normal sale will deduct stock from inventory. Confirm with your password."
        }
        confirmLabel="Issue invoice"
        destructive={false}
        onConfirm={confirmIssue}
      />
    </div>
  );
}

interface DraftItem {
  product_id: number | null;
  description: string;
  quantity: number;
  gold_weight_g: string;
  gold_purity: string;
  gold_rate_per_g: string;
  stone_weight_ct: string;
  stone_rate_per_ct: string;
  labor_amount: string;
  line_discount: string;
  discount_ratti: string;
  sale_wastage_pct: string;
  sale_wastage_g: string;
}

// The customary base the counter quotes against. Stored per line (the column
// exists) so an unusual base is possible, but nothing in the UI varies it yet.
const RATTI_BASE = 96;

/**
 * Previews of the backend pricing, mirroring services/pricing.py. Only ever
 * shown while the operator is still typing — the server recomputes every figure
 * from the fields that were sent, so a drift here can misinform but cannot
 * mis-bill. Once the invoice exists the detail page reads the server's own
 * derived weights instead of these.
 *
 * charged  = net * (1 + pct/100) + flat      (wastage marks the metal up)
 * billable = charged / base * (base - ratti) (the ratti discount gives back)
 */
function chargedGold(weight: string, pct: string, grams: string): number {
  return (Number(weight) || 0) * (1 + (Number(pct) || 0) / 100) + (Number(grams) || 0);
}

function billableGold(it: DraftItem): number {
  const charged = chargedGold(it.gold_weight_g, it.sale_wastage_pct, it.sale_wastage_g);
  const remaining = RATTI_BASE - (Number(it.discount_ratti) || 0);
  if (remaining <= 0) return 0;
  return (charged / RATTI_BASE) * remaining;
}

/** Preview of `price_line`: gold + stone + labour, x qty, less the line discount. */
function lineTotal(it: DraftItem, invoiceRate: string): number {
  const qty = Math.max(it.quantity || 1, 0);
  const rate = Number(it.gold_rate_per_g) || Number(invoiceRate) || 0;
  const purity = Number(it.gold_purity) ? Number(it.gold_purity) / 24 : 1;
  const gold = billableGold(it) * purity * rate * qty;
  const stone = (Number(it.stone_weight_ct) || 0) * (Number(it.stone_rate_per_ct) || 0) * qty;
  const labour = (Number(it.labor_amount) || 0) * qty;
  return Math.max(gold + stone + labour - (Number(it.line_discount) || 0), 0);
}

const blankItem = (): DraftItem => ({
  product_id: null,
  description: "",
  quantity: 1,
  gold_weight_g: "0",
  gold_purity: "22",
  gold_rate_per_g: "",
  stone_weight_ct: "0",
  stone_rate_per_ct: "0",
  labor_amount: "0",
  line_discount: "0",
  discount_ratti: "0",
  sale_wastage_pct: "0",
  sale_wastage_g: "0",
});

function NewInvoiceModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [sellers, setSellers] = useState<Seller[]>([]);
  const [customerId, setCustomerId] = useState<number>(0);
  // Who gets credit for the sale. Optional — a walk-in served by nobody in
  // particular is an ordinary bill, and forcing a name would put fictional
  // sales against whoever is first in the list.
  const [sellerId, setSellerId] = useState<number>(0);
  const [saleType, setSaleType] = useState("normal");
  // Which of the shop's two bills. A loose-material bill carries no gold at
  // all — the server refuses weight, wastage and ratti on one — so the gold
  // fields are hidden rather than left to be rejected after typing.
  const [kind, setKind] = useState<"finished_product" | "loose_material">(
    "finished_product",
  );
  const [currency, setCurrency] = useState<Currency>("PKR");
  const [goldRate, setGoldRate] = useState("0");
  const [discount, setDiscount] = useState("0");
  const [discountWeight, setDiscountWeight] = useState("0");
  const [tax, setTax] = useState("0");
  const [billBookNo, setBillBookNo] = useState("");
  // Days of credit. 0 — due on issue — is a counter sale and the common case.
  const [termDays, setTermDays] = useState("0");
  const [roundOff, setRoundOff] = useState("0");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<DraftItem[]>([blankItem()]);
  const [submitting, setSubmitting] = useState(false);

  // Preview of what the server will compute, so the round-off button has a
  // figure to work from and the operator can see the effect before saving.
  const subtotalPreview = items.reduce((sum, it) => sum + lineTotal(it, goldRate), 0);
  const beforeRounding = Math.max(
    subtotalPreview -
      (Number(discount) || 0) -
      (Number(discountWeight) || 0) * (Number(goldRate) || 0) +
      (Number(tax) || 0),
    0,
  );
  const totalPreview = Math.max(beforeRounding - (Number(roundOff) || 0), 0);

  /**
   * The paisa (and rupees) the counter waives to reach a figure the customer
   * can hand over. It is written to `round_off` rather than quietly adjusting
   * the total, because a round-off folded into the price is an untracked
   * discount the margin report can never see.
   */
  const roundToNearest100 = () => {
    const remainder = beforeRounding % 100;
    setRoundOff(remainder.toFixed(2));
  };

  useEffect(() => {
    if (!open) return;
    Promise.all([
      api.get<Customer[]>("/customers"),
      api.get<Product[]>("/products"),
      // Active only: a salesman who has left should not be offered on a bill
      // written today, though the bills he already carries keep his name.
      api.get<Seller[]>("/sales/sellers", { params: { is_active: true } }),
    ]).then(([c, p, s_]) => {
      setCustomers(c.data);
      setProducts(p.data);
      setSellers(s_.data);
      if (c.data.length && !customerId) setCustomerId(c.data[0].id);
    });
  }, [open]);

  // Auto-fill the gold rate from the latest /gold-rates/current whenever
  // the chosen currency changes (or the modal opens). Silent fallback if
  // no rate has been set yet — user can type one manually.
  useEffect(() => {
    if (!open) return;
    api
      .get<{ rate_per_g: string }>("/gold-rates/current", {
        params: { currency, purity: 24 },
      })
      .then((r) => setGoldRate(r.data.rate_per_g))
      .catch(() => {
        /* no rate set yet — leave the field as-is */
      });
  }, [open, currency]);

  const updateItem = (i: number, patch: Partial<DraftItem>) => {
    setItems((prev) => prev.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  };

  const removeItem = (i: number) => {
    setItems((prev) => (prev.length > 1 ? prev.filter((_, idx) => idx !== i) : prev));
  };

  const pickProduct = (i: number, productId: string) => {
    const id = Number(productId);
    if (!id) return updateItem(i, { product_id: null });
    const p = products.find((p) => p.id === id);
    if (!p) return;
    updateItem(i, {
      product_id: id,
      description: `${p.serial_no} — ${p.name}`,
      gold_weight_g: p.gold_weight_g,
      gold_purity: p.gold_purity ? String(p.gold_purity) : "",
      stone_weight_ct: p.stone_weight_ct,
    });
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!customerId) {
      toast("error", "Pick a customer first");
      return;
    }
    const loose = kind === "loose_material";
    setSubmitting(true);
    try {
      await api.post("/invoices", {
        customer_id: customerId,
        seller_id: sellerId || null,
        sale_type: saleType,
        kind,
        currency,
        gold_rate_per_g: goldRate || "0",
        discount_amount: discount || "0",
        discount_weight_g: discountWeight || "0",
        tax_amount: tax || "0",
        bill_book_no: billBookNo || null,
        term_days: Number(termDays || 0),
        round_off: roundOff || "0",
        notes: notes || null,
        items: items.map((it) => ({
          product_id: it.product_id,
          description: it.description || "Untitled line",
          quantity: it.quantity || 1,
          // Zeroed rather than sent on a loose-material bill. The server
          // refuses gold on one, and a value left over from switching the bill
          // type halfway through would come back as a validation error naming
          // a field the form is no longer showing.
          gold_weight_g: loose ? "0" : it.gold_weight_g || "0",
          gold_purity: loose ? null : it.gold_purity ? parseInt(it.gold_purity, 10) : null,
          gold_rate_per_g: loose ? "0" : it.gold_rate_per_g || goldRate || "0",
          stone_weight_ct: it.stone_weight_ct || "0",
          stone_rate_per_ct: it.stone_rate_per_ct || "0",
          labor_amount: it.labor_amount || "0",
          line_discount: it.line_discount || "0",
          discount_ratti: loose ? "0" : it.discount_ratti || "0",
          ratti_base: RATTI_BASE,
          sale_wastage_pct: loose ? "0" : it.sale_wastage_pct || "0",
          sale_wastage_g: loose ? "0" : it.sale_wastage_g || "0",
        })),
      });
      toast("success", "Invoice draft created");
      setItems([blankItem()]);
      setNotes("");
      setDiscount("0");
      setDiscountWeight("0");
      setTax("0");
      setBillBookNo("");
      setRoundOff("0");
      onCreated();
    } catch (err) {
      toast("error", apiError(err, "Could not create invoice"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="New invoice (draft)" widthClass="max-w-3xl">
      <form onSubmit={submit} className="space-y-5">
        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Customer"
            required
            value={String(customerId)}
            onChange={(e) => setCustomerId(Number(e.target.value))}
            options={[{ value: 0, label: "— pick —" }, ...customers.map((c) => ({ value: c.id, label: c.name }))]}
          />
          {/* Right after the customer, which is the order the counter works
              in and the order the specification asks for. Optional: a bill
              nobody is credited with is ordinary, and a required field here
              would put invented sales against whoever sorts first. */}
          <SelectField
            label="Sold by"
            value={String(sellerId)}
            onChange={(e) => setSellerId(Number(e.target.value))}
            options={[
              { value: 0, label: "— nobody in particular —" },
              ...sellers.map((s_) => ({
                value: s_.id,
                label:
                  s_.kind === "broker" ? `${s_.name} · broker` : s_.name,
              })),
            ]}
            hint={
              sellers.length === 0
                ? "No salesmen on file — add them under Sales."
                : "Credits the sale to their target"
            }
          />
          <SelectField
            label="Sale type"
            value={saleType}
            onChange={(e) => setSaleType(e.target.value)}
            options={[
              { value: "normal", label: "Normal" },
              { value: "on_approval", label: "On approval" },
            ]}
          />
        </div>
        <SelectField
          label="Bill for"
          value={kind}
          onChange={(e) => setKind(e.target.value as typeof kind)}
          options={[
            { value: "finished_product", label: "Finished pieces" },
            { value: "loose_material", label: "Loose material — stones only" },
          ]}
          hint={
            kind === "loose_material"
              ? "No gold on this bill: no weight, no wastage, no ratti. The discount comes off the stone price."
              : "Billed on the metal, with the stones priced alongside."
          }
        />
        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value as Currency)}
            options={CURRENCY_OPTIONS}
          />
          <TextField
            label="Gold rate (per g, 24k)"
            type="number"
            step="0.0001"
            min={0}
            value={goldRate}
            onChange={(e) => setGoldRate(e.target.value)}
            hint="Auto-filled from latest /gold-rates"
          />
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">Line items</h3>
            <button
              type="button"
              className="btn-ghost text-xs"
              onClick={() => setItems((p) => [...p, blankItem()])}
            >
              + Add line
            </button>
          </div>
          <div className="space-y-3">
            {items.map((it, i) => (
              <div key={i} className="rounded-lg border border-slate-200 p-3">
                <div className="grid grid-cols-12 gap-2">
                  <div className="col-span-4">
                    <SelectField
                      label="Product (optional)"
                      value={String(it.product_id ?? 0)}
                      onChange={(e) => pickProduct(i, e.target.value)}
                      options={[
                        { value: 0, label: "— free-form —" },
                        ...products.map((p) => ({
                          value: p.id,
                          label: `${p.serial_no} · ${p.name}`,
                        })),
                      ]}
                    />
                  </div>
                  <div className="col-span-5">
                    <TextField
                      label="Description"
                      required
                      value={it.description}
                      onChange={(e) => updateItem(i, { description: e.target.value })}
                    />
                  </div>
                  <div className="col-span-2">
                    <TextField
                      label="Qty"
                      type="number"
                      min={1}
                      value={String(it.quantity)}
                      onChange={(e) => updateItem(i, { quantity: Number(e.target.value) || 1 })}
                    />
                  </div>
                  <div className="col-span-1 flex items-end">
                    <button
                      type="button"
                      className="text-xs text-red-500 hover:underline disabled:text-slate-300"
                      onClick={() => removeItem(i)}
                      disabled={items.length === 1}
                    >
                      Remove
                    </button>
                  </div>
                </div>
                <div className="mt-2 grid grid-cols-8 gap-2">
                  <TextField
                    label="Gold (g)"
                    type="number"
                    step="0.0001"
                    min={0}
                    value={it.gold_weight_g}
                    onChange={(e) => updateItem(i, { gold_weight_g: e.target.value })}
                  />
                  <TextField
                    label="Disc (ratti)"
                    type="number"
                    step="0.001"
                    min={0}
                    max={RATTI_BASE}
                    value={it.discount_ratti}
                    onChange={(e) => updateItem(i, { discount_ratti: e.target.value })}
                    hint={`of ${RATTI_BASE}`}
                  />
                  <TextField
                    label="Purity"
                    type="number"
                    min={1}
                    max={24}
                    value={it.gold_purity}
                    onChange={(e) => updateItem(i, { gold_purity: e.target.value })}
                  />
                  <TextField
                    label="Gold rate"
                    type="number"
                    step="0.0001"
                    min={0}
                    value={it.gold_rate_per_g}
                    onChange={(e) => updateItem(i, { gold_rate_per_g: e.target.value })}
                    placeholder="(invoice rate)"
                  />
                  <TextField
                    label="Stone (ct)"
                    type="number"
                    step="0.0001"
                    min={0}
                    value={it.stone_weight_ct}
                    onChange={(e) => updateItem(i, { stone_weight_ct: e.target.value })}
                  />
                  <TextField
                    label="Stone rate"
                    type="number"
                    step="0.0001"
                    min={0}
                    value={it.stone_rate_per_ct}
                    onChange={(e) => updateItem(i, { stone_rate_per_ct: e.target.value })}
                  />
                  <TextField
                    label="Labor"
                    type="number"
                    step="0.01"
                    min={0}
                    value={it.labor_amount}
                    onChange={(e) => updateItem(i, { labor_amount: e.target.value })}
                  />
                  <TextField
                    label="Line disc"
                    type="number"
                    step="0.01"
                    min={0}
                    value={it.line_discount}
                    onChange={(e) => updateItem(i, { line_discount: e.target.value })}
                    hint="Subtracted from line"
                  />
                </div>
                <div className="mt-2 grid grid-cols-8 gap-2">
                  <TextField
                    label="Wastage %"
                    type="number"
                    step="0.001"
                    min={0}
                    value={it.sale_wastage_pct}
                    onChange={(e) => updateItem(i, { sale_wastage_pct: e.target.value })}
                    hint="Charged to customer"
                  />
                  <TextField
                    label="Wastage (g)"
                    type="number"
                    step="0.0001"
                    min={0}
                    value={it.sale_wastage_g}
                    onChange={(e) => updateItem(i, { sale_wastage_g: e.target.value })}
                    hint="Flat, adds to %"
                  />
                </div>
                {/* The operator has to see what the customer is actually being
                    charged for before saving — a percentage and a ratti figure
                    do not read as a weight, and the weight is what the money is
                    calculated on. */}
                {(Number(it.sale_wastage_pct) > 0 ||
                  Number(it.sale_wastage_g) > 0 ||
                  Number(it.discount_ratti) > 0) && (
                  <div className="mt-2 text-xs text-amber-700">
                    Net{" "}
                    <span className="text-slate-500">
                      {(Number(it.gold_weight_g) || 0).toFixed(4)} g
                    </span>
                    {(Number(it.sale_wastage_pct) > 0 || Number(it.sale_wastage_g) > 0) && (
                      <>
                        {" "}
                        → with wastage{" "}
                        {Number(it.sale_wastage_pct) > 0 ? `${it.sale_wastage_pct}%` : ""}
                        {Number(it.sale_wastage_g) > 0 ? ` +${it.sale_wastage_g}g` : ""}{" "}
                        <span className="text-slate-500">
                          {chargedGold(it.gold_weight_g, it.sale_wastage_pct, it.sale_wastage_g).toFixed(4)} g
                        </span>
                      </>
                    )}
                    {Number(it.discount_ratti) > 0 && (
                      <> → less {it.discount_ratti}/{RATTI_BASE} ratti</>
                    )}{" "}
                    → billed on{" "}
                    <span className="font-semibold">{billableGold(it).toFixed(4)} g</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <TextField
            label="Discount (amount)"
            type="number"
            step="0.01"
            min={0}
            value={discount}
            onChange={(e) => setDiscount(e.target.value)}
          />
          <TextField
            label="Discount (weight g)"
            type="number"
            step="0.0001"
            min={0}
            value={discountWeight}
            onChange={(e) => setDiscountWeight(e.target.value)}
            hint="Converted at gold rate"
          />
          <TextField
            label="Tax"
            type="number"
            step="0.01"
            min={0}
            value={tax}
            onChange={(e) => setTax(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-3 items-end gap-3">
          <TextField
            label="Bill book #"
            value={billBookNo}
            onChange={(e) => setBillBookNo(e.target.value)}
            placeholder="e.g. 441"
            hint="The paper bill this matches"
          />
          {/* Prints on the bill as Term Days, with the due date worked out
              from it. Zero is a counter sale — money now. */}
          <TextField
            label="Term days"
            type="number"
            min="0"
            value={termDays}
            onChange={(e) => setTermDays(e.target.value)}
            hint="Days of credit — 0 is due on issue"
          />
          <TextField
            label="Round off"
            type="number"
            step="0.01"
            value={roundOff}
            onChange={(e) => setRoundOff(e.target.value)}
            hint="Subtracted; negative rounds up"
          />
          <button type="button" className="btn-ghost mb-1" onClick={roundToNearest100}>
            Round to nearest 100
          </button>
        </div>

        <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm">
          <div className="flex justify-between text-slate-600">
            <span>Before rounding</span>
            <span>{fmtMoney(beforeRounding, currency)}</span>
          </div>
          {Number(roundOff) !== 0 && (
            <div className="flex justify-between text-amber-700">
              <span>Round off</span>
              <span>-{fmtMoney(roundOff, currency)}</span>
            </div>
          )}
          <div className="mt-1 flex justify-between border-t border-slate-200 pt-1 font-semibold text-slate-900">
            <span>Total (preview)</span>
            <span>{fmtMoney(totalPreview, currency)}</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Recalculated by the server on save — this is a guide, not the bill.
          </p>
        </div>

        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting || !customerId}>
            {submitting ? "Saving…" : "Create draft"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

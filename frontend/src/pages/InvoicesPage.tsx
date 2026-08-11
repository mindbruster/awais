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
  currency: Currency;
  subtotal: string;
  discount_amount: string;
  total: string;
  issued_at: string | null;
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
                  <td className="px-4 py-3 text-slate-500">#{inv.customer_id}</td>
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
                          <button
                            className="rounded bg-emerald-600 px-2 py-1 text-xs text-white hover:bg-emerald-700"
                            onClick={() => action(inv.id, "mark-paid", "Marked paid")}
                          >
                            Mark paid
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
}

// The customary base the counter quotes against. Stored per line (the column
// exists) so an unusual base is possible, but nothing in the UI varies it yet.
const RATTI_BASE = 96;

/**
 * Preview of backend `apply_ratti_discount` — billable = weight / base * (base
 * - ratti). Only ever shown, never sent: the server recomputes it from
 * discount_ratti, so a drift here can misinform but cannot mis-bill.
 */
function billableGold(weight: string, ratti: string): number {
  const w = Number(weight) || 0;
  const r = Number(ratti) || 0;
  const remaining = RATTI_BASE - r;
  if (remaining <= 0) return 0;
  return (w / RATTI_BASE) * remaining;
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
  const [customerId, setCustomerId] = useState<number>(0);
  const [saleType, setSaleType] = useState("normal");
  const [currency, setCurrency] = useState<Currency>("PKR");
  const [goldRate, setGoldRate] = useState("0");
  const [discount, setDiscount] = useState("0");
  const [discountWeight, setDiscountWeight] = useState("0");
  const [tax, setTax] = useState("0");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<DraftItem[]>([blankItem()]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    Promise.all([
      api.get<Customer[]>("/customers"),
      api.get<Product[]>("/products"),
    ]).then(([c, p]) => {
      setCustomers(c.data);
      setProducts(p.data);
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
    setSubmitting(true);
    try {
      await api.post("/invoices", {
        customer_id: customerId,
        sale_type: saleType,
        currency,
        gold_rate_per_g: goldRate || "0",
        discount_amount: discount || "0",
        discount_weight_g: discountWeight || "0",
        tax_amount: tax || "0",
        notes: notes || null,
        items: items.map((it) => ({
          product_id: it.product_id,
          description: it.description || "Untitled line",
          quantity: it.quantity || 1,
          gold_weight_g: it.gold_weight_g || "0",
          gold_purity: it.gold_purity ? parseInt(it.gold_purity, 10) : null,
          gold_rate_per_g: it.gold_rate_per_g || goldRate || "0",
          stone_weight_ct: it.stone_weight_ct || "0",
          stone_rate_per_ct: it.stone_rate_per_ct || "0",
          labor_amount: it.labor_amount || "0",
          line_discount: it.line_discount || "0",
          discount_ratti: it.discount_ratti || "0",
          ratti_base: RATTI_BASE,
        })),
      });
      toast("success", "Invoice draft created");
      setItems([blankItem()]);
      setNotes("");
      setDiscount("0");
      setDiscountWeight("0");
      setTax("0");
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
                {/* The operator has to see what the customer is actually being
                    charged for before saving — the ratti figure alone doesn't
                    read as a weight. */}
                {Number(it.discount_ratti) > 0 && (
                  <div className="mt-2 text-xs text-amber-700">
                    Ratti discount {it.discount_ratti}/{RATTI_BASE} — billable gold{" "}
                    <span className="line-through text-slate-400">
                      {(Number(it.gold_weight_g) || 0).toFixed(4)} g
                    </span>{" "}
                    →{" "}
                    <span className="font-semibold">
                      {billableGold(it.gold_weight_g, it.discount_ratti).toFixed(4)} g
                    </span>
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

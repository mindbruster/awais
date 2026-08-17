/**
 * Who brings the business, and what they are asked to bring.
 *
 * Salesmen and targets share a screen because neither is read without the
 * other: a name with no figure is a contact record, and a figure with no name
 * is a wish. The one question this page answers is "is he going to make it",
 * and that needs the target, the actual, and how much of the month has gone —
 * all three, or the reader draws the wrong conclusion from the same number
 * twice a month.
 *
 * Salesmen and brokers are shown together but never blended. A salesman
 * carries the shop's stock and a broker holds nothing, so a total across both
 * would describe a business that does not exist.
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

type Kind = "salesman" | "broker";
type Scope = "company" | "customer" | "seller";

interface Seller {
  id: number;
  name: string;
  kind: Kind;
  phone: string | null;
  commission_pct: string;
  is_active: boolean;
}

interface Target {
  id: number;
  scope: Scope;
  customer_name: string | null;
  seller_name: string | null;
  period_start: string;
  period_end: string;
  label: string | null;
  target_amount: string | null;
  target_weight_g: string | null;
  actual_amount: string;
  actual_weight_g: string;
  invoices: number;
  amount_pct: string | null;
  weight_pct: string | null;
  period_elapsed_pct: string | null;
}

interface Named {
  id: number;
  name: string;
}

const monthEnd = () => {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);
};
const monthStart = () => {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
};

export function SellersPage() {
  const [sellers, setSellers] = useState<Seller[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [addSeller, setAddSeller] = useState(false);
  const [addTarget, setAddTarget] = useState(false);
  const [targetsDenied, setTargetsDenied] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await api.get<Seller[]>("/sales/sellers");
      setSellers(s.data);
    } catch (e) {
      setError(apiError(e, "Could not load salesmen"));
    }
    try {
      const t = await api.get<Target[]>("/sales/targets");
      setTargets(t.data);
      setTargetsDenied(false);
    } catch (e) {
      setTargetsDenied((e as { response?: { status?: number } })?.response?.status === 403);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Salesmen & targets</h1>
          <p className="mt-1 text-sm text-slate-500">
            Who brings the business, and what they are asked to bring.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={() => setAddSeller(true)}>
            Add salesman
          </button>
          {!targetsDenied && (
            <button className="btn-primary" onClick={() => setAddTarget(true)}>
              Set a target
            </button>
          )}
        </div>
      </div>

      {/* --- targets --- */}
      {targetsDenied ? (
        <div className="card text-xs leading-relaxed text-slate-500">
          Targets are money figures about people and are not shown at your access level.
        </div>
      ) : (
        <section>
          <h2 className="eyebrow">Targets</h2>
          {targets.length === 0 ? (
            <p className="card mt-2 text-sm text-slate-500">
              Nothing set yet. A target can be for the whole shop, one customer, or one
              salesman — in money, in weight, or both.
            </p>
          ) : (
            <div className="mt-2 grid gap-3 lg:grid-cols-2">
              {targets.map((t) => (
                <TargetCard key={t.id} t={t} />
              ))}
            </div>
          )}
        </section>
      )}

      {/* --- the people --- */}
      <section>
        <h2 className="eyebrow">Salesmen and brokers</h2>
        <div className="card mt-2 p-0">
          {sellers.length === 0 ? (
            <p className="px-5 py-6 text-sm text-slate-500">Nobody added yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-5 py-2">Name</th>
                  <th className="px-5 py-2">Kind</th>
                  <th className="px-5 py-2">Phone</th>
                  <th className="px-5 py-2 text-right">Commission</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {sellers.map((s) => (
                  <tr key={s.id}>
                    <td className="px-5 py-2.5 font-medium">
                      <Link
                        to={`/sales/${s.id}`}
                        className="text-brand-700 hover:underline"
                      >
                        {s.name}
                      </Link>
                      {!s.is_active && <span className="chip-dead ml-2">inactive</span>}
                    </td>
                    <td className="px-5 py-2.5">
                      {/* Never blended into one total: a salesman carries the
                          shop's stock and a broker holds nothing. */}
                      <span className={s.kind === "broker" ? "chip-idle" : "chip-back"}>
                        {s.kind}
                      </span>
                    </td>
                    <td className="px-5 py-2.5 text-slate-500">{s.phone ?? "—"}</td>
                    <td className="num px-5 py-2.5 text-right">
                      {Number(s.commission_pct)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <SellerForm
        open={addSeller}
        onClose={() => setAddSeller(false)}
        onSaved={() => {
          setAddSeller(false);
          load();
        }}
      />
      <TargetForm
        open={addTarget}
        sellers={sellers}
        onClose={() => setAddTarget(false)}
        onSaved={() => {
          setAddTarget(false);
          load();
        }}
      />
    </div>
  );
}

function TargetCard({ t }: { t: Target }) {
  const who =
    t.scope === "company" ? "The shop" : t.seller_name ?? t.customer_name ?? "—";
  const elapsed = t.period_elapsed_pct ? Number(t.period_elapsed_pct) : null;
  return (
    <div className="card">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">{who}</p>
          <p className="text-[11px] text-slate-500">
            {t.label ? `${t.label} · ` : ""}
            {t.period_start} → {t.period_end}
          </p>
        </div>
        {elapsed !== null && (
          <span className="num text-[11px] text-slate-400">{elapsed.toFixed(0)}% elapsed</span>
        )}
      </div>

      <div className="mt-3 space-y-3">
        {/* Only the halves that were set. A percentage against nothing is not
            zero, it is meaningless, and zero would read as failure. */}
        {t.target_amount && (
          <Bar
            label="Money"
            actual={fmtMoney(t.actual_amount)}
            target={fmtMoney(t.target_amount)}
            pct={t.amount_pct ? Number(t.amount_pct) : 0}
            elapsed={elapsed}
          />
        )}
        {t.target_weight_g && (
          <Bar
            label="Weight"
            actual={`${Number(t.actual_weight_g).toFixed(3)} g`}
            target={`${Number(t.target_weight_g).toFixed(3)} g`}
            pct={t.weight_pct ? Number(t.weight_pct) : 0}
            elapsed={elapsed}
          />
        )}
      </div>
      <p className="mt-2 text-[11px] text-slate-400">
        {t.invoices} bill{t.invoices === 1 ? "" : "s"} in the period
      </p>
    </div>
  );
}

function Bar({
  label,
  actual,
  target,
  pct,
  elapsed,
}: {
  label: string;
  actual: string;
  target: string;
  pct: number;
  elapsed: number | null;
}) {
  // Ahead or behind is the question, and it is only answerable against how much
  // of the period has gone — 60% of target is excellent on day three and a
  // problem on day thirty.
  const behind = elapsed !== null && pct < elapsed;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className="num">
          <span className="font-medium text-slate-900">{actual}</span>
          <span className="text-slate-400"> of {target}</span>
        </span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full ${
            pct >= 100 ? "bg-emerald-500" : behind ? "bg-amber-500" : "bg-brand-500"
          }`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <p className="num mt-0.5 text-[11px] text-slate-500">
        {pct.toFixed(0)}%
        {elapsed !== null && (
          <span className={behind ? "text-amber-700" : "text-emerald-700"}>
            {" "}
            · {behind ? "behind" : "ahead of"} the calendar
          </span>
        )}
      </p>
    </div>
  );
}

function SellerForm({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("salesman");
  const [phone, setPhone] = useState("");
  const [commission, setCommission] = useState("0");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName("");
    setKind("salesman");
    setPhone("");
    setCommission("0");
    setNotes("");
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/sales/sellers", {
        name: name.trim(),
        kind,
        phone: phone || null,
        commission_pct: commission || "0",
        notes: notes || null,
      });
      toast("success", `${name} added`);
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not add them"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Add a salesman or broker">
      <form onSubmit={submit} className="space-y-4">
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
        <SelectField
          label="Kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
          options={[
            { value: "salesman", label: "Salesman — carries the shop's stock" },
            { value: "broker", label: "Broker — introduces a buyer, holds nothing" },
          ]}
          hint="They settle differently, so they are never totalled together."
        />
        <div className="grid grid-cols-2 gap-3">
          <TextField label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
          <TextField
            label="Commission (%)"
            type="number"
            step="0.001"
            min={0}
            max={100}
            value={commission}
            onChange={(e) => setCommission(e.target.value)}
            hint="On what they bring"
          />
        </div>
        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={busy || !name.trim()}>
            {busy ? "Adding…" : "Add"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function TargetForm({
  open,
  sellers,
  onClose,
  onSaved,
}: {
  open: boolean;
  sellers: Seller[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [scope, setScope] = useState<Scope>("company");
  const [customers, setCustomers] = useState<Named[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [sellerId, setSellerId] = useState("");
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(monthEnd());
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [weight, setWeight] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setScope("company");
    setFrom(monthStart());
    setTo(monthEnd());
    setLabel("");
    setAmount("");
    setWeight("");
    api
      .get<Named[]>("/customers", { params: { limit: 500 } })
      .then((r) => setCustomers(r.data))
      .catch(() => setCustomers([]));
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/sales/targets", {
        scope,
        // The scope decides which party is named, and the server refuses a
        // target that names the wrong one — so only the relevant id is sent.
        customer_id: scope === "customer" && customerId ? Number(customerId) : null,
        seller_id: scope === "seller" && sellerId ? Number(sellerId) : null,
        period_start: from,
        period_end: to,
        label: label || null,
        target_amount: amount || null,
        target_weight_g: weight || null,
      });
      toast("success", "Target set");
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not set that target"));
    } finally {
      setBusy(false);
    }
  };

  const ready =
    (amount || weight) &&
    to >= from &&
    (scope === "company" ||
      (scope === "customer" && customerId) ||
      (scope === "seller" && sellerId));

  return (
    <Modal open={open} onClose={onClose} title="Set a target">
      <form onSubmit={submit} className="space-y-4">
        <SelectField
          label="For"
          value={scope}
          onChange={(e) => setScope(e.target.value as Scope)}
          options={[
            { value: "company", label: "The whole shop" },
            { value: "customer", label: "One customer" },
            { value: "seller", label: "One salesman or broker" },
          ]}
        />
        {scope === "customer" && (
          <SelectField
            label="Customer"
            required
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            options={[
              { value: "", label: "Pick one…" },
              ...customers.map((c) => ({ value: c.id, label: c.name })),
            ]}
          />
        )}
        {scope === "seller" && (
          <SelectField
            label="Salesman or broker"
            required
            value={sellerId}
            onChange={(e) => setSellerId(e.target.value)}
            options={[
              { value: "", label: "Pick one…" },
              ...sellers.map((s) => ({ value: s.id, label: `${s.name} (${s.kind})` })),
            ]}
          />
        )}

        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="From"
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
          <TextField
            label="To"
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            error={to < from ? "The period ends before it starts" : null}
          />
        </div>
        <TextField
          label="Label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="August 2026"
          hint="Any period works — a month, a year, or the days before Eid"
        />

        {/* Both, either, but not neither. A gold business manages in money and
            in weight and they answer different questions: a month where the
            rate rose can beat a rupee target on flat trading. */}
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Target amount"
            type="number"
            step="0.01"
            min={0}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="optional"
          />
          <TextField
            label="Target weight (g)"
            type="number"
            step="0.001"
            min={0}
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
            placeholder="optional"
          />
        </div>
        {!amount && !weight && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-900">
            Set at least one. A target with neither figure cannot be missed or met.
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={busy || !ready}>
            {busy ? "Setting…" : "Set target"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

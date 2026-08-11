import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { SelectField, TextArea } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { FilterSelect, SearchBox, Toolbar } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

interface Design {
  id: number;
  design_no: string;
  tag_no: string | null;
  item_id: number;
  item_name: string | null;
  customer_id: number | null;
  customer_name: string | null;
  current_department_id: number | null;
  current_department_name: string | null;
  status: string;
}

interface Named {
  id: number;
  name: string;
}

const STATUSES = [
  { value: "in_production", label: "In production" },
  { value: "stocked", label: "Stocked" },
  { value: "sold", label: "Sold" },
  { value: "cancelled", label: "Cancelled" },
];

export function statusPill(status: string): string {
  switch (status) {
    case "in_production":
      return "bg-amber-100 text-amber-800";
    case "stocked":
      return "bg-emerald-100 text-emerald-800";
    case "sold":
      return "bg-slate-200 text-slate-700";
    default:
      return "bg-red-100 text-red-700";
  }
}

export function DesignsPage() {
  const [items, setItems] = useState<Design[]>([]);
  const [departments, setDepartments] = useState<Named[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [dept, setDept] = useState("");

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (status) params.status = status;
    if (dept) params.current_department_id = dept;
    api
      .get<Design[]>("/designs", { params })
      .then((r) => setItems(r.data))
      .catch((e) => setError(apiError(e, "Failed to load designs")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q, status, dept]);

  useEffect(() => {
    api
      .get<Named[]>("/departments", { params: { is_active: true } })
      .then((r) => setDepartments(r.data))
      .catch(() => setDepartments([]));
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Designs</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          New design
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Every piece on the floor, from the first department to the last. Open one to see where it
        is, who is holding it and what each stage cost.
      </p>
      <Toolbar>
        <SearchBox
          value={q}
          onChange={setQ}
          placeholder="Search design or tag number…"
          className="w-80"
        />
        <FilterSelect value={status} onChange={setStatus} options={STATUSES} allLabel="All statuses" />
        <FilterSelect
          value={dept}
          onChange={setDept}
          options={departments.map((d) => ({ value: String(d.id), label: d.name }))}
          allLabel="Anywhere"
        />
        <span className="ml-auto text-xs text-slate-500">{items.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {q || status || dept ? "No designs matching the filters." : "No designs yet."}
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Design</th>
                <th className="px-4 py-3">Tag</th>
                <th className="px-4 py-3">Item</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Currently at</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((d) => (
                <tr key={d.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono font-medium">
                    <Link to={`/designs/${d.id}`} className="text-brand-700 hover:underline">
                      {d.design_no}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">{d.tag_no ?? "—"}</td>
                  <td className="px-4 py-3">{d.item_name ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">{d.customer_name ?? "Stock"}</td>
                  <td className="px-4 py-3">
                    {d.current_department_name ? (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-800">
                        {d.current_department_name}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">In house</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${statusPill(d.status)}`}>
                      {d.status.replace("_", " ")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <NewDesignForm
        open={open}
        onClose={() => {
          setOpen(false);
          load();
        }}
      />
    </div>
  );
}

function NewDesignForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<Named[]>([]);
  const [customers, setCustomers] = useState<Named[]>([]);
  const [itemId, setItemId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [minted, setMinted] = useState<Design | null>(null);

  useEffect(() => {
    if (!open) return;
    setMinted(null);
    setNotes("");
    Promise.all([
      api.get<Named[]>("/items", { params: { is_active: true } }),
      api.get<Named[]>("/customers", { params: { limit: 500 } }),
    ])
      .then(([i, c]) => {
        setItems(i.data);
        setCustomers(c.data);
        setItemId((prev) => prev || String(i.data[0]?.id ?? ""));
      })
      .catch((e) => toast("error", apiError(e, "Could not load items")));
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post<Design>("/designs", {
        item_id: Number(itemId),
        customer_id: customerId ? Number(customerId) : null,
        notes: notes || null,
      });
      setMinted(r.data);
    } catch (err) {
      toast("error", apiError(err, "Could not mint design"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={minted ? "Design minted" : "New design"}>
      {minted ? (
        <div className="space-y-4">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 text-center">
            <p className="text-xs uppercase tracking-wide text-emerald-700">Design number</p>
            <p className="mt-1 font-mono text-3xl font-semibold text-emerald-900">
              {minted.design_no}
            </p>
            <p className="mt-2 text-xs text-emerald-800">
              Write this on the job card. Everything the piece does from here is filed under it.
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setMinted(null)}>
              Mint another
            </button>
            <Link className="btn-primary" to={`/designs/${minted.id}`}>
              Open {minted.design_no}
            </Link>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <SelectField
            label="Item"
            required
            value={itemId}
            onChange={(e) => setItemId(e.target.value)}
            options={items.map((i) => ({ value: i.id, label: i.name }))}
            hint="The item's abbreviation becomes the design number prefix"
          />
          <SelectField
            label="Customer"
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            options={[
              { value: "", label: "Stock — no customer" },
              ...customers.map((c) => ({ value: c.id, label: c.name })),
            ]}
            hint="Leave on stock unless this is a commission"
          />
          <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={busy || !itemId}>
              {busy ? "Minting…" : "Mint design"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

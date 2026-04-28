import { FormEvent, useEffect, useState } from "react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextField } from "@/components/Field";
import { SearchBox, FilterSelect, Toolbar } from "@/components/Toolbar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

interface InventoryItem {
  id: number;
  type: string;
  label: string;
  location: string | null;
  quantity: number;
  weight_g: string;
  weight_ct: string;
  purity: number | null;
  product_id: number | null;
}

const TYPES = [
  { value: "raw_gold", label: "Raw gold" },
  { value: "raw_stone", label: "Raw stone" },
  { value: "finished_product", label: "Finished product" },
  { value: "other", label: "Other" },
];

export function InventoryPage() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<InventoryItem | null>(null);
  const [deleting, setDeleting] = useState<InventoryItem | null>(null);
  const [busyDelete, setBusyDelete] = useState(false);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (type) params.type = type;
    api
      .get<InventoryItem[]>("/inventory", { params })
      .then((res) => setItems(res.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q, type]);

  const confirmDelete = async () => {
    if (!deleting) return;
    setBusyDelete(true);
    try {
      await api.delete(`/inventory/${deleting.id}`);
      toast("success", `Deleted ${deleting.label}`);
      setDeleting(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Delete failed"));
    } finally {
      setBusyDelete(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Inventory</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          New item
        </button>
      </div>
      <Toolbar>
        <SearchBox
          value={q}
          onChange={setQ}
          placeholder="Search by label or location…"
          className="w-72"
        />
        <FilterSelect value={type} onChange={setType} options={TYPES} allLabel="All types" />
        <span className="ml-auto text-xs text-slate-500">{items.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {q || type ? "No items matching the filters." : "No inventory yet."}
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Label</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-right">Gold (g)</th>
                <th className="px-4 py-3 text-right">Stone (ct)</th>
                <th className="px-4 py-3 text-right">Purity</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((i) => (
                <tr key={i.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{i.type}</span>
                  </td>
                  <td className="px-4 py-3 font-medium">{i.label}</td>
                  <td className="px-4 py-3 text-slate-500">{i.location ?? "—"}</td>
                  <td className="px-4 py-3 text-right">{i.quantity}</td>
                  <td className="px-4 py-3 text-right">{i.weight_g}</td>
                  <td className="px-4 py-3 text-right">{i.weight_ct}</td>
                  <td className="px-4 py-3 text-right">{i.purity ?? "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        className="text-xs text-brand-700 hover:underline"
                        onClick={() => setEditing(i)}
                      >
                        Edit
                      </button>
                      <button
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => setDeleting(i)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <InventoryForm
        open={open}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          load();
        }}
      />
      <InventoryForm
        open={!!editing}
        existing={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          load();
        }}
      />
      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.label ?? "item"}?`}
        description="Items referenced by stock movements cannot be deleted (RESTRICT). Adjust the stock to zero instead if you want to retire it."
        destructive
        confirmLabel="Delete"
        busy={busyDelete}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function InventoryForm({
  open,
  onClose,
  onSaved,
  existing,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  existing?: InventoryItem | null;
}) {
  const [type, setType] = useState("raw_gold");
  const [label, setLabel] = useState("");
  const [location, setLocation] = useState("");
  const [quantity, setQuantity] = useState("0");
  const [weightG, setWeightG] = useState("0");
  const [weightCt, setWeightCt] = useState("0");
  const [purity, setPurity] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setType(existing?.type ?? "raw_gold");
      setLabel(existing?.label ?? "");
      setLocation(existing?.location ?? "");
      setQuantity(String(existing?.quantity ?? 0));
      setWeightG(existing?.weight_g ?? "0");
      setWeightCt(existing?.weight_ct ?? "0");
      setPurity(existing?.purity ? String(existing.purity) : "");
    }
  }, [open, existing]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body = {
        type,
        label,
        location: location || null,
        quantity: parseInt(quantity || "0", 10),
        weight_g: weightG || "0",
        weight_ct: weightCt || "0",
        purity: purity ? parseInt(purity, 10) : null,
      };
      if (existing) {
        await api.patch(`/inventory/${existing.id}`, body);
        toast("success", `"${label}" updated`);
      } else {
        await api.post("/inventory", body);
        toast("success", `Inventory "${label}" added`);
      }
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not save inventory item"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={existing ? "Edit inventory item" : "New inventory item"}>
      <form onSubmit={submit} className="space-y-4">
        <SelectField
          label="Type"
          required
          options={TYPES}
          value={type}
          onChange={(e) => setType(e.target.value)}
        />
        <TextField
          label="Label"
          required
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="e.g. 22k bullion"
        />
        <TextField label="Location" value={location} onChange={(e) => setLocation(e.target.value)} />
        <div className="grid grid-cols-3 gap-3">
          <TextField
            label="Quantity"
            type="number"
            min={0}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
          <TextField
            label="Gold (g)"
            type="number"
            step="0.0001"
            min={0}
            value={weightG}
            onChange={(e) => setWeightG(e.target.value)}
          />
          <TextField
            label="Stone (ct)"
            type="number"
            step="0.0001"
            min={0}
            value={weightCt}
            onChange={(e) => setWeightCt(e.target.value)}
          />
        </div>
        <TextField
          label="Purity (1–24)"
          type="number"
          min={1}
          max={24}
          value={purity}
          onChange={(e) => setPurity(e.target.value)}
          hint="Only for raw_gold"
        />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting || !label}>
            {submitting ? "Saving…" : existing ? "Save changes" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

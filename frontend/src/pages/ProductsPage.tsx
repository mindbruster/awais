import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextField, TextArea } from "@/components/Field";
import { SearchBox, FilterSelect, Toolbar } from "@/components/Toolbar";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

interface Product {
  id: number;
  serial_no: string;
  name: string;
  category: string | null;
  description: string | null;
  gold_weight_g: string;
  gold_purity: number | null;
  stone_weight_ct: string;
  total_cost: string;
  status: string;
  image_url: string | null;
}

const STATUS = [
  { value: "in_production", label: "In production" },
  { value: "in_stock", label: "In stock" },
  { value: "sold", label: "Sold" },
  { value: "on_approval", label: "On approval" },
];

export function ProductsPage() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [deleting, setDeleting] = useState<Product | null>(null);
  const [q, setQ] = useState("");
  // Backend products list doesn't filter by status; we filter client-side for now.
  const [statusFilter, setStatusFilter] = useState("");

  const load = () => {
    setLoading(true);
    api
      .get<Product[]>("/products", { params: q ? { q } : {} })
      .then((res) => setItems(res.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q]);

  const confirmDelete = async (password: string) => {
    if (!deleting) return;
    try {
      await api.delete(`/products/${deleting.id}`, {
        headers: { "X-Confirm-Password": password },
      });
      toast("success", `Deleted ${deleting.serial_no}`);
      setDeleting(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Delete failed"));
    }
  };

  const filtered = statusFilter ? items.filter((p) => p.status === statusFilter) : items;

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Products</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          New product
        </button>
      </div>
      <Toolbar>
        <SearchBox
          value={q}
          onChange={setQ}
          placeholder="Search by serial, name, category…"
          className="w-80"
        />
        <FilterSelect
          value={statusFilter}
          onChange={setStatusFilter}
          options={STATUS}
          allLabel="All statuses"
        />
        <span className="ml-auto text-xs text-slate-500">{filtered.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && filtered.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {q || statusFilter ? "No products matching the filters." : "No products yet."}
          </div>
        )}
        {filtered.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Image</th>
                <th className="px-4 py-3">Serial</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Category</th>
                <th className="px-4 py-3 text-right">Gold (g)</th>
                <th className="px-4 py-3 text-right">Stone (ct)</th>
                <th className="px-4 py-3 text-right">Cost</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    {p.image_url ? (
                      <img
                        src={`http://localhost:8000${p.image_url}`}
                        alt={p.name}
                        className="h-10 w-10 rounded object-cover"
                      />
                    ) : (
                      <div className="h-10 w-10 rounded bg-slate-100" />
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    <Link to={`/products/${p.id}`} className="text-brand-700 hover:underline">
                      {p.serial_no}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{p.name}</td>
                  <td className="px-4 py-3 text-slate-500">{p.category ?? "—"}</td>
                  <td className="px-4 py-3 text-right">{p.gold_weight_g}</td>
                  <td className="px-4 py-3 text-right">{p.stone_weight_ct}</td>
                  <td className="px-4 py-3 text-right">{p.total_cost}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        className="text-xs text-brand-700 hover:underline"
                        onClick={() => setEditing(p)}
                      >
                        Edit
                      </button>
                      <button
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => setDeleting(p)}
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

      <ProductForm
        open={open}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          load();
        }}
      />
      <ProductForm
        open={!!editing}
        existing={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          load();
        }}
      />
      <PasswordConfirm
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.serial_no ?? "product"}?`}
        description="Confirm with your password to delete this product permanently."
        confirmLabel="Delete product"
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function ProductForm({
  open,
  onClose,
  onSaved,
  existing,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  existing?: Product | null;
}) {
  const [name, setName] = useState("");
  const [serial, setSerial] = useState("");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [goldG, setGoldG] = useState("0");
  const [purity, setPurity] = useState("22");
  const [stoneCt, setStoneCt] = useState("0");
  const [status, setStatus] = useState("in_stock");
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setName(existing?.name ?? "");
      setSerial(existing?.serial_no ?? "");
      setCategory(existing?.category ?? "");
      setDescription(existing?.description ?? "");
      setGoldG(existing?.gold_weight_g ?? "0");
      setPurity(existing?.gold_purity ? String(existing.gold_purity) : "22");
      setStoneCt(existing?.stone_weight_ct ?? "0");
      setStatus(existing?.status ?? "in_stock");
      if (fileRef.current) fileRef.current.value = "";
    }
  }, [open, existing]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body = {
        name,
        serial_no: serial || null,
        category: category || null,
        description: description || null,
        gold_weight_g: goldG || "0",
        gold_purity: purity ? parseInt(purity, 10) : null,
        stone_weight_ct: stoneCt || "0",
        status,
      };
      let productId: number;
      if (existing) {
        const { data } = await api.patch<Product>(`/products/${existing.id}`, body);
        productId = data.id;
        toast("success", `"${data.serial_no}" updated`);
      } else {
        const { data } = await api.post<Product>("/products", body);
        productId = data.id;
        toast("success", `Product "${data.serial_no}" created`);
      }
      const file = fileRef.current?.files?.[0];
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        await api.post(`/products/${productId}/image`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      }
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not save product"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={existing ? "Edit product" : "New product"} widthClass="max-w-xl">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
          <TextField
            label="Serial #"
            value={serial}
            onChange={(e) => setSerial(e.target.value)}
            hint={existing ? "Edit with care" : "Auto-generated if blank"}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="ring / chain / earring …"
          />
          <SelectField
            label="Status"
            options={STATUS}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          />
        </div>
        <TextArea
          label="Description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="grid grid-cols-3 gap-3">
          <TextField
            label="Gold (g)"
            type="number"
            step="0.0001"
            min={0}
            value={goldG}
            onChange={(e) => setGoldG(e.target.value)}
          />
          <TextField
            label="Purity"
            type="number"
            min={1}
            max={24}
            value={purity}
            onChange={(e) => setPurity(e.target.value)}
          />
          <TextField
            label="Stone (ct)"
            type="number"
            step="0.0001"
            min={0}
            value={stoneCt}
            onChange={(e) => setStoneCt(e.target.value)}
          />
        </div>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">
            {existing?.image_url ? "Replace image (optional)" : "Image (optional)"}
          </span>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-200"
          />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting || !name}>
            {submitting ? "Saving…" : existing ? "Save changes" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextField, TextArea } from "@/components/Field";
import { SearchBox, FilterSelect, Toolbar } from "@/components/Toolbar";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { CURRENCY_OPTIONS, Currency, fmtMoney } from "@/lib/money";

interface Stone {
  id: number;
  name: string;
  kind: string;
  cut: string | null;
  color: string | null;
  clarity: string | null;
  default_rate_per_ct: string | null;
  currency: Currency;
  notes: string | null;
}

const KINDS = [
  { value: "diamond", label: "Diamond" },
  { value: "ruby", label: "Ruby" },
  { value: "emerald", label: "Emerald" },
  { value: "sapphire", label: "Sapphire" },
  { value: "pearl", label: "Pearl" },
  { value: "other", label: "Other" },
];

export function StonesPage() {
  const [items, setItems] = useState<Stone[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Stone | null>(null);
  const [deleting, setDeleting] = useState<Stone | null>(null);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (kind) params.kind = kind;
    api
      .get<Stone[]>("/stones", { params })
      .then((r) => setItems(r.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q, kind]);

  const confirmDelete = async (password: string) => {
    if (!deleting) return;
    try {
      await api.delete(`/stones/${deleting.id}`, {
        headers: { "X-Confirm-Password": password },
      });
      toast("success", `Deleted ${deleting.name}`);
      setDeleting(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Delete failed"));
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Stones</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          New stone
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Master catalogue of stone types. Used when adding stones to a finished product.
      </p>
      <Toolbar>
        <SearchBox
          value={q}
          onChange={setQ}
          placeholder="Search name, cut, color, clarity…"
          className="w-80"
        />
        <FilterSelect value={kind} onChange={setKind} options={KINDS} allLabel="All kinds" />
        <span className="ml-auto text-xs text-slate-500">{items.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {q || kind ? "No stones matching the filters." : "No stones yet."}
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Kind</th>
                <th className="px-4 py-3">Cut</th>
                <th className="px-4 py-3">Color</th>
                <th className="px-4 py-3">Clarity</th>
                <th className="px-4 py-3 text-right">Rate / ct</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((s) => (
                <tr key={s.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium">{s.name}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{s.kind}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{s.cut ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">{s.color ?? "—"}</td>
                  <td className="px-4 py-3 text-slate-600">{s.clarity ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono">
                    {s.default_rate_per_ct ? fmtMoney(s.default_rate_per_ct, s.currency) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        className="text-xs text-brand-700 hover:underline"
                        onClick={() => setEditing(s)}
                      >
                        Edit
                      </button>
                      <button
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => setDeleting(s)}
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

      <StoneForm
        open={open}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          load();
        }}
      />
      <StoneForm
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
        title={`Delete ${deleting?.name ?? "stone"}?`}
        description="Stone deletes require password confirmation. Stones referenced by any product breakdown cannot be deleted (FK RESTRICT)."
        confirmLabel="Delete"
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function StoneForm({
  open,
  onClose,
  onSaved,
  existing,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  existing?: Stone | null;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("diamond");
  const [cut, setCut] = useState("");
  const [color, setColor] = useState("");
  const [clarity, setClarity] = useState("");
  const [rate, setRate] = useState("");
  const [currency, setCurrency] = useState<Currency>("PKR");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setName(existing?.name ?? "");
      setKind(existing?.kind ?? "diamond");
      setCut(existing?.cut ?? "");
      setColor(existing?.color ?? "");
      setClarity(existing?.clarity ?? "");
      setRate(existing?.default_rate_per_ct ?? "");
      setCurrency(existing?.currency ?? "PKR");
      setNotes(existing?.notes ?? "");
    }
  }, [open, existing]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const body = {
        name,
        kind,
        cut: cut || null,
        color: color || null,
        clarity: clarity || null,
        default_rate_per_ct: rate || null,
        currency,
        notes: notes || null,
      };
      if (existing) {
        await api.patch(`/stones/${existing.id}`, body);
        toast("success", `"${name}" updated`);
      } else {
        await api.post("/stones", body);
        toast("success", `Stone "${name}" added`);
      }
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not save stone"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={existing ? "Edit stone" : "New stone"} widthClass="max-w-xl">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
          <SelectField
            label="Kind"
            required
            options={KINDS}
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <TextField
            label="Cut"
            value={cut}
            onChange={(e) => setCut(e.target.value)}
            placeholder="round, princess…"
          />
          <TextField
            label="Color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
            placeholder="D / E / F …"
          />
          <TextField
            label="Clarity"
            value={clarity}
            onChange={(e) => setClarity(e.target.value)}
            placeholder="VVS1, VS2 …"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Default rate / ct"
            type="number"
            step="0.0001"
            min={0}
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            hint="Used as a default when attaching to a product"
          />
          <SelectField
            label="Currency"
            options={CURRENCY_OPTIONS}
            value={currency}
            onChange={(e) => setCurrency(e.target.value as Currency)}
          />
        </div>
        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy || !name}>
            {busy ? "Saving…" : existing ? "Save changes" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

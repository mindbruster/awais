import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextField, TextArea } from "@/components/Field";
import { SearchBox, FilterSelect, Toolbar } from "@/components/Toolbar";
import { DepartmentsPage } from "@/pages/settings/DepartmentsPage";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

interface Vendor {
  id: number;
  name: string;
  type: string;
  department_id: number | null;
  department_name: string | null;
  phone: string | null;
  cnic: string | null;
  address: string | null;
  default_wastage_pct: string | null;
  effective_wastage_pct: string | null;
  opening_cash_balance: string;
  opening_gold_g: string;
  is_active: boolean;
  notes: string | null;
}

interface Department {
  id: number;
  name: string;
}

export function VendorsPage() {
  const [items, setItems] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Vendor | null>(null);
  const [deleting, setDeleting] = useState<Vendor | null>(null);
  const [busyDelete, setBusyDelete] = useState(false);
  const [q, setQ] = useState("");
  // The stage he handles — the only grouping of workers the shop has.
  const [departmentId, setDepartmentId] = useState("");
  const [departments, setDepartments] = useState<Department[]>([]);

  useEffect(() => {
    api
      .get<Department[]>("/departments", { params: { limit: "200", is_active: "true" } })
      .then((r) => setDepartments(r.data))
      .catch(() => setDepartments([]));
  }, []);

  const load = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (departmentId) params.department_id = departmentId;
    api
      .get<Vendor[]>("/vendors", { params })
      .then((res) => setItems(res.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q, departmentId]);

  const confirmDelete = async () => {
    if (!deleting) return;
    setBusyDelete(true);
    try {
      await api.delete(`/vendors/${deleting.id}`);
      toast("success", `Deleted ${deleting.name}`);
      setDeleting(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Delete failed"));
    } finally {
      setBusyDelete(false);
    }
  };

  return (
    <div className="space-y-10">
      <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Workers</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          New worker
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        The people the shop issues material to. Each one handles a stage and carries the wastage
        rate agreed with him.
      </p>
      <Toolbar>
        <SearchBox value={q} onChange={setQ} placeholder="Search by name, phone or CNIC…" className="w-72" />
        <FilterSelect
          value={departmentId}
          onChange={setDepartmentId}
          options={departments.map((d) => ({ value: String(d.id), label: d.name }))}
          allLabel="All stages"
        />
        <span className="ml-auto text-xs text-slate-500">{items.length} shown</span>
      </Toolbar>
      <div className="card mt-4 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {q || departmentId ? "No workers matching the filters." : "No workers yet."}
          </div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Stage</th>
                <th className="px-4 py-3">Wastage</th>
                <th className="px-4 py-3">Opening gold</th>
                <th className="px-4 py-3">Phone</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((v) => (
                <tr key={v.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium">
                    {/* The name is the way in to what he holds and is owed �
                        previously the list was the end of the road. */}
                    <Link to={`/vendors/`} className="text-brand-700 hover:underline">
                      {v.name}
                    </Link>
                    {!v.is_active && (
                      <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                        inactive
                      </span>
                    )}
                  </td>
                  {/* A worker with no department cannot be issued material —
                      he simply never appears in the dropdown on a design. Said
                      plainly here, because the symptom otherwise shows up two
                      screens away as an empty list. */}
                  <td className="px-4 py-3">
                    {v.department_name ?? (
                      <span className="text-amber-700" title="Set a department before this worker can be given work">
                        none — cannot be given work
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {v.effective_wastage_pct === null ? (
                      "—"
                    ) : (
                      <span title={v.default_wastage_pct ? "Agreed with this worker" : "Inherited from department"}>
                        {Number(v.effective_wastage_pct)}%
                        {!v.default_wastage_pct && (
                          <span className="ml-1 text-xs text-slate-400">dept</span>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {Number(v.opening_gold_g) === 0 ? "—" : `${Number(v.opening_gold_g)} g`}
                  </td>
                  <td className="px-4 py-3">{v.phone ?? "—"}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        className="text-xs text-brand-700 hover:underline"
                        onClick={() => setEditing(v)}
                      >
                        Edit
                      </button>
                      <button
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => setDeleting(v)}
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

      <VendorForm
        open={open}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          load();
        }}
      />
      <VendorForm
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
        title={`Delete ${deleting?.name ?? "worker"}?`}
        description="Jobs already assigned to this worker keep their record. If he has simply stopped working with the shop, switch him to inactive instead — that preserves his history."
        destructive
        confirmLabel="Delete"
        busy={busyDelete}
        onConfirm={confirmDelete}
      />
      </div>

      {/* The stages, on the same screen as the people who work them.
          They are kept as separate records underneath, and deliberately: the
          terms belong to the stage, not the man, so hiring a second maker means
          adding one worker rather than re-agreeing the shop's wastage rules.
          But there is no reason anyone should have to visit two screens to see
          a floor of three people. */}
      <DepartmentsPage />
    </div>
  );
}

function VendorForm({
  open,
  onClose,
  onSaved,
  existing,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  existing?: Vendor | null;
}) {
  const [name, setName] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [phone, setPhone] = useState("");
  const [cnic, setCnic] = useState("");
  const [address, setAddress] = useState("");
  const [wastage, setWastage] = useState("");
  const [openingCash, setOpeningCash] = useState("");
  const [openingGold, setOpeningGold] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [notes, setNotes] = useState("");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setName(existing?.name ?? "");
      setDepartmentId(existing?.department_id ? String(existing.department_id) : "");
      setPhone(existing?.phone ?? "");
      setCnic(existing?.cnic ?? "");
      setAddress(existing?.address ?? "");
      setWastage(existing?.default_wastage_pct ?? "");
      setOpeningCash(existing?.opening_cash_balance ?? "");
      setOpeningGold(existing?.opening_gold_g ?? "");
      setIsActive(existing ? existing.is_active : true);
      setNotes(existing?.notes ?? "");
      api
        .get<Department[]>("/departments", { params: { limit: "200", is_active: "true" } })
        .then((r) => setDepartments(r.data))
        .catch(() => setDepartments([]));
    }
  }, [open, existing]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body = {
        name,
        department_id: departmentId ? Number(departmentId) : null,
        phone: phone || null,
        cnic: cnic || null,
        address: address || null,
        default_wastage_pct: wastage === "" ? null : wastage,
        opening_cash_balance: openingCash || "0",
        opening_gold_g: openingGold || "0",
        is_active: isActive,
        notes: notes || null,
      };
      if (existing) {
        await api.patch(`/vendors/${existing.id}`, body);
        toast("success", `"${name}" updated`);
      } else {
        await api.post("/vendors", body);
        toast("success", `Worker "${name}" created`);
      }
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not save worker"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={existing ? "Edit worker" : "New worker"}>
      <form onSubmit={submit} className="space-y-4">
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
        <div className="grid grid-cols-2 gap-3">
          {/* Stage first, and required: it is what decides whether this worker
              can be picked on a job at all. The worker dropdown on a design is
              filtered by it, so one saved without a stage is invisible on every
              screen that matters. */}
          <SelectField
            label="Stage"
            required
            hint="Maker, stone fixer or lacker"
            options={[
              { value: "", label: "Select a stage…" },
              ...departments.map((d) => ({ value: d.id, label: d.name })),
            ]}
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
          />
          <TextField label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
          <TextField
            label="CNIC"
            value={cnic}
            onChange={(e) => setCnic(e.target.value)}
            placeholder="42101-1234567-1"
          />
          <TextField
            label="Agreed wastage %"
            type="number"
            step="0.001"
            hint="Leave blank to use the department's rate"
            value={wastage}
            onChange={(e) => setWastage(e.target.value)}
          />
          <TextField
            label="Opening gold (g)"
            type="number"
            step="0.0001"
            hint="Metal he already holds"
            value={openingGold}
            onChange={(e) => setOpeningGold(e.target.value)}
          />
          <TextField
            label="Opening cash balance"
            type="number"
            step="0.01"
            hint="Positive = owed to the worker"
            value={openingCash}
            onChange={(e) => setOpeningCash(e.target.value)}
          />
          <label className="flex items-center gap-2 pt-7 text-sm">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            <span className="font-medium text-slate-700">Active</span>
          </label>
        </div>
        <TextArea label="Address" value={address} onChange={(e) => setAddress(e.target.value)} />
        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
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

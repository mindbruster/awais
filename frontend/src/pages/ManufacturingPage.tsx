import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { TextArea } from "@/components/Field";
import { FilterSelect, Toolbar } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

const STAGES = [
  { value: "draft", label: "Draft" },
  { value: "karigar_assigned", label: "Karigar assigned" },
  { value: "karigar_received", label: "Karigar received" },
  { value: "stone_fixer_assigned", label: "Stone fixer assigned" },
  { value: "stone_fixer_received", label: "Stone fixer received" },
  { value: "polish_assigned", label: "Polish assigned" },
  { value: "polish_received", label: "Polish received" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

interface Job {
  id: number;
  job_no: string;
  stage: string;
  gold_assigned_g: string;
  jewelry_received_g: string;
  karigar_loss_g: string;
  stones_used_ct: string;
  polish_loss_g: string;
  product_id: number | null;
}

const STAGE_COLOR: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  karigar_assigned: "bg-amber-100 text-amber-800",
  karigar_received: "bg-amber-100 text-amber-800",
  stone_fixer_assigned: "bg-blue-100 text-blue-800",
  stone_fixer_received: "bg-blue-100 text-blue-800",
  polish_assigned: "bg-violet-100 text-violet-800",
  polish_received: "bg-violet-100 text-violet-800",
  completed: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-red-100 text-red-700",
};

export function ManufacturingPage() {
  const [items, setItems] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [stage, setStage] = useState("");

  const load = () => {
    setLoading(true);
    api
      .get<Job[]>("/manufacturing", { params: stage ? { stage } : {} })
      .then((res) => setItems(res.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [stage]);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Manufacturing</h1>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          New job
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Click a job to manage its stage transitions.
      </p>
      <Toolbar>
        <FilterSelect value={stage} onChange={setStage} options={STAGES} allLabel="All stages" />
        <span className="ml-auto text-xs text-slate-500">{items.length} shown</span>
      </Toolbar>
      <div className="card mt-6 overflow-hidden p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && items.length === 0 && (
          <div className="p-6 text-sm text-slate-500">No jobs yet.</div>
        )}
        {items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Job #</th>
                <th className="px-4 py-3">Stage</th>
                <th className="px-4 py-3 text-right">Gold assigned</th>
                <th className="px-4 py-3 text-right">Received</th>
                <th className="px-4 py-3 text-right">Karigar loss</th>
                <th className="px-4 py-3 text-right">Polish loss</th>
                <th className="px-4 py-3">Product</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((j) => (
                <tr key={j.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-xs">
                    <Link to={`/manufacturing/${j.id}`} className="text-brand-700 hover:underline">
                      {j.job_no}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        STAGE_COLOR[j.stage] ?? "bg-slate-100"
                      }`}
                    >
                      {j.stage}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">{j.gold_assigned_g} g</td>
                  <td className="px-4 py-3 text-right">{j.jewelry_received_g} g</td>
                  <td className="px-4 py-3 text-right text-red-600">{j.karigar_loss_g} g</td>
                  <td className="px-4 py-3 text-right text-red-600">{j.polish_loss_g} g</td>
                  <td className="px-4 py-3 text-slate-500">
                    {j.product_id ? `#${j.product_id}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <NewJobModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={() => {
          setOpen(false);
          load();
        }}
      />
    </div>
  );
}

function NewJobModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.post("/manufacturing", { notes: notes || null });
      toast("success", "Job opened");
      setNotes("");
      onCreated();
    } catch (err) {
      toast("error", apiError(err, "Could not open job"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Open manufacturing job">
      <form onSubmit={submit} className="space-y-4">
        <TextArea
          label="Notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          hint="Once open, you'll assign karigar, stones and polish on the job page."
        />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Opening…" : "Open job"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

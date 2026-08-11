import { FormEvent, ReactNode, useEffect, useState } from "react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { SearchBox, Toolbar } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

export type MasterRow = { id: number; [key: string]: any };

export interface MasterField {
  key: string;
  label: string;
  type?: "text" | "number" | "date" | "checkbox" | "select" | "textarea";
  options?: { value: string | number; label: string }[];
  required?: boolean;
  step?: string;
  placeholder?: string;
  hint?: string;
  /** Starting value for a new row. Defaults by type. */
  initial?: any;
  /** Custom cell renderer; falls back to the raw value. */
  render?: (row: MasterRow) => ReactNode;
  /** Keep out of the table (still editable in the form). */
  hideInTable?: boolean;
  /** Keep out of the form (still shown in the table) — e.g. derived fields. */
  hideInForm?: boolean;
  /** Narrow the form to two columns for compact fields. */
  half?: boolean;
}

interface Props {
  title: string;
  description: string;
  /** API path, without the leading slash convention of the client baseURL. */
  endpoint: string;
  /** Singular noun used in buttons and dialogs ("department"). */
  noun: string;
  fields: MasterField[];
  searchPlaceholder?: string;
  /** Column whose value names the row in dialogs. Defaults to `name`. */
  labelKey?: string;
  /** Extra filter controls rendered in the toolbar. */
  toolbarExtra?: ReactNode;
  /** Extra query params merged into every list request. */
  params?: Record<string, string>;
  /** Bumped by the parent to force a reload (e.g. after a related list changes). */
  refreshKey?: number;
  onChanged?: () => void;
}

function initialFor(f: MasterField) {
  if (f.initial !== undefined) return f.initial;
  if (f.type === "checkbox") return true;
  if (f.type === "select") return f.options?.[0]?.value ?? "";
  return "";
}

/**
 * The shared shell for every reference-data screen: list, search, create, edit
 * and a password-confirmed delete.
 *
 * These screens are identical apart from their columns, so they're configured
 * rather than copied — the same reason the API generates them from one
 * factory. Deleting a master silently reshapes historic reports, which is why
 * it asks for a password and why the server refuses when rows still point at it.
 */
export function MasterTable({
  title,
  description,
  endpoint,
  noun,
  fields,
  searchPlaceholder = "Search…",
  labelKey = "name",
  toolbarExtra,
  params,
  refreshKey = 0,
  onChanged,
}: Props) {
  const [rows, setRows] = useState<MasterRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<MasterRow | null>(null);
  const [deleting, setDeleting] = useState<MasterRow | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    const query: Record<string, string> = { ...(params ?? {}) };
    if (q) query.q = q;
    api
      .get<MasterRow[]>(endpoint, { params: query })
      .then((res) => setRows(res.data))
      .catch((e) => setError(apiError(e, "Failed to load")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q, endpoint, JSON.stringify(params ?? {}), refreshKey]);

  const afterChange = () => {
    load();
    onChanged?.();
  };

  const confirmDelete = async (password: string) => {
    if (!deleting) return;
    try {
      await api.delete(`${endpoint}/${deleting.id}`, {
        headers: { "X-Confirm-Password": password },
      });
      toast("success", `Deleted ${deleting[labelKey] ?? noun}`);
      setDeleting(null);
      afterChange();
    } catch (err) {
      toast("error", apiError(err, "Delete failed"));
    }
  };

  const tableFields = fields.filter((f) => !f.hideInTable);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          New {noun}
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">{description}</p>

      <Toolbar>
        <SearchBox value={q} onChange={setQ} placeholder={searchPlaceholder} className="w-72" />
        {toolbarExtra}
        <span className="ml-auto text-xs text-slate-500">{rows.length} shown</span>
      </Toolbar>

      <div className="card mt-4 overflow-x-auto p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && rows.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {q ? `No ${noun}s matching “${q}”.` : `No ${noun}s yet.`}
          </div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                {tableFields.map((f) => (
                  <th key={f.key} className="whitespace-nowrap px-4 py-3">
                    {f.label}
                  </th>
                ))}
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((row) => (
                <tr key={row.id} className="hover:bg-slate-50">
                  {tableFields.map((f) => (
                    <td key={f.key} className="px-4 py-3">
                      {f.render ? (
                        f.render(row)
                      ) : f.type === "checkbox" ? (
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs ${
                            row[f.key]
                              ? "bg-emerald-50 text-emerald-700"
                              : "bg-slate-100 text-slate-500"
                          }`}
                        >
                          {row[f.key] ? "Yes" : "No"}
                        </span>
                      ) : (
                        <span className={f.key === labelKey ? "font-medium" : ""}>
                          {row[f.key] === null || row[f.key] === undefined || row[f.key] === ""
                            ? "—"
                            : String(row[f.key])}
                        </span>
                      )}
                    </td>
                  ))}
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        className="text-xs text-brand-700 hover:underline"
                        onClick={() => setEditing(row)}
                      >
                        Edit
                      </button>
                      <button
                        className="text-xs text-red-600 hover:underline"
                        onClick={() => setDeleting(row)}
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

      <MasterForm
        open={creating}
        noun={noun}
        endpoint={endpoint}
        fields={fields}
        onClose={() => setCreating(false)}
        onSaved={() => {
          setCreating(false);
          afterChange();
        }}
      />
      <MasterForm
        open={!!editing}
        existing={editing}
        noun={noun}
        endpoint={endpoint}
        fields={fields}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          afterChange();
        }}
      />
      <PasswordConfirm
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.[labelKey] ?? noun}?`}
        description={`Records already referencing this ${noun} will block the delete. If it is simply no longer in use, edit it and switch it off instead — that keeps historic reports intact.`}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function MasterForm({
  open,
  onClose,
  onSaved,
  existing,
  endpoint,
  noun,
  fields,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  existing?: MasterRow | null;
  endpoint: string;
  noun: string;
  fields: MasterField[];
}) {
  const formFields = fields.filter((f) => !f.hideInForm);
  const [values, setValues] = useState<Record<string, any>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    const next: Record<string, any> = {};
    for (const f of formFields) {
      const current = existing?.[f.key];
      next[f.key] =
        current === undefined || current === null
          ? existing
            ? f.type === "checkbox"
              ? false
              : ""
            : initialFor(f)
          : current;
    }
    setValues(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, existing]);

  const set = (key: string, v: any) => setValues((prev) => ({ ...prev, [key]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body: Record<string, any> = {};
      for (const f of formFields) {
        const v = values[f.key];
        if (f.type === "checkbox") {
          body[f.key] = !!v;
        } else if (v === "" || v === undefined) {
          // Blank optional fields are cleared, not sent as empty strings —
          // the API validates types and "" is not a valid number or date.
          body[f.key] = f.required ? v : null;
        } else {
          body[f.key] = f.type === "select" && !isNaN(Number(v)) && f.options?.some((o) => typeof o.value === "number")
            ? Number(v)
            : v;
        }
      }
      if (existing) {
        await api.patch(`${endpoint}/${existing.id}`, body);
        toast("success", `${noun[0].toUpperCase()}${noun.slice(1)} updated`);
      } else {
        await api.post(endpoint, body);
        toast("success", `${noun[0].toUpperCase()}${noun.slice(1)} created`);
      }
      onSaved();
    } catch (err) {
      toast("error", apiError(err, `Could not save ${noun}`));
    } finally {
      setSubmitting(false);
    }
  };

  const requiredMissing = formFields.some(
    (f) => f.required && (values[f.key] === "" || values[f.key] === undefined),
  );

  return (
    <Modal open={open} onClose={onClose} title={existing ? `Edit ${noun}` : `New ${noun}`}>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          {formFields.map((f) => {
            const span = f.half ? "col-span-1" : "col-span-2";
            if (f.type === "checkbox") {
              return (
                <label key={f.key} className={`${span} flex items-center gap-2 pt-1 text-sm`}>
                  <input
                    type="checkbox"
                    checked={!!values[f.key]}
                    onChange={(e) => set(f.key, e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300"
                  />
                  <span className="font-medium text-slate-700">{f.label}</span>
                  {f.hint && <span className="text-xs text-slate-500">{f.hint}</span>}
                </label>
              );
            }
            if (f.type === "select") {
              return (
                <div key={f.key} className={span}>
                  <SelectField
                    label={f.label}
                    required={f.required}
                    hint={f.hint}
                    options={f.options ?? []}
                    value={values[f.key] ?? ""}
                    onChange={(e) => set(f.key, e.target.value)}
                  />
                </div>
              );
            }
            if (f.type === "textarea") {
              return (
                <div key={f.key} className={span}>
                  <TextArea
                    label={f.label}
                    hint={f.hint}
                    value={values[f.key] ?? ""}
                    onChange={(e) => set(f.key, e.target.value)}
                  />
                </div>
              );
            }
            return (
              <div key={f.key} className={span}>
                <TextField
                  label={f.label}
                  required={f.required}
                  hint={f.hint}
                  type={f.type ?? "text"}
                  step={f.step}
                  placeholder={f.placeholder}
                  value={values[f.key] ?? ""}
                  onChange={(e) => set(f.key, e.target.value)}
                />
              </div>
            );
          })}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={submitting || requiredMissing}>
            {submitting ? "Saving…" : existing ? "Save changes" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

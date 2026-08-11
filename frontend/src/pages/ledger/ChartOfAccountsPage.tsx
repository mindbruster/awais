import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { FilterSelect, SearchBox, Toolbar } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

interface Account {
  id: number;
  code: string;
  name: string;
  type: string;
  parent_id: number | null;
  parent_name: string | null;
  is_system: boolean;
  is_postable: boolean;
  is_active: boolean;
  notes: string | null;
}

const ACCOUNT_TYPES = [
  { value: "asset", label: "Asset" },
  { value: "liability", label: "Liability" },
  { value: "equity", label: "Equity" },
  { value: "income", label: "Income" },
  { value: "expense", label: "Expense" },
];

const TYPE_COLOR: Record<string, string> = {
  asset: "bg-emerald-100 text-emerald-800",
  liability: "bg-red-100 text-red-700",
  equity: "bg-brand-100 text-brand-700",
  income: "bg-blue-100 text-blue-800",
  expense: "bg-amber-100 text-amber-800",
};

/**
 * A parent whose child matched the filter is not itself in the result, so an
 * orphaned child is re-hung at the root rather than dropped — a search must
 * never hide the rows it just matched.
 */
function flatten(rows: Account[]): { account: Account; depth: number }[] {
  const present = new Set(rows.map((r) => r.id));
  const children = new Map<number | null, Account[]>();
  for (const a of rows) {
    const key = a.parent_id !== null && present.has(a.parent_id) ? a.parent_id : null;
    children.set(key, [...(children.get(key) ?? []), a]);
  }
  const out: { account: Account; depth: number }[] = [];
  const walk = (parent: number | null, depth: number) => {
    const kids = [...(children.get(parent) ?? [])].sort((x, y) => x.code.localeCompare(y.code));
    for (const a of kids) {
      out.push({ account: a, depth });
      walk(a.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

export function ChartOfAccountsPage() {
  const [rows, setRows] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    const params: Record<string, string> = {};
    if (q) params.q = q;
    if (type) params.type = type;
    api
      .get<Account[]>("/ledger/accounts", { params })
      .then((res) => setRows(res.data))
      .catch((e) => setError(apiError(e, "Failed to load the chart of accounts")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q, type]);

  const tree = useMemo(() => flatten(rows), [rows]);

  const confirmDelete = async (password: string) => {
    if (!deleting) return;
    try {
      await api.delete(`/ledger/accounts/${deleting.id}`, {
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
        <h1 className="text-2xl font-semibold text-slate-900">Chart of accounts</h1>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          New account
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Every posting lands on one of these. Headings group their children and are never posted
        to; the accounts marked <span className="font-medium">system</span> are the ones automatic
        posting looks up by code.
      </p>

      <Toolbar>
        <SearchBox value={q} onChange={setQ} placeholder="Search code or name…" className="w-72" />
        <FilterSelect value={type} onChange={setType} options={ACCOUNT_TYPES} allLabel="All types" />
        <span className="ml-auto text-xs text-slate-500">{rows.length} accounts</span>
      </Toolbar>

      <div className="card mt-4 overflow-x-auto p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && rows.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {q || type ? "No accounts matching the filters." : "No accounts yet."}
          </div>
        )}
        {rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Code</th>
                <th className="px-4 py-3">Account</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Flags</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tree.map(({ account: a, depth }) => (
                <tr key={a.id} className="hover:bg-slate-50">
                  <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-slate-500">
                    {a.code}
                  </td>
                  <td className="px-4 py-2.5">
                    <span style={{ paddingLeft: depth * 18 }} className="inline-block">
                      <span
                        className={a.is_postable ? "font-medium" : "font-semibold text-slate-500"}
                      >
                        {a.name}
                      </span>
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        TYPE_COLOR[a.type] ?? "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {a.type}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5">
                    <div className="flex gap-1.5">
                      {a.is_system && (
                        <span
                          className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-white"
                          title="Automatic posting resolves this account by its code"
                        >
                          system
                        </span>
                      )}
                      {!a.is_postable && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                          heading
                        </span>
                      )}
                      {!a.is_active && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                          inactive
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        className="text-xs text-brand-700 hover:underline"
                        onClick={() => setEditing(a)}
                      >
                        Edit
                      </button>
                      {!a.is_system && (
                        <button
                          className="text-xs text-red-600 hover:underline"
                          onClick={() => setDeleting(a)}
                        >
                          Delete
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

      <AccountForm
        open={creating}
        accounts={rows}
        onClose={() => setCreating(false)}
        onSaved={() => {
          setCreating(false);
          load();
        }}
      />
      <AccountForm
        open={!!editing}
        existing={editing}
        accounts={rows}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          load();
        }}
      />
      <PasswordConfirm
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.name ?? "account"}?`}
        description="The ledger is append-only, so an account that already carries postings or child accounts cannot be deleted. If it is simply out of use, edit it and switch it off — that keeps every historic statement readable."
        confirmLabel="Delete"
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function AccountForm({
  open,
  onClose,
  onSaved,
  existing,
  accounts,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  existing?: Account | null;
  accounts: Account[];
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState("asset");
  const [parentId, setParentId] = useState("");
  const [isPostable, setIsPostable] = useState(true);
  const [isActive, setIsActive] = useState(true);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setCode(existing?.code ?? "");
    setName(existing?.name ?? "");
    setType(existing?.type ?? "asset");
    setParentId(existing?.parent_id ? String(existing.parent_id) : "");
    setIsPostable(existing ? existing.is_postable : true);
    setIsActive(existing ? existing.is_active : true);
    setNotes(existing?.notes ?? "");
  }, [open, existing]);

  const parentOptions = [
    { value: "", label: "—" },
    ...accounts
      .filter((a) => a.id !== existing?.id)
      .map((a) => ({ value: a.id, label: `${a.code} — ${a.name}` })),
  ];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        code,
        name,
        parent_id: parentId ? Number(parentId) : null,
        is_postable: isPostable,
        is_active: isActive,
        notes: notes || null,
      };
      if (existing) {
        await api.patch(`/ledger/accounts/${existing.id}`, body);
        toast("success", `"${name}" updated`);
      } else {
        await api.post("/ledger/accounts", { ...body, type });
        toast("success", `Account "${name}" created`);
      }
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not save account"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={existing ? "Edit account" : "New account"}>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Code"
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="1170"
            hint={existing?.is_system ? "System accounts keep their code" : undefined}
            disabled={existing?.is_system}
          />
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
          {existing ? (
            <TextField label="Type" value={existing.type} disabled hint="Set when created" />
          ) : (
            <SelectField
              label="Type"
              required
              options={ACCOUNT_TYPES}
              value={type}
              onChange={(e) => setType(e.target.value)}
            />
          )}
          <SelectField
            label="Sits under"
            required={!existing || existing.parent_id !== null}
            hint="The heading this account belongs to"
            options={parentOptions}
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
          />
          <label className="flex items-center gap-2 pt-1 text-sm">
            <input
              type="checkbox"
              checked={isPostable}
              onChange={(e) => setIsPostable(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            <span className="font-medium text-slate-700">Postable</span>
            <span className="text-xs text-slate-500">off = heading</span>
          </label>
          <label className="flex items-center gap-2 pt-1 text-sm">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            <span className="font-medium text-slate-700">Active</span>
          </label>
        </div>
        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn-primary"
            disabled={
              submitting ||
              !code ||
              !name ||
              // A root that is not the seeded root would leave the tree with two
              // tops, and no report knows which one to walk.
              (!parentId && existing?.parent_id !== null)
            }
          >
            {submitting ? "Saving…" : existing ? "Save changes" : "Create"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

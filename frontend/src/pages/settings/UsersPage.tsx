import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { Modal } from "@/components/Modal";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { SelectField, TextField } from "@/components/Field";
import { toast } from "@/components/Toast";
import { useAuthStore } from "@/store/auth";

/**
 * Who can sign in, and what each of them may reach.
 *
 * The roles existed before this screen did and nothing could put a person on
 * one, which made the whole permission system decoration. Four roles ship;
 * more can be built by a super admin under Modules & roles.
 *
 * Three refusals here come from the server and are worth knowing before you
 * meet them: you cannot deactivate or re-role yourself (that is how a shop
 * locks itself out of its own user list), only a super admin may touch a super
 * admin, and setting somebody else's password makes you re-enter your own.
 */

type Role = { id: number; name: string; description?: string | null };
type User = {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  role: Role;
};

export function UsersPage() {
  const me = useAuthStore((s) => s.user);
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<User | null>(null);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const load = useCallback(() => {
    api
      .get<User[]>("/users")
      .then((r) => setUsers(r.data))
      .catch((e) => setError(apiError(e, "Could not load users")));
    // Roles come from the admin router, which a plain admin may read even
    // though only a super admin may change them.
    api
      .get<Role[]>("/admin/roles")
      .then((r) => setRoles(r.data))
      .catch(() => setRoles([]));
  }, []);

  useEffect(load, [load]);

  const save = async (body: Record<string, unknown>, id?: number) => {
    try {
      if (id) await api.patch(`/users/${id}`, body);
      else await api.post("/users", body);
      toast("success", id ? "Saved" : "User added");
      setEditing(null);
      setCreating(false);
      load();
    } catch (e) {
      toast("error", apiError(e, "Could not save"));
      throw e;
    }
  };

  const resetPassword = async (password: string) => {
    if (!resetting) return;
    try {
      await api.patch(
        `/users/${resetting.id}`,
        { password: newPassword },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `Password set for ${resetting.full_name}`);
      setResetting(null);
      setNewPassword("");
    } catch (e) {
      toast("error", apiError(e, "Could not set the password"));
      throw e;
    }
  };

  const remove = async (password: string) => {
    if (!deleting) return;
    try {
      await api.delete(`/users/${deleting.id}`, {
        headers: { "X-Confirm-Password": password },
      });
      toast("success", `${deleting.full_name} removed`);
      setDeleting(null);
      load();
    } catch (e) {
      toast("error", apiError(e, "Could not remove this user"));
      throw e;
    }
  };

  if (error) return <div className="card text-sm text-red-600">{error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">People</h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-500">
            Who can sign in, and what each of them may reach. A role decides what
            somebody sees and what the server will accept from them — the two are
            never out of step, so a screen nobody can open is also an endpoint
            nobody can call.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setCreating(true)}>
          Add someone
        </button>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2.5 font-medium">Name</th>
              <th className="px-4 py-2.5 font-medium">Email</th>
              <th className="px-4 py-2.5 font-medium">Role</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "bg-slate-50/60"}>
                <td className="px-4 py-2.5 font-medium text-slate-900">
                  {u.full_name}
                  {u.id === me?.id && (
                    <span className="ml-2 text-xs font-normal text-slate-400">you</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-slate-600">{u.email}</td>
                <td className="px-4 py-2.5 capitalize text-slate-600">
                  {u.role.name.replace(/_/g, " ")}
                </td>
                <td className="px-4 py-2.5">
                  {u.is_active ? (
                    <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                      Active
                    </span>
                  ) : (
                    <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600">
                      Signed out for good
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex justify-end gap-1">
                    <button className="btn-ghost" onClick={() => setEditing(u)}>
                      Edit
                    </button>
                    <button
                      className="btn-ghost"
                      onClick={() => {
                        setNewPassword("");
                        setResetting(u);
                      }}
                    >
                      Set password
                    </button>
                    {u.id !== me?.id && (
                      <button className="btn-ghost text-red-600" onClick={() => setDeleting(u)}>
                        Remove
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  Nobody yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs leading-relaxed text-slate-500">
        Removing somebody deletes the account. To stop a person signing in while
        keeping their name on what they did, edit them and turn Active off
        instead — the audit log and every document they touched still name them.
      </p>

      <UserForm
        open={creating || !!editing}
        user={editing}
        roles={roles}
        isSelf={editing?.id === me?.id}
        onClose={() => {
          setCreating(false);
          setEditing(null);
        }}
        onSave={save}
      />

      <PasswordConfirm
        open={!!resetting}
        onClose={() => setResetting(null)}
        title={`Set a password for ${resetting?.full_name ?? ""}`}
        description="Setting somebody else's password is an account takeover even when it is a favour, so you re-enter your own — the audit line then names somebody who was present."
        confirmLabel="Set password"
        destructive={false}
        extraValid={newPassword.length >= 6}
        onConfirm={resetPassword}
        extra={
          <TextField
            label="New password for them"
            type="text"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            hint="At least 6 characters. Shown as you type, because you have to read it out to them."
            required
          />
        }
      />

      <PasswordConfirm
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={`Remove ${deleting?.full_name ?? ""}?`}
        description="The account is deleted and they can no longer sign in. Documents they created keep their name."
        confirmLabel="Remove"
        onConfirm={remove}
      />
    </div>
  );
}

function UserForm({
  open,
  user,
  roles,
  isSelf,
  onClose,
  onSave,
}: {
  open: boolean;
  user: User | null;
  roles: Role[];
  isSelf: boolean;
  onClose: () => void;
  onSave: (body: Record<string, unknown>, id?: number) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [roleId, setRoleId] = useState("");
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(user?.full_name ?? "");
    setEmail(user?.email ?? "");
    setRoleId(user ? String(user.role.id) : "");
    setActive(user?.is_active ?? true);
    setPassword("");
  }, [open, user]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (user) {
        // Email is left out on purpose: it is the login, and changing it under
        // somebody is how a person is locked out of an account that still
        // appears to be theirs. Remove and re-add instead.
        await onSave(
          { full_name: name, role_id: Number(roleId), is_active: active },
          user.id,
        );
      } else {
        await onSave({
          full_name: name,
          email,
          password,
          role_id: Number(roleId),
          is_active: active,
        });
      }
    } catch {
      /* toast already shown; keep the form open with what was typed */
    } finally {
      setBusy(false);
    }
  };

  const valid =
    name.trim().length > 0 &&
    roleId !== "" &&
    (user ? true : email.trim().length > 0 && password.length >= 6);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={user ? `Edit ${user.full_name}` : "Add someone"}
      widthClass="max-w-md"
    >
      <form onSubmit={submit} className="space-y-3">
        <TextField
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        {user ? (
          <div>
            <p className="eyebrow">Email</p>
            <p className="mt-0.5 text-sm text-slate-600">{user.email}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              The login cannot be changed. Remove the account and add it again if
              somebody's address really has changed.
            </p>
          </div>
        ) : (
          <>
            <TextField
              label="Email"
              type="email"
              autoComplete="off"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              hint="This is how they sign in."
              required
            />
            <TextField
              label="First password"
              type="text"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              hint="At least 6 characters. Tell them to change it themselves — the button sits under their name in the sidebar."
              required
            />
          </>
        )}
        <SelectField
          label="Role"
          value={roleId}
          onChange={(e) => setRoleId(e.target.value)}
          disabled={isSelf}
          hint={
            isSelf
              ? "You cannot change your own role — it would remove the permission that let you do it."
              : "What this person may reach. Roles are set up under Modules & roles."
          }
          options={roles.map((r) => ({
            value: String(r.id),
            label: r.name.replace(/_/g, " "),
          }))}
          required
        />
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={active}
            disabled={isSelf}
            onChange={(e) => setActive(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300"
          />
          Can sign in
          {isSelf && (
            <span className="text-xs text-slate-500">
              — you cannot deactivate yourself
            </span>
          )}
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={!valid || busy}>
            {busy ? "Saving…" : user ? "Save" : "Add"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

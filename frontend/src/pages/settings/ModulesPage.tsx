/**
 * The super admin panel: which modules this shop uses, and what each role may do.
 *
 * Both sit behind the `superadmin` role rather than behind a permission, and
 * that is the point of the tier. A permission that could be granted to widen
 * who may grant permissions is not a control, it is a formality — so the two
 * things that decide what everybody else can reach belong to somebody who is
 * not also running the counter.
 *
 * A switch that cannot be used is shown greyed **with its reason**, not hidden.
 * "Manufacturing cannot be switched off" tells nobody anything; "3 jobs still
 * out with workers, 1,272 fine g outside" tells them exactly what to settle.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

interface Blocker { what: string; where: string | null }

interface Module {
  id: number;
  key: string;
  label: string;
  enabled: boolean;
  can_disable: boolean;
  can_switch_off: boolean;
  blockers: Blocker[];
  notes: string | null;
}

interface Role {
  id: number;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
  users: number;
}

interface Permission { key: string; resource: string; action: string }

export function ModulesPage() {
  const [modules, setModules] = useState<Module[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [catalogue, setCatalogue] = useState<Permission[]>([]);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Module | null>(null);
  const [tab, setTab] = useState<"modules" | "roles">("modules");

  const load = useCallback(() => {
    api
      .get<Module[]>("/admin/modules")
      .then((r) => setModules(r.data))
      .catch((e) => {
        if (e?.response?.status === 403) setForbidden(true);
        else setError(apiError(e, "Could not load modules"));
      });
    api.get<Role[]>("/admin/roles").then((r) => setRoles(r.data)).catch(() => {});
    api.get<Permission[]>("/admin/permissions").then((r) => setCatalogue(r.data)).catch(() => {});
  }, []);

  useEffect(load, [load]);

  if (forbidden)
    return (
      <div className="card">
        <h1 className="text-lg font-semibold text-slate-900">Super admin only</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          Modules and role permissions are managed by a super admin, not an admin.
          That separation is deliberate: an admin who could widen their own
          permissions would not really be limited by them.
        </p>
      </div>
    );
  if (error) return <div className="card text-sm text-red-600">{error}</div>;

  const toggle = async (m: Module, password: string) => {
    try {
      await api.patch(
        `/admin/modules/${m.key}`,
        { enabled: !m.enabled },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${m.label} switched ${m.enabled ? "off" : "on"}`);
      setPending(null);
      load();
    } catch (e) {
      toast("error", apiError(e, "Could not change the module"));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Modules & roles</h1>
        <p className="mt-1 text-sm text-slate-500">
          What this shop uses, and what each role may do. Switching a module off hides
          its screens <em>and</em> refuses its endpoints — not one without the other.
        </p>
      </div>

      <nav className="flex gap-1 border-b border-slate-200">
        {(["modules", "roles"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px rounded-t-lg border-b-2 px-4 py-2 text-sm font-medium capitalize transition ${
              tab === t ? "border-brand-600 text-brand-700"
                        : "border-transparent text-slate-500 hover:text-slate-800"}`}
          >
            {t}
          </button>
        ))}
      </nav>

      {tab === "modules" && (
        <div className="card overflow-hidden p-0">
          <ul className="divide-y divide-slate-100">
            {modules.map((m) => (
              <li key={m.key} className="flex flex-wrap items-start gap-4 px-5 py-4">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-900">{m.label}</p>
                  {!m.can_disable && (
                    <p className="mt-0.5 text-[11px] text-slate-500">
                      Always on — without it there would be no way to switch anything
                      back on.
                    </p>
                  )}
                  {/* Named, not summarised. A person needs to know what to go
                      and settle, not that something unspecified is in the way. */}
                  {m.blockers.length > 0 && (
                    <ul className="mt-1 space-y-0.5">
                      {m.blockers.map((b, i) => (
                        <li key={i} className="text-[11px] text-amber-700">
                          {b.where ? (
                            <Link to={b.where} className="hover:underline">{b.what} →</Link>
                          ) : b.what}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <button
                  disabled={m.enabled && !m.can_switch_off}
                  onClick={() => setPending(m)}
                  title={
                    m.enabled && !m.can_switch_off
                      ? m.can_disable
                        ? "Settle what is listed first"
                        : "This module cannot be switched off"
                      : undefined
                  }
                  className={`flex-none rounded-full px-3 py-1 text-xs font-medium ring-1 transition ${
                    m.enabled
                      ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                      : "bg-slate-100 text-slate-500 ring-slate-200"
                  } ${m.enabled && !m.can_switch_off ? "cursor-not-allowed opacity-60" : ""}`}
                >
                  {m.enabled ? "On" : "Off"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {tab === "roles" && (
        <div className="space-y-3">
          {roles.map((r) => (
            <div key={r.id} className="card">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-slate-900">
                  {r.name}
                  {r.is_system && (
                    <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                      system
                    </span>
                  )}
                </p>
                <p className="text-xs text-slate-500">
                  {r.permissions.length} of {catalogue.length} permissions ·{" "}
                  {r.users} user{r.users === 1 ? "" : "s"}
                </p>
              </div>
              {r.description && (
                <p className="mt-0.5 text-xs text-slate-500">{r.description}</p>
              )}
              {r.name === "superadmin" && (
                <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                  Holds no permissions at all — its authority is its name, checked
                  directly, so nothing can strip it by accident and leave the shop with
                  no way back in.
                </p>
              )}
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-brand-400"
                  style={{
                    width: `${catalogue.length
                      ? (r.permissions.length / catalogue.length) * 100
                      : 0}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <PasswordConfirm
        open={!!pending}
        onClose={() => setPending(null)}
        title={`Switch ${pending?.label ?? ""} ${pending?.enabled ? "off" : "on"}?`}
        description={
          pending?.enabled
            ? "Its screens disappear and its endpoints refuse — for everyone, including anything that calls the API directly."
            : "Its screens and endpoints become available again to anyone whose role permits them."
        }
        confirmLabel={pending?.enabled ? "Switch off" : "Switch on"}
        onConfirm={async (pw) => {
          if (pending) await toggle(pending, pw);
        }}
      />
    </div>
  );
}

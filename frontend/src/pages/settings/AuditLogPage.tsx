/**
 * Who did what, and what it changed.
 *
 * Every action in the system has been writing here since audit logging was
 * added — issuing metal, receiving it, voiding a bill, cancelling a leg,
 * recording a payment — and none of it could be read from the app. A log
 * nobody can open is a log that only helps after somebody has already gone to
 * the database, which is the wrong half of the problem.
 *
 * Admin only, and deliberately so: it is a record of colleagues, and the
 * question it answers ("who cancelled that leg") is an owner's question.
 *
 * The details are shown expanded rather than behind a click. The whole value of
 * a line like `design.leg_receive` is the figures on it — what came back, what
 * was allowed, what was charged — and a row that shows only the verb tells the
 * reader nothing they could not have guessed.
 */
import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { SearchBox, Toolbar } from "@/components/Toolbar";
import { apiError } from "@/lib/api-error";

interface Entry {
  id: number;
  created_at: string;
  actor_user_id: number | null;
  actor_email: string | null;
  action: string;
  resource_type: string;
  resource_id: number | null;
  details: Record<string, unknown> | null;
  // Only the fields that moved, same keys on both sides. Null — not {} — when
  // the action was never recorded as a field change.
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  request_id: string | null;
}

// Actions that change money or metal, coloured so a page of routine edits does
// not read the same as a page of reversals.
const WEIGHTY = /(cancel|void|delete|reverse|write_off|split)/;

export function AuditLogPage() {
  const [rows, setRows] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState("");
  const [resource, setResource] = useState("");

  useEffect(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (action) params.action = action;
    if (resource) params.resource_type = resource;
    api
      .get<Entry[]>("/audit-log", { params })
      .then((r) => setRows(r.data))
      .catch((e) => setError(apiError(e, "Could not load the audit log")))
      .finally(() => setLoading(false));
  }, [action, resource]);

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Audit log</h1>
      <p className="mt-1 text-sm text-slate-500">
        Every action that changed something, who did it, and what it carried. Append-only — a
        correction is a new line, never an edit to an old one.
      </p>

      <Toolbar>
        <SearchBox
          value={action}
          onChange={setAction}
          placeholder="Exact action, e.g. design.leg_receive"
          className="w-72"
        />
        <SearchBox
          value={resource}
          onChange={setResource}
          placeholder="Resource, e.g. job_leg"
          className="w-56"
        />
        <span className="ml-auto text-xs text-slate-500">{rows.length} shown</span>
      </Toolbar>

      <div className="card mt-4 p-0">
        {loading && <div className="p-6 text-sm text-slate-500">Loading…</div>}
        {error && <div className="p-6 text-sm text-red-600">{error}</div>}
        {!loading && !error && rows.length === 0 && (
          <div className="p-6 text-sm text-slate-500">
            {action || resource ? "Nothing matches those filters." : "Nothing recorded yet."}
          </div>
        )}
        <ul className="divide-y divide-slate-100">
          {rows.map((e) => (
            <li key={e.id} className="px-5 py-3">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span
                  className={`font-mono text-xs ${
                    WEIGHTY.test(e.action) ? "font-semibold text-red-600" : "text-slate-700"
                  }`}
                >
                  {e.action}
                </span>
                <span className="text-xs text-slate-500">
                  {e.resource_type}
                  {e.resource_id !== null && ` #${e.resource_id}`}
                </span>
                <span className="ml-auto text-xs text-slate-400">
                  {e.actor_email ?? "system"} · {new Date(e.created_at).toLocaleString()}
                </span>
              </div>
              {/* The change itself, before the free-form context. An audit
                  line whose whole content is "the rate was edited" is a
                  notification; "99,999 → 9,999" is evidence, and it is the
                  first thing the reader is looking for. */}
              {(e.before || e.after) && (
                <div className="mt-1.5 space-y-0.5">
                  {Array.from(
                    new Set([
                      ...Object.keys(e.before ?? {}),
                      ...Object.keys(e.after ?? {}),
                    ]),
                  ).map((k) => {
                    const from = e.before?.[k];
                    const to = e.after?.[k];
                    return (
                      <div key={k} className="flex flex-wrap items-baseline gap-2 text-[11px]">
                        <span className="min-w-[7rem] text-slate-400">{k}</span>
                        {e.before && (
                          <span className="num text-slate-500 line-through decoration-slate-300">
                            {fmt(from)}
                          </span>
                        )}
                        {e.before && e.after && <span className="text-slate-300">→</span>}
                        {e.after && (
                          <span className="num font-medium text-slate-900">{fmt(to)}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              {e.reason && (
                <p className="mt-1 text-[11px] italic text-slate-500">“{e.reason}”</p>
              )}
              {e.details && Object.keys(e.details).length > 0 && (
                <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5">
                  {Object.entries(e.details).map(([k, v]) => (
                    <div key={k} className="flex items-baseline gap-1">
                      <dt className="text-[11px] text-slate-400">{k}</dt>
                      <dd className="num text-[11px] text-slate-700">
                        {fmt(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/**
 * A value as a person reads it.
 *
 * `null` prints as an em dash rather than the word "null": on a deletion every
 * cleared field would otherwise read as though somebody typed the word in.
 */
function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

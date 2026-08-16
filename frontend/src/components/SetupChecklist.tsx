/**
 * What still needs setting up, for a shop that has just opened the app.
 *
 * Every item is a live query against their own data, so the list empties
 * itself as they work and never congratulates them for something they haven't
 * done. It hides itself entirely once the required steps are complete — a
 * checklist that nags a shop already trading is a checklist they learn to
 * scroll past.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";

interface Step {
  key: string;
  title: string;
  detail: string;
  done: boolean;
  count: number;
  to: string;
  cta: string;
  optional: boolean;
}

interface Checklist {
  steps: Step[];
  done_count: number;
  total: number;
  required_done: number;
  required_total: number;
  ready: boolean;
  user_name: string | null;
}

const DISMISS_KEY = "setup-checklist-dismissed";

export function SetupChecklist() {
  const [data, setData] = useState<Checklist | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(DISMISS_KEY) === "1",
  );

  const load = useCallback(() => {
    api
      .get<Checklist>("/setup/checklist")
      .then((r) => {
        setData(r.data);
        // The first thing not done is the thing to do next, so it opens itself.
        const next = r.data.steps.find((s) => !s.done && !s.optional);
        setOpen(next?.key ?? null);
      })
      .catch(() => setData(null));
  }, []);

  useEffect(load, [load]);

  if (!data) return null;
  // Once the shop can actually trade, this disappears on its own.
  if (data.ready || dismissed) return null;

  const pct = Math.round((data.required_done / Math.max(data.required_total, 1)) * 100);

  return (
    <section className="card border-brand-200 bg-brand-50/40">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">
            {data.user_name ? `Let's get you set up, ${data.user_name.split(" ")[0]}` : "Let's get you set up"}
          </h2>
          <p className="mt-1 max-w-xl text-xs leading-relaxed text-slate-600">
            A few things need to exist before the shop can run — you can't mint a design without
            an item, and no metal can move without today's gold rate. This list is read from your
            own data, so it ticks itself off.
          </p>
        </div>
        <button
          className="flex-none text-xs text-slate-500 hover:text-slate-800 hover:underline"
          onClick={() => {
            localStorage.setItem(DISMISS_KEY, "1");
            setDismissed(true);
          }}
        >
          Hide this
        </button>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-brand-100">
          <div
            className="h-full rounded-full bg-brand-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="num flex-none text-xs font-medium text-brand-800">
          {data.required_done} of {data.required_total}
        </span>
      </div>

      <ol className="mt-4 space-y-1">
        {data.steps.map((s) => {
          const isOpen = open === s.key;
          return (
            <li key={s.key} className="rounded-xl bg-white/70">
              <button
                className="flex w-full items-center gap-3 px-3 py-2 text-left"
                onClick={() => setOpen(isOpen ? null : s.key)}
                aria-expanded={isOpen}
              >
                <span
                  className={`flex h-5 w-5 flex-none items-center justify-center rounded-full text-[11px] font-semibold ${
                    s.done
                      ? "bg-emerald-100 text-emerald-700"
                      : "border border-dashed border-slate-300 text-slate-400"
                  }`}
                  aria-hidden
                >
                  {s.done ? "✓" : ""}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={`block text-sm ${
                      s.done ? "text-slate-400 line-through" : "font-medium text-slate-900"
                    }`}
                  >
                    {s.title}
                  </span>
                </span>
                {s.optional && !s.done && (
                  <span className="flex-none text-[11px] text-slate-400">optional</span>
                )}
                {s.done && s.count > 0 && (
                  <span className="num flex-none text-xs text-slate-400">{s.count}</span>
                )}
              </button>
              {isOpen && (
                <div className="border-t border-slate-100 px-3 py-2.5">
                  <p className="text-xs leading-relaxed text-slate-600">{s.detail}</p>
                  <Link className="btn-primary mt-3 w-full sm:w-auto" to={s.to}>
                    {s.cta}
                  </Link>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

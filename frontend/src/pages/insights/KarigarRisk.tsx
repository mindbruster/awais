/**
 * Who to watch on the workshop floor, and why.
 *
 * The score is deliberately shown taken apart. An owner reading this is being
 * asked to have an awkward conversation with someone he has worked with for
 * years, and "the computer says 68" is not something he can put to a man —
 * so every component that fired is listed with the figure behind it and the
 * points it contributed. A number nobody can interrogate is a number nobody
 * acts on.
 */
import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { fmtWeight } from "@/lib/money";

interface Reason {
  code: string;
  label: string;
  detail: string;
  points: number;
}

interface Row {
  worker_id: number;
  worker_name: string;
  department: string | null;
  legs: number;
  gold_issued_g: string;
  excess_g: string;
  excess_rate_pct: string;
  avg_days_held: string | null;
  earlier_rate_pct: string | null;
  recent_rate_pct: string | null;
  open_legs: number;
  open_gold_g: string;
  oldest_open_days: number | null;
  score: number;
  band: "low" | "watch" | "high" | "insufficient";
  reasons: Reason[];
  narrative: string | null;
}

interface Report {
  days: number;
  min_legs: number;
  shop_excess_rate_pct: string;
  shop_avg_days_held: string | null;
  rows: Row[];
  scored_count: number;
  high_count: number;
  ai_enabled: boolean;
  ai_note: string | null;
}

function BandChip({ band }: { band: Row["band"] }) {
  if (band === "high")
    return (
      <span className="chip-owed">
        <span className="dot bg-red-500" aria-hidden />
        Worth a conversation
      </span>
    );
  if (band === "watch")
    return (
      <span className="chip-out">
        <span className="dot bg-amber-500" aria-hidden />
        Watch
      </span>
    );
  if (band === "insufficient")
    return <span className="chip-dead">Not enough work yet</span>;
  return (
    <span className="chip-back">
      <span className="dot bg-emerald-500" aria-hidden />
      Fine
    </span>
  );
}

export function KarigarRisk({ days }: { days: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set());

  useEffect(() => {
    let live = true;
    // The server takes 30–730; the shared window control on this page can sit
    // below that, so it is clamped here rather than sending a value the API
    // will reject and showing the operator an error about their own filter.
    const window = Math.min(730, Math.max(30, Number(days) || 180));
    api
      .get<Report>("/insights/karigar-risk", { params: { days: String(window) } })
      .then((r) => {
        if (!live) return;
        setReport(r.data);
        // Anything that needs attention starts open; the rest is one click away.
        setOpen(
          new Set(
            r.data.rows.filter((x) => x.band === "high").map((x) => x.worker_id),
          ),
        );
      })
      .catch((err) => {
        if (!live) return;
        if (err instanceof AxiosError && err.response?.status === 403) setForbidden(true);
        else setError(apiError(err, "Could not load the risk report"));
      });
    return () => {
      live = false;
    };
  }, [days]);

  if (forbidden) return null;

  const toggle = (id: number) =>
    setOpen((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const notable = report?.rows.filter((r) => r.band === "high" || r.band === "watch") ?? [];
  const quiet = report?.rows.filter((r) => r.band === "low" || r.band === "insufficient") ?? [];

  return (
    <section className="card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-700">Who to watch on the floor</h2>
        {report && (
          <span className="num text-xs text-slate-500">
            shop average {report.shop_excess_rate_pct}% past allowance
            {report.shop_avg_days_held ? ` · ${report.shop_avg_days_held} days a leg` : ""}
          </span>
        )}
      </div>
      <p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-500">
        Four things taken together — how far past his allowance a worker runs, whether that is
        getting worse, how long he sits on a job, and how much of your metal he is holding right
        now. The score is arithmetic, not an opinion; open a row to see it added up.
      </p>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      {report && notable.length === 0 && (
        <p className="mt-4 rounded-xl border border-dashed border-slate-300 px-3 py-6 text-center text-sm text-slate-500">
          Nobody stands out over the last {report.days} days.
          {report.scored_count === 0 && (
            <span className="mt-1 block text-xs">
              Not enough finished work to judge anyone yet — a worker needs {report.min_legs} legs
              before he is scored.
            </span>
          )}
        </p>
      )}

      <div className="mt-4 space-y-2">
        {notable.map((r) => {
          const isOpen = open.has(r.worker_id);
          return (
            <div
              key={r.worker_id}
              className={`card-flush ${r.band === "high" ? "ring-1 ring-red-200" : ""}`}
            >
              <button
                onClick={() => toggle(r.worker_id)}
                aria-expanded={isOpen}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-slate-50"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm font-semibold text-slate-900">{r.worker_name}</span>
                    <span className="text-xs text-slate-500">{r.department ?? "—"}</span>
                  </div>
                  <p className="num mt-0.5 text-xs text-slate-500">
                    {r.legs} legs · {fmtWeight(r.excess_g, 3)} g past allowance
                    {Number(r.open_gold_g) > 0 && (
                      <> · holding {fmtWeight(r.open_gold_g, 3)} g</>
                    )}
                  </p>
                </div>
                <div className="flex flex-none items-center gap-3">
                  <BandChip band={r.band} />
                  <span
                    className={`num w-9 text-right text-lg font-semibold ${
                      r.band === "high" ? "text-red-600" : "text-amber-700"
                    }`}
                  >
                    {r.score}
                  </span>
                  <svg
                    width="16" height="16" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="2" aria-hidden
                    className={`flex-none text-slate-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </div>
              </button>

              {isOpen && (
                <div className="border-t border-slate-100 px-4 py-3">
                  {r.narrative && (
                    <p className="mb-3 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-700">
                      {r.narrative}
                    </p>
                  )}
                  <ul className="space-y-2">
                    {r.reasons.map((x) => (
                      <li key={x.code} className="flex gap-3">
                        <span className="num w-8 flex-none rounded bg-slate-100 py-0.5 text-center text-xs font-semibold text-slate-600">
                          +{x.points}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-xs font-medium text-slate-900">
                            {x.label}
                          </span>
                          <span className="block text-xs leading-snug text-slate-600">
                            {x.detail}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                  <p className="num mt-3 border-t border-slate-100 pt-2 text-right text-xs text-slate-500">
                    total {r.score} / 100
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {quiet.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
            {quiet.length} other worker{quiet.length === 1 ? "" : "s"} with nothing to flag
          </summary>
          <ul className="mt-2 space-y-1">
            {quiet.map((r) => (
              <li key={r.worker_id} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-slate-700">
                  {r.worker_name}
                  <span className="ml-2 text-slate-400">{r.department ?? "—"}</span>
                </span>
                <span className="num text-slate-400">
                  {r.legs} legs · {fmtWeight(r.excess_g, 3)} g
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {report && !report.ai_enabled && report.ai_note && (
        <p className="mt-3 text-xs text-slate-400">{report.ai_note}</p>
      )}
    </section>
  );
}

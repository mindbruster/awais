/**
 * Who is holding the shop's material right now.
 *
 * The UI specification asks for this twice — once as a dashboard section and
 * once as a first-class concept — and it was the one thing in the spec with no
 * screen at all. Every existing view answers a neighbouring question: the
 * position report gives one total ("412 g are with workers"), true and useless
 * when you need to know *whose*; a party statement gives one party in full,
 * which is what you read after you already know who to worry about.
 *
 * Three units, side by side, never added — the rule that holds everywhere else
 * in this system. A karigar holding gold, silver and carats owes three
 * different things settled three different ways.
 *
 * The figures come from the **ledger**, not from open job legs, and the
 * difference is the entire point. Legs say what was issued; the ledger says
 * what is still out after everything that has come back. A worker with every
 * leg closed and a gram unaccounted for shows up here with that gram, and the
 * legs alone would have called him clear — which is exactly what the seeded
 * data does, so the case is not hypothetical.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Row {
  party_type: string;
  party_id: number;
  party_name: string | null;
  department: string | null;
  gold_g: string;
  silver_g: string;
  stone_ct: string;
  cash_balance: string;
  open_legs: number;
  oldest_issue_date: string | null;
  days_out: number | null;
  overdue_legs: number;
}

interface Report {
  as_of: string;
  rows: Row[];
  total_gold_g: string;
  total_silver_g: string;
  total_stone_ct: string;
  parties: number;
}

const n = (v: string) => Number(v) || 0;
const g = (v: string) => n(v).toFixed(3);

export function MaterialOutsidePage() {
  const [data, setData] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Report>("/reports/material-outside")
      .then((r) => setData(r.data))
      .catch((e) => setError(apiError(e, "Could not load what is outside")))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="card text-sm text-slate-500">Loading…</div>;
  if (error) return <div className="card text-sm text-red-600">{error}</div>;
  if (!data) return null;

  // Scaled on magnitude, so a row where the shop owes metal draws a bar the
  // size of the debt rather than collapsing to nothing.
  const maxGold = Math.max(...data.rows.map((r) => Math.abs(n(r.gold_g))), 1);
  // A negative balance is the shop holding the worker's own metal — the
  // no-gold-given deal, where he made the piece from his gold and is owed it
  // back. Real, and unreadable without a word of explanation on a page titled
  // "material with others".
  const owedOut = data.rows.filter((r) => n(r.gold_g) < 0 || n(r.silver_g) < 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Material with others</h1>
        <p className="mt-1 text-sm text-slate-500">
          Everything of the shop's that is currently in somebody else's hands, as of{" "}
          {data.as_of}. Read from the ledger, so it counts what is still out — not
          what was issued.
        </p>
      </div>

      {/* Three totals, never one. Gold and silver differ a hundredfold in
          value and a carat is not a gram; a combined figure would be a number
          in no unit at all. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Total label="Gold out" value={`${g(data.total_gold_g)} g`} tone="brand" />
        <Total label="Silver out" value={`${g(data.total_silver_g)} g`} />
        <Total label="Stones out" value={`${n(data.total_stone_ct).toFixed(2)} ct`} />
        <Total label="Parties holding" value={String(data.parties)} />
      </div>

      {data.rows.length === 0 ? (
        <EmptyState title="Nothing is outside the building">
          Every gram and every carat the shop has issued has come back. This page fills
          up the moment metal goes to a karigar.
        </EmptyState>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full min-w-[54rem] text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Who</th>
                <th className="px-4 py-3 text-right">Gold</th>
                <th className="px-4 py-3 text-right">Silver</th>
                <th className="px-4 py-3 text-right">Stones</th>
                <th className="px-4 py-3 text-right">Owed for labour</th>
                <th className="px-4 py-3">Out since</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.rows.map((r) => (
                <tr key={`${r.party_type}-${r.party_id}`} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link
                      to={`/vendors/${r.party_id}`}
                      className="font-medium text-brand-700 hover:underline"
                    >
                      {r.party_name ?? `${r.party_type} #${r.party_id}`}
                    </Link>
                    {r.department && (
                      <span className="ml-2 text-xs text-slate-400">{r.department}</span>
                    )}
                    <div
                      className={`mt-1 h-1 rounded ${
                        n(r.gold_g) < 0 ? "bg-sky-400" : "bg-brand-400"
                      }`}
                      style={{
                        width: `${Math.max((Math.abs(n(r.gold_g)) / maxGold) * 100, 2)}%`,
                      }}
                    />
                  </td>
                  <td
                    className={`num px-4 py-3 text-right font-medium ${
                      n(r.gold_g) < 0 ? "text-sky-700" : ""
                    }`}
                  >
                    {n(r.gold_g) ? `${g(r.gold_g)} g` : "—"}
                    {n(r.gold_g) < 0 && (
                      <span className="block text-[11px] font-normal text-sky-700">
                        we owe him
                      </span>
                    )}
                  </td>
                  <td className="num px-4 py-3 text-right">
                    {n(r.silver_g) ? `${g(r.silver_g)} g` : "—"}
                  </td>
                  <td className="num px-4 py-3 text-right">
                    {n(r.stone_ct) ? `${n(r.stone_ct).toFixed(2)} ct` : "—"}
                  </td>
                  <td className="num px-4 py-3 text-right text-slate-600">
                    {n(r.cash_balance) ? fmtMoney(r.cash_balance) : "—"}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {r.overdue_legs > 0 ? (
                      <span className="font-medium text-red-600">
                        {r.overdue_legs} leg{r.overdue_legs === 1 ? "" : "s"} past its
                        return date
                      </span>
                    ) : r.open_legs > 0 ? (
                      <span className={r.days_out && r.days_out > 30 ? "text-amber-700" : "text-slate-500"}>
                        {r.open_legs} open · {r.days_out ?? 0} day
                        {r.days_out === 1 ? "" : "s"}
                      </span>
                    ) : (
                      // The interesting row: a balance with nothing open behind
                      // it. Nothing is "in progress" — this is simply unreturned.
                      <span className="text-amber-700">
                        no open job — unreturned
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {owedOut.length > 0 && (
        <p className="rounded-lg bg-sky-50 px-3 py-2 text-xs leading-relaxed text-sky-900">
          {owedOut.length === 1 ? "One party has" : `${owedOut.length} parties have`} a{" "}
          <strong>negative balance</strong>, which is not an error: they worked on their
          own metal and the shop owes it back on the agreed date. It runs the opposite way
          to every other row here, so it is shown as it is rather than clamped to zero —
          and it is the only promise in the system to <em>deliver</em> metal, which is why
          the dashboard chases its due date.
        </p>
      )}

      <p className="text-xs leading-relaxed text-slate-500">
        A row with material but <strong>no open job</strong> is the one to look at: nothing
        is in progress against it, so the balance is not work under way — it is metal that
        has not come back. Ranked by gold, which is what exposure means here; silver and
        stones break ties rather than being added to it. The totals are three figures and
        never one: a gram of gold and a gram of silver differ a hundredfold, and a carat is
        not a gram at all.
      </p>
    </div>
  );
}

function Total({
  label,
  value,
  tone = "plain",
}: {
  label: string;
  value: string;
  tone?: "plain" | "brand";
}) {
  return (
    <div
      className={`rounded-lg px-3 py-2 ring-1 ${
        tone === "brand" ? "bg-brand-50 text-brand-900 ring-brand-200" : "bg-slate-50 ring-slate-200"
      }`}
    >
      <div className="text-xs uppercase opacity-70">{label}</div>
      <div className="num mt-0.5 text-lg font-semibold">{value}</div>
    </div>
  );
}

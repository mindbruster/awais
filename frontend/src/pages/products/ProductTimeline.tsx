/**
 * One piece, from raw metal to the customer's hand.
 *
 * §19 of the specification asks the product page to combine what the piece
 * looks like with where it has been, and this is the second half. Every other
 * screen answers a question about a *stage* — who holds metal, what is in
 * stock, what sold — and none of them could answer the question a customer
 * standing at the counter asks, which is "what is this, and where has it been".
 *
 * Assembled from the documents rather than from a log. A stored timeline is a
 * second version of history, and it drifts from the first one the moment
 * anything is reversed.
 *
 * The rail is deliberately plain: a dot, a date, a line. The temptation with a
 * lifecycle view is to draw it as a horizontal stepper with icons, which looks
 * better in a screenshot and is worse to read — real pieces go backwards, get
 * re-issued to the same worker twice, and come home from a memo unsold, and a
 * five-step stepper cannot show any of that without lying.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Event {
  kind: string;
  title: string;
  detail: string | null;
  at: string | null;
  reference: string | null;
  to: string | null;
  weight_g: string | null;
  stone_ct: string | null;
  amount: string | null;
  tone: "good" | "warn" | "bad" | "plain";
}

interface Timeline {
  product_id: number;
  serial_no: string;
  status: string;
  total_cost: string;
  material_cost: string;
  sold_for: string | null;
  margin: string | null;
  design_id: number | null;
  design_no: string | null;
  events: Event[];
}

const DOT: Record<string, string> = {
  good: "bg-emerald-500",
  warn: "bg-amber-500",
  bad: "bg-red-500",
  plain: "bg-slate-300",
};

// A word for the stage, so the eye can skim the rail without reading titles.
const STAGE: Record<string, string> = {
  job: "Job",
  issued: "Out",
  received: "Back",
  stocked: "Stock",
  transfer: "Moved",
  approval_out: "Memo",
  approval_back: "Returned",
  sold: "Sold",
};

const n = (v: string | null) => Number(v ?? 0) || 0;

export function ProductTimeline({ productId }: { productId: number }) {
  const [data, setData] = useState<Timeline | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Timeline>(`/products/${productId}/timeline`)
      .then((r) => setData(r.data))
      .catch((e) => setError(apiError(e, "Could not load the history")));
  }, [productId]);

  if (error) return <div className="card text-sm text-red-600">{error}</div>;
  if (!data) return <div className="card text-sm text-slate-500">Loading history…</div>;

  const cost = n(data.total_cost) + n(data.material_cost);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="eyebrow">Where this piece has been</h2>
        {data.design_no && (
          <Link
            to={`/designs/${data.design_id}`}
            className="text-xs text-brand-700 hover:underline"
          >
            job {data.design_no} →
          </Link>
        )}
      </div>

      {/* What it cost and what it made, side by side. The margin is null until
          it sells, because a margin on an unsold piece is a guess dressed as a
          figure. */}
      <div className="card grid gap-3 sm:grid-cols-3">
        <Fig label="Cost to make" value={fmtMoney(cost)} />
        <Fig
          label="Sold for"
          value={data.sold_for ? fmtMoney(data.sold_for) : "still in stock"}
        />
        <Fig
          label="Margin"
          value={data.margin === null ? "—" : fmtMoney(data.margin)}
          tone={data.margin === null ? "plain" : n(data.margin) >= 0 ? "good" : "bad"}
        />
      </div>

      <div className="card">
        <ol className="relative">
          {data.events.map((e, i) => {
            const last = i === data.events.length - 1;
            return (
              <li key={i} className="relative flex gap-4 pb-5 last:pb-0">
                {/* The rail. Drawn per row rather than as one absolute line so
                    it stops at the final dot instead of trailing into space. */}
                {!last && (
                  <span
                    className="absolute left-[5px] top-4 h-full w-px bg-slate-200"
                    aria-hidden="true"
                  />
                )}
                <span
                  className={`relative z-10 mt-1.5 h-2.5 w-2.5 flex-none rounded-full ring-4 ring-white ${
                    DOT[e.tone] ?? DOT.plain
                  }`}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm font-medium text-slate-900">{e.title}</span>
                    {e.reference &&
                      (e.to ? (
                        <Link
                          to={e.to}
                          className="font-mono text-[11px] text-brand-700 hover:underline"
                        >
                          {e.reference}
                        </Link>
                      ) : (
                        <span className="font-mono text-[11px] text-slate-400">
                          {e.reference}
                        </span>
                      ))}
                    <span className="ml-auto flex-none text-[10px] uppercase tracking-wide text-slate-400">
                      {STAGE[e.kind] ?? e.kind}
                    </span>
                  </div>
                  {e.detail && (
                    <p className="num mt-0.5 text-xs leading-relaxed text-slate-600">
                      {e.detail}
                    </p>
                  )}
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    {e.at ? (
                      new Date(e.at).toLocaleString()
                    ) : (
                      // Undated events sort last rather than to the epoch — a
                      // leg still out with a worker has no return date yet.
                      <span className="text-amber-600">not yet</span>
                    )}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

function Fig({
  label,
  value,
  tone = "plain",
}: {
  label: string;
  value: string;
  tone?: "plain" | "good" | "bad";
}) {
  return (
    <div>
      <p className="text-xs uppercase text-slate-500">{label}</p>
      <p
        className={`num mt-0.5 text-lg font-semibold ${
          tone === "good" ? "text-emerald-700" : tone === "bad" ? "text-red-600" : "text-slate-900"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

/**
 * One piece, and everywhere it has been.
 *
 * The page is laid out in the order the floor asks its questions: what is this
 * and where is it now (the job card), what has it cost so far (the strip), how
 * did it get here (the route), and what happens next (the action rail). The
 * route collapses because a piece running nine stages was previously a mile of
 * scrolling in which the one leg that mattered — the open one — looked exactly
 * like the eight that were already settled.
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { TextArea, TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";
import { Img } from "@/components/Img";
import { IssueSheet } from "@/pages/designs/IssueSheet";
import {
  DesignStatusChip,
  Figure,
  Leg,
  LegStatusChip,
  LegStone,
  Metric,
  Settlement,
  Terms,
  allowanceOf,
  allowanceWorking,
  designStatusLabel,
  labourOn,
  labourWorking,
  netMetal,
  round4,
  settle,
  termsOf,
  when,
  wt,
} from "@/pages/designs/parts";

interface DesignDetail {
  id: number;
  design_no: string;
  tag_no: string | null;
  item_name: string | null;
  customer_name: string | null;
  current_department_name: string | null;
  status: string;
  is_lot: boolean;
  expected_pieces: number;
  parent_design_id: number | null;
  piece_weight_g: string | null;
  piece_purity: number | null;
  image_url: string | null;
  notes: string | null;
  product_id: number | null;
  legs: Leg[];
}

interface Trace {
  started_at: string | null;
  completed_at: string | null;
  days_in_production: number | null;
  hops: { leg_id: number; days_held: number | null }[];
  totals: {
    hops: number;
    open_hops: number;
    pieces: number;
    gold_issued_g: string;
    gold_received_g: string;
    wastage_allowed_g: string;
    wastage_actual_g: string;
    wastage_excess_g: string;
    stones_issued_ct: string;
    stones_used_ct: string;
    stones_returned_ct: string;
    labour_amount: string;
  };
}

/**
 * Whether the piece can be put into stock, and why not when it can't.
 *
 * These are the same four refusals `stocking.ensure_stockable` makes on the
 * server. They are restated here so the button can say what is standing in the
 * way instead of offering an action that will 409 — and, more importantly, so
 * the action exists at all: the stock form was reachable only by typing its URL.
 */
function stockability(design: DesignDetail): { ok: boolean; reason?: string } {
  if (design.product_id !== null || design.status === "stocked")
    return { ok: false, reason: "already stocked" };
  if (design.status === "sold" || design.status === "cancelled")
    return { ok: false, reason: `${designStatusLabel(design.status).toLowerCase()} — nothing to stock` };
  // A divided lot holds nothing any more: its metal is in the pieces, and each
  // of those is stocked on its own. Stocking the lot as well would put the same
  // gold into finished goods twice.
  if (design.status === "split")
    return { ok: false, reason: "divided into pieces — stock those individually" };
  if (design.is_lot)
    return { ok: false, reason: "a lot is divided into pieces before any of it is stocked" };
  const out = design.legs.find((l) => l.status === "issued");
  if (out)
    return {
      ok: false,
      reason: `still out at ${out.department_name ?? "a department"} — receive leg #${out.sequence} first`,
    };
  if (!design.legs.some((l) => l.status === "received"))
    return { ok: false, reason: "nothing has come back yet" };
  return { ok: true };
}

export function DesignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const designId = Number(id);
  const [design, setDesign] = useState<DesignDetail | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, t] = await Promise.all([
        api.get<DesignDetail>(`/designs/${designId}`),
        api.get<Trace>(`/designs/${designId}/trace`),
      ]);
      setDesign(d.data);
      setTrace(t.data);
    } catch (e) {
      setError(apiError(e, "Failed to load design"));
    }
  }, [designId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!design || !trace) return <div className="text-sm text-slate-500">Loading…</div>;

  const openLeg = design.legs.find((l) => l.status === "issued") ?? null;
  const closed = design.status === "sold" || design.status === "cancelled";
  const daysHeld = new Map(trace.hops.map((h) => [h.leg_id, h.days_held]));
  const stock = stockability(design);
  const railed = Boolean(openLeg) || !closed;

  return (
    <div className="space-y-5">
      <JobCard design={design} trace={trace} reload={load} />
      <LedgerStrip totals={trace.totals} />

      <div className={railed ? "grid gap-5 lg:grid-cols-[minmax(0,1fr)_21rem]" : ""}>
        <Timeline legs={design.legs} daysHeld={daysHeld} />

        {railed && (
          <div className="space-y-4 lg:sticky lg:top-6 lg:self-start">
            {openLeg ? (
              <ReceivePanel leg={openLeg} designNo={design.design_no} reload={load} />
            ) : design.is_lot && design.status !== "split" ? (
              <SplitPanel design={design} reload={load} />
            ) : (
              <NextStep
                designId={design.id}
                designNo={design.design_no}
                stock={stock}
                onIssue={() => setIssuing(true)}
              />
            )}
          </div>
        )}
      </div>

      {closed && (
        <div className="card text-sm text-slate-500">
          {design.design_no} is {designStatusLabel(design.status).toLowerCase()}. No further work
          can be issued.
        </div>
      )}

      <IssueSheet
        open={issuing}
        onClose={() => setIssuing(false)}
        designId={design.id}
        designNo={design.design_no}
        onIssued={load}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ header */

function JobCard({
  design,
  trace,
  reload,
}: {
  design: DesignDetail;
  trace: Trace;
  reload: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const generateTag = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ tag_no: string }>(`/designs/${design.id}/tag`, {});
      toast("success", `Tag ${r.data.tag_no} issued`);
      reload();
    } catch (err) {
      toast("error", apiError(err, "Could not generate tag"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card-flush">
      <div className="border-b border-slate-100 px-5 pb-4 pt-4">
        <Link to="/designs" className="text-xs text-slate-500 hover:text-slate-700 hover:underline">
          ← Designs
        </Link>

        <div className="mt-3 flex flex-wrap items-start gap-4">
          {design.image_url && (
            <Img
              src={design.image_url}
              alt={design.design_no}
              className="h-20 w-20 flex-none rounded-xl border border-slate-200 object-cover"
              fallbackClassName="num flex h-20 w-20 flex-none items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-[10px] text-slate-400"
              fallback={design.design_no}
            />
          )}
          <div className="min-w-0 flex-1">
            <h1 className="num text-3xl font-semibold tracking-tight text-slate-900">
              {design.design_no}
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              {design.item_name ?? "—"} ·{" "}
              {design.customer_name ? (
                <span className="text-slate-900">{design.customer_name}</span>
              ) : (
                "for stock"
              )}
              {/* A lot and a piece are read very differently — one is a dealing
                  with a maker, the other is an article — and the number alone
                  does not always say which, so the line does. */}
              {design.is_lot && (
                <>
                  {" · "}
                  <span className="text-slate-900">
                    a lot
                    {design.expected_pieces > 0 ? ` of ${design.expected_pieces} pieces` : ""}
                  </span>
                </>
              )}
              {design.parent_design_id && design.piece_weight_g && (
                <>
                  {" · "}
                  <span className="num text-slate-900">
                    {wt(design.piece_weight_g)}
                    {design.piece_purity ? ` of ${design.piece_purity}k` : ""}
                  </span>{" "}
                  <Link
                    to={`/designs/${design.parent_design_id}`}
                    className="text-brand-700 hover:underline"
                  >
                    from its lot
                  </Link>
                </>
              )}
            </p>
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              <DesignStatusChip status={design.status} />
              {design.current_department_name ? (
                <span className="chip-out">
                  <span className="dot bg-amber-500" aria-hidden />
                  Out at {design.current_department_name}
                </span>
              ) : (
                <span className="chip-idle">In house</span>
              )}
              {design.tag_no ? (
                <span className="chip-gold num">{design.tag_no}</span>
              ) : (
                <button
                  onClick={generateTag}
                  disabled={busy}
                  className="chip border border-dashed border-slate-300 text-slate-500 hover:border-brand-400 hover:text-brand-700 disabled:opacity-60"
                >
                  {busy ? "Generating…" : "+ Generate tag"}
                </button>
              )}
            </div>
          </div>

          {/* Only the onward link lives up here. What to *do* with the piece is
              the rail's job, and offering the same two buttons in both places
              makes the reader decide which one is the real one. */}
          {design.product_id !== null && (
            <Link className="btn-outline flex-none" to={`/products/${design.product_id}`}>
              View product →
            </Link>
          )}
        </div>
      </div>

      <dl className="grid grid-cols-2 divide-x divide-slate-100 sm:grid-cols-4">
        <Stat label="Started" value={when(trace.started_at)} />
        <Stat label="Completed" value={when(trace.completed_at)} />
        <Stat
          label="Days in production"
          value={trace.days_in_production !== null ? String(trace.days_in_production) : "—"}
        />
        <Stat
          label="Legs"
          value={String(trace.totals.hops)}
          sub={trace.totals.open_hops ? `${trace.totals.open_hops} open` : "all closed"}
        />
      </dl>

      {design.notes && (
        <p className="whitespace-pre-line border-t border-slate-100 px-5 py-3 text-xs leading-relaxed text-slate-500">
          {design.notes}
        </p>
      )}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="px-5 py-3">
      <dt className="eyebrow">{label}</dt>
      <dd className="num mt-0.5 text-sm text-slate-900">
        {value}
        {sub && <span className="ml-1.5 text-xs font-normal text-slate-400">{sub}</span>}
      </dd>
    </div>
  );
}

function LedgerStrip({ totals }: { totals: Trace["totals"] }) {
  const excess = Number(totals.wastage_excess_g);
  return (
    <div className="card-flush grid grid-cols-2 divide-slate-100 sm:grid-cols-3 lg:grid-cols-5 lg:divide-x">
      <div className="border-b border-slate-100 px-5 py-4 sm:border-b-0">
        <Metric label="Gold issued" value={wt(totals.gold_issued_g)} sub={`${totals.hops} legs`} />
      </div>
      <div className="border-b border-slate-100 px-5 py-4 sm:border-b-0">
        <Metric
          label="Gold received"
          value={wt(totals.gold_received_g)}
          sub={totals.open_hops ? `${totals.open_hops} still out` : "all legs closed"}
        />
      </div>
      <div className="border-b border-slate-100 px-5 py-4 lg:border-b-0">
        <Metric
          label="Wastage"
          value={wt(totals.wastage_actual_g)}
          sub={`${wt(totals.wastage_allowed_g)} allowed`}
        />
      </div>
      <div className="border-b border-slate-100 px-5 py-4 lg:border-b-0">
        <Metric
          label="Owed by workers"
          value={wt(totals.wastage_excess_g)}
          sub="beyond allowance"
          tone={excess > 0 ? "bad" : "good"}
        />
      </div>
      <div className="px-5 py-4">
        <Metric
          label="Labour"
          value={fmtMoney(totals.labour_amount)}
          sub={
            totals.pieces
              ? `${totals.pieces} pcs handled · accrued on closed legs`
              : "accrued on closed legs"
          }
        />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- the route */

function Timeline({
  legs,
  daysHeld,
}: {
  legs: Leg[];
  daysHeld: Map<number, number | null>;
}) {
  // Open first, then the leg that closed most recently. A settled leg from six
  // weeks ago is history; it opens when it is asked for.
  const lastReceived = [...legs].reverse().find((l) => l.status === "received");
  const [expanded, setExpanded] = useState<Set<number>>(
    () =>
      new Set(
        legs
          .filter((l) => l.status === "issued" || l.id === lastReceived?.id)
          .map((l) => l.id),
      ),
  );

  // A leg that has just been issued is the one the operator is about to act on,
  // so it opens itself when it appears. Legs he has closed by hand stay closed:
  // this only ever adds.
  const openIds = legs
    .filter((l) => l.status === "issued")
    .map((l) => l.id)
    .join(",");
  useEffect(() => {
    if (!openIds) return;
    setExpanded((s) => {
      const next = new Set(s);
      openIds.split(",").forEach((v) => next.add(Number(v)));
      return next;
    });
  }, [openIds]);

  const toggle = (id: number) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (legs.length === 0) {
    return (
      <div className="card py-10 text-center">
        <p className="text-sm font-medium text-slate-700">Nothing has been issued yet.</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-slate-500">
          The route builds itself as the piece moves. Issue it to its first department to start.
        </p>
      </div>
    );
  }

  const allOpen = expanded.size === legs.length;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-slate-900">
          Route <span className="font-normal text-slate-400">· {legs.length} legs</span>
        </h2>
        <button
          className="text-xs text-slate-500 hover:text-slate-800 hover:underline"
          onClick={() => setExpanded(allOpen ? new Set() : new Set(legs.map((l) => l.id)))}
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>

      <ol className="space-y-2">
        {legs.map((leg, i) => (
          <li key={leg.id} className="relative pl-9">
            {i < legs.length - 1 && (
              <span
                className="absolute left-[13px] top-9 h-[calc(100%-1rem)] w-px bg-slate-200"
                aria-hidden
              />
            )}
            <span
              className={`num absolute left-0 top-2.5 flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
                leg.status === "issued"
                  ? "bg-amber-100 text-amber-800 ring-4 ring-amber-50"
                  : leg.status === "received"
                  ? "bg-emerald-100 text-emerald-800"
                  : "bg-slate-200 text-slate-500"
              }`}
            >
              {leg.sequence}
            </span>
            <LegCard
              leg={leg}
              daysHeld={daysHeld.get(leg.id) ?? null}
              open={expanded.has(leg.id)}
              onToggle={() => toggle(leg.id)}
            />
          </li>
        ))}
      </ol>
    </div>
  );
}

function LegCard({
  leg,
  daysHeld,
  open,
  onToggle,
}: {
  leg: Leg;
  daysHeld: number | null;
  open: boolean;
  onToggle: () => void;
}) {
  const cancelled = leg.status === "cancelled";
  const live = leg.status === "issued";
  const terms = termsOf(leg);
  const excess = Number(leg.wastage_excess_g);
  const labourSub =
    labourWorking(leg, Number(leg.labour_amount)) ??
    `${leg.labour_basis.replace(/_/g, " ")} @ ${Number(leg.labour_rate)}`;

  return (
    <div
      className={`card-flush ${cancelled ? "opacity-70" : ""} ${
        live ? "ring-1 ring-amber-200" : ""
      }`}
    >
      {/* The collapsed line has to carry enough that opening it is a choice,
          not the only way to find out what happened. */}
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-slate-50"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <h3 className="text-sm font-semibold text-slate-900">{leg.department_name ?? "—"}</h3>
            <span className="text-xs text-slate-500">
              {leg.worker_name ?? "in-house"}
            </span>
          </div>
          <p className="num mt-0.5 text-xs text-slate-500">
            {wt(leg.gold_issued_g)} out
            {!live && !cancelled && <> · {wt(leg.gold_received_g)} back</>}
            {daysHeld !== null && (
              <> · {daysHeld} day{daysHeld === 1 ? "" : "s"}</>
            )}
          </p>
        </div>
        <div className="flex flex-none items-center gap-2">
          {excess > 0 && !live && (
            <span className="chip-owed num">{wt(excess)} owed</span>
          )}
          <LegStatusChip status={leg.status} />
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={`flex-none text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
            aria-hidden
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-100 px-4 py-4">
          <p className="mb-3 text-xs text-slate-500">
            Issued {when(leg.issued_at)}
            {leg.received_at ? ` · received ${when(leg.received_at)}` : ""}
          </p>

          <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            <Figure
              label={leg.metal === "silver" ? "Silver issued" : "Gold issued"}
              value={wt(leg.gold_issued_g)}
              sub={
                leg.gold_issued_tunch_pct
                  ? `${Number(leg.gold_issued_tunch_pct)}% fine`
                  : leg.gold_issued_purity
                  ? `${leg.gold_issued_purity}k`
                  : undefined
              }
            />
            <Figure
              label={leg.metal === "silver" ? "Silver received" : "Gold received"}
              value={live ? "pending" : wt(leg.gold_received_g)}
              muted={live}
              // The gross is worth showing beside the net whenever they differ:
              // the net is what settled, but the gross is the number the worker
              // and the counter both watched go onto the scale.
              sub={
                !live && Number(leg.gold_received_gross_g) !== Number(leg.gold_received_g)
                  ? `${wt(leg.gold_received_gross_g)} gross, less ${wt(
                      leg.stones_set_ct,
                      "ct",
                    )} set`
                  : !live && leg.gold_received_purity
                  ? `${leg.gold_received_purity}k back`
                  : undefined
              }
            />
            <Figure
              label="Labour"
              value={fmtMoney(live ? null : leg.labour_amount)}
              muted={live}
              sub={
                live && leg.labour_basis === "per_piece"
                  ? `${leg.piece_count} × ${fmtMoney(leg.labour_rate)} on receive`
                  : labourSub
              }
            />
            <Figure
              label="Stones"
              value={Number(leg.stones_issued_ct) ? wt(leg.stones_used_ct, "ct") : "—"}
              muted={!Number(leg.stones_issued_ct)}
              sub={
                Number(leg.stones_issued_ct)
                  ? `${wt(leg.stones_issued_ct, "ct")} issued, ${wt(
                      leg.stones_returned_ct,
                      "ct",
                    )} back`
                  : undefined
              }
            />
            {Number(leg.stones_broken_ct) > 0 && (
              <Figure
                label="Broken"
                value={wt(leg.stones_broken_ct, "ct")}
                sub="held as stock at cost"
              />
            )}
            {Number(leg.stones_owed_ct) > 0 && (
              <Figure
                label="Stones owed"
                value={wt(leg.stones_owed_ct, "ct")}
                sub={`charged to ${leg.worker_name ?? "the worker"}`}
              />
            )}
            {leg.piece_count > 0 && (
              <Figure
                label="Pieces"
                value={String(leg.piece_count)}
                sub={leg.stones.length > 0 ? "stones set" : "items handled"}
              />
            )}
          </div>

          {!live && !cancelled && (
            <Settlement
              className="mt-4"
              allowed={Number(leg.wastage_allowed_g)}
              actual={Number(leg.wastage_actual_g)}
              excess={excess}
              terms={terms}
              worker={leg.worker_name}
              // The two operands, so the difference can be checked against a
              // scale rather than taken on trust. `gross` is what was weighed
              // at the counter on the way back; the stone grams are added to
              // the given side, which is how the trade states it — 100 g of
              // gold plus 30 ct of stones is 106 g out.
              given={Number(leg.gold_issued_g)}
              back={Number(leg.gold_received_gross_g)}
              stonesSetCt={Number(leg.stones_used_ct) || null}
              // Only when the fine reckoning says something the raw figures
              // don't. On a leg that went out and came back at one purity the
              // two are the same story told twice.
              fine={
                leg.wastage_actual_fine_g !== null &&
                Number(leg.wastage_actual_fine_g) !== Number(leg.wastage_actual_g)
                  ? {
                      allowed: Number(leg.wastage_allowed_fine_g ?? 0),
                      actual: Number(leg.wastage_actual_fine_g),
                      excess: Number(leg.wastage_excess_fine_g ?? 0),
                    }
                  : null
              }
            />
          )}
          {live && (
            <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
              {wt(leg.gold_issued_g)} is with {leg.worker_name ?? "the shop's own bench"}. Wastage
              is settled when the piece comes back —{" "}
              {allowanceWorking(terms, allowanceOf(terms, Number(leg.gold_issued_g)))}.
            </p>
          )}

          {leg.stones.length > 0 && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[24rem] border-t border-slate-100 pt-2 text-xs">
                <thead className="text-left text-slate-400">
                  <tr className="eyebrow">
                    <th className="py-1.5 font-semibold">Stone</th>
                    <th className="py-1.5 text-right font-semibold">Issued</th>
                    <th className="py-1.5 text-right font-semibold">Returned</th>
                    <th className="py-1.5 text-right font-semibold">Used</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {leg.stones.map((s) => (
                    <tr key={s.id}>
                      <td className="py-1.5 text-slate-700">{s.stone_name ?? `#${s.stone_id}`}</td>
                      <td className="num py-1.5 text-right">
                        {s.quantity_issued} · {wt(s.weight_issued_ct, "ct")}
                      </td>
                      <td className="num py-1.5 text-right">
                        {s.quantity_returned} · {wt(s.weight_returned_ct, "ct")}
                      </td>
                      <td className="num py-1.5 text-right font-medium">
                        {wt(round4(Number(s.weight_issued_ct) - Number(s.weight_returned_ct)), "ct")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {leg.notes && (
            <p className="mt-3 whitespace-pre-line border-t border-slate-100 pt-3 text-xs leading-relaxed text-slate-500">
              {leg.notes}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------------- the action rail */

/** What to do with a piece that is sitting in the shop. */
function NextStep({
  designId,
  designNo,
  stock,
  onIssue,
}: {
  designId: number;
  designNo: string;
  stock: { ok: boolean; reason?: string };
  onIssue: () => void;
}) {
  return (
    <div className="card">
      <h3 className="text-sm font-semibold text-slate-900">{designNo} is in the shop</h3>
      <p className="mt-1 text-xs leading-relaxed text-slate-500">
        Nobody is holding it. Send it on to the next department, or — when it's finished — put it
        into stock as a sellable piece.
      </p>
      <div className="mt-4 space-y-2">
        <button className="btn-primary w-full" onClick={onIssue}>
          Issue to department
        </button>
        {stock.ok ? (
          <Link className="btn-outline w-full" to={`/designs/${designId}/stock`}>
            Stock this piece
          </Link>
        ) : (
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-center text-xs text-slate-500">
            Can't be stocked yet — {stock.reason}.
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * Dividing a returned lot into the pieces the maker handed over.
 *
 * Each piece is weighed on its own. An even split would be one click and
 * wrong: twelve bangles differ by a gram either way, and from then on every
 * piece's cost, price and wastage would be worked out from a weight it never
 * had. So the form starts from the expected count with blank weights, shows
 * the running total against what actually came back, and will not commit until
 * the two agree — which is the same check the server makes.
 */
function SplitPanel({ design, reload }: { design: DesignDetail; reload: () => void }) {
  const lastReceived = [...design.legs].reverse().find((l) => l.status === "received");
  const back = round4(Number(lastReceived?.gold_received_g ?? 0));
  const [weights, setWeights] = useState<string[]>(() =>
    Array.from({ length: Math.max(design.expected_pieces || 1, 1) }, () => ""),
  );
  const [busy, setBusy] = useState(false);

  const total = round4(weights.reduce((s, w) => s + Number(w || 0), 0));
  const filled = weights.filter((w) => Number(w || 0) > 0).length;
  const diff = round4(back - total);
  const ready = filled === weights.length && diff === 0 && back > 0;

  const setAt = (i: number, v: string) =>
    setWeights((w) => w.map((x, j) => (j === i ? v : x)));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post<{ design_no: string }[]>(`/designs/${design.id}/split`, {
        pieces: weights.map((w) => ({ weight_g: w })),
      });
      toast("success", `${design.design_no} divided into ${r.data.length} pieces`);
      reload();
    } catch (err) {
      toast("error", apiError(err, "Could not divide the lot"));
    } finally {
      setBusy(false);
    }
  };

  if (!lastReceived) {
    return (
      <div className="card">
        <h3 className="text-sm font-semibold text-slate-900">Divide the lot</h3>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          Nothing has come back on {design.design_no} yet. Issue it to a maker and receive the
          metal — the pieces are numbered from what he actually hands over, not from what was
          planned.
        </p>
      </div>
    );
  }

  return (
    <div className="card border-brand-200 ring-1 ring-brand-100">
      <div className="flex items-start gap-2">
        <span className="dot mt-1.5 flex-none bg-brand-500" aria-hidden />
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">Divide into pieces</h3>
          <p className="num mt-0.5 text-xs text-slate-500">
            {wt(back)} back
            {lastReceived.gold_received_purity ? ` · ${lastReceived.gold_received_purity}k` : ""}
          </p>
        </div>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Weigh each piece. Each gets its own design number and carries it through setting, stock
        and sale — so the weights have to be the real ones, not an average.
      </p>

      <form onSubmit={submit} className="mt-3 space-y-2">
        {weights.map((w, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="num w-8 flex-none text-right text-xs text-slate-400">{i + 1}</span>
            <input
              className="input flex-1"
              type="number"
              step="0.0001"
              min="0"
              placeholder="0.0000"
              value={w}
              onChange={(e) => setAt(i, e.target.value)}
            />
            {weights.length > 1 && (
              <button
                type="button"
                className="flex-none text-xs text-slate-400 hover:text-red-600"
                onClick={() => setWeights((ws) => ws.filter((_, j) => j !== i))}
                aria-label={`Remove piece ${i + 1}`}
              >
                ✕
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          className="text-xs font-medium text-brand-700 underline underline-offset-2"
          onClick={() => setWeights((w) => [...w, ""])}
        >
          Add another piece
        </button>

        <div
          className={`mt-2 rounded-xl px-3 py-2 text-xs ${
            diff === 0 && total > 0 ? "bg-emerald-50 text-emerald-900" : "bg-slate-50 text-slate-600"
          }`}
        >
          <div className="flex items-baseline justify-between gap-2">
            <span>{weights.length} pieces total</span>
            <span className="num font-medium">{wt(total)}</span>
          </div>
          {diff !== 0 && (
            <p className="num mt-1 text-[11px]">
              {diff > 0
                ? `${wt(diff)} still to account for against the ${wt(back)} that came back.`
                : `${wt(Math.abs(diff))} more than the ${wt(back)} that came back.`}
            </p>
          )}
        </div>

        <button className="btn-primary w-full" disabled={busy || !ready}>
          {busy ? "Dividing…" : `Divide into ${weights.length} pieces`}
        </button>
      </form>
    </div>
  );
}

function ReceivePanel({
  leg,
  designNo,
  reload,
}: {
  leg: Leg;
  designNo: string;
  reload: () => void;
}) {
  // What the scale reads: the whole object, stones and all.
  const [received, setReceived] = useState("");
  // The purity of what came *back*, which on a maker's leg is not the purity
  // that went out. Blank means "the same as issued", which is right for setting
  // and lacker legs where the piece is handed over and back unchanged.
  const [recvPurity, setRecvPurity] = useState("");
  const [recvTunch, setRecvTunch] = useState("");
  // Per stone line: set into the piece, handed back whole, chipped. What the
  // setter owes is the remainder, derived rather than typed — a fourth figure
  // could contradict the other three with nothing to say which was wrong.
  const [returns, setReturns] = useState<
    Record<number, { setQty: string; setCt: string; qty: string; ct: string; brokeQty: string; brokeCt: string }>
  >({});
  const [pieceCount, setPieceCount] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [askCancel, setAskCancel] = useState(false);
  const [cancelGold, setCancelGold] = useState("");
  const [cancelStones, setCancelStones] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  const issued = Number(leg.gold_issued_g);
  const terms: Terms = termsOf(leg);
  const blankLine = { setQty: "", setCt: "", qty: "", ct: "", brokeQty: "", brokeCt: "" };
  const lineOf = (id: number) => returns[id] ?? blankLine;

  // Carats stated as set into the piece. These are what the gross weight is
  // netted by, so they have to be totalled before anything else can be worked
  // out — the metal is what is left once the stones come back out at five
  // carats to the gram.
  const setCt = round4(
    leg.stones.reduce((s, st) => s + Number(lineOf(st.id).setCt || 0), 0),
  );
  const gross = Number(received || 0);
  const net = netMetal(gross, setCt);

  // Typed weight, not the committed one: this is what makes the settlement
  // visible before the operator signs off on it.
  const preview = settle(
    issued,
    net,
    terms,
    recvPurity ? Number(recvPurity) : null,
    recvTunch ? Number(recvTunch) : null,
  );
  const effectivePieces = pieceCount === "" ? leg.piece_count : Number(pieceCount || 0);
  const labour = labourOn({ ...leg, piece_count: effectivePieces }, net);
  const holder = leg.worker_name ?? "the bench";

  // Issued less set, returned and broken — the setter's debt, per material.
  const owedCt = (s: LegStone) =>
    Math.max(
      round4(
        Number(s.weight_issued_ct) -
          Number(lineOf(s.id).setCt || 0) -
          Number(lineOf(s.id).ct || 0) -
          Number(lineOf(s.id).brokeCt || 0),
      ),
      0,
    );
  const overAccounted = (s: LegStone) =>
    round4(
      Number(lineOf(s.id).setCt || 0) +
        Number(lineOf(s.id).ct || 0) +
        Number(lineOf(s.id).brokeCt || 0),
    ) > Number(s.weight_issued_ct);

  const setReturn = (id: number, patch: Partial<typeof blankLine>) =>
    setReturns((r) => ({ ...r, [id]: { ...(r[id] ?? blankLine), ...patch } }));

  const stoneProblem = leg.stones.find(overAccounted);
  // The maker's convention is the one that changes purity between the two ends
  // of the job, so it is the one that cannot be left to the fallback.
  const needsPurity = leg.wastage_basis === "ratti_of_received";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/designs/legs/${leg.id}/receive`, {
        // The gross the scale read. The server takes the set stones back out
        // of it; sending the net would take them out twice.
        gold_received_g: received || "0",
        gold_received_purity: recvPurity ? Number(recvPurity) : null,
        gold_received_tunch_pct: recvTunch || null,
        piece_count: pieceCount === "" ? null : Number(pieceCount),
        stones: leg.stones.map((s) => ({
          leg_stone_id: s.id,
          quantity_set: Number(lineOf(s.id).setQty || 0),
          weight_set_ct: lineOf(s.id).setCt || "0",
          quantity_returned: Number(lineOf(s.id).qty || 0),
          weight_returned_ct: lineOf(s.id).ct || "0",
          quantity_broken: Number(lineOf(s.id).brokeQty || 0),
          weight_broken_ct: lineOf(s.id).brokeCt || "0",
        })),
        notes: notes || null,
      });
      toast("success", `Leg #${leg.sequence} received`);
      reload();
    } catch (err) {
      toast("error", apiError(err, "Could not receive"));
    } finally {
      setBusy(false);
    }
  };

  const confirmCancel = async (password: string) => {
    try {
      await api.post(
        `/designs/legs/${leg.id}/cancel`,
        {
          gold_recovered_g: cancelGold || "0",
          stones_recovered_ct: cancelStones || "0",
          reason: cancelReason.trim(),
        },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `Leg #${leg.sequence} cancelled`);
      setAskCancel(false);
      reload();
    } catch (err) {
      toast("error", apiError(err, "Cancel failed"));
    }
  };

  return (
    <div className="card border-amber-200 ring-1 ring-amber-100">
      <div className="flex items-start gap-2">
        <span className="dot mt-1.5 flex-none bg-amber-500" aria-hidden />
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">Receive from {holder}</h3>
          <p className="num mt-0.5 text-xs text-slate-500">
            Leg #{leg.sequence} · {leg.department_name} · {wt(leg.gold_issued_g)} out
          </p>
        </div>
      </div>

      <form onSubmit={submit} className="mt-4 space-y-3">
        <TextField
          label={
            leg.stones.length > 0 ? "Gross weight on the scale (g)" : "Metal received (g)"
          }
          type="number"
          step="0.0001"
          min={0}
          required
          autoFocus
          value={received}
          onChange={(e) => setReceived(e.target.value)}
          hint={
            leg.stones.length > 0
              ? "The whole piece, stones and all — the metal is worked out below"
              : "Heavier than issued is fine — solder and findings add weight"
          }
        />

        {/* Gross to net, shown as the arithmetic rather than as a result. The
            operator is checking a number against a scale, and "102 − 5.900 =
            96.100" is checkable where "96.100" alone is something to trust. */}
        {leg.stones.length > 0 && received !== "" && (
          <div className="rounded-xl bg-slate-50 px-3 py-2.5">
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-slate-500">Metal in the piece</span>
              <span className="num text-sm font-semibold text-slate-900">{wt(net)}</span>
            </div>
            <p className="num mt-1 text-[11px] leading-snug text-slate-500">
              {wt(gross)} gross − {wt(setCt, "ct")} set ({wt(round4(setCt / 5))}) = {wt(net)}
            </p>
            {net < 0 && (
              <p className="mt-1.5 text-[11px] leading-relaxed text-red-600">
                The stones stated as set weigh more than the piece does. Check the gross weight
                and the carats set — one of them is wrong.
              </p>
            )}
          </div>
        )}

        {/* The purity that came back, which on a maker's leg is not the purity
            that went out. Crediting 21k as though it were pure overstates his
            return by about a seventh and the job reads as settled while the
            metal is still short. */}
        <div className="grid grid-cols-2 gap-3">
          <TextField
            label="Returned purity (k)"
            type="number"
            min={1}
            max={24}
            required={needsPurity}
            value={recvPurity}
            onChange={(e) => setRecvPurity(e.target.value)}
            placeholder={leg.gold_issued_purity ? String(leg.gold_issued_purity) : "same as out"}
            // A ratti leg exists *because* the purity changes — pure out, 21k
            // back. Left blank the server refuses it, and rightly: the fallback
            // would credit the alloy as pure and hand the maker a seventh of
            // the job. Said here rather than met as an error after typing.
            hint={
              needsPurity
                ? "Required on a ratti leg — what he handed back, not what went out"
                : "Blank = same as went out"
            }
            error={
              needsPurity && received !== "" && !recvPurity && !recvTunch
                ? "State what came back, or the metal is credited as though it were pure"
                : null
            }
          />
          <TextField
            label="Returned tunch (%)"
            type="number"
            step="0.001"
            min={0.001}
            max={100}
            value={recvTunch}
            onChange={(e) => setRecvTunch(e.target.value)}
            placeholder="optional"
            hint="Wins over the karat when assayed"
          />
        </div>

        {preview.crossPurity && received !== "" && (
          <p className="rounded-lg bg-brand-50 px-3 py-2 text-[11px] leading-relaxed text-brand-900">
            What came back is a different purity from what went out, so the settlement is worked
            out in fine grams — {wt(preview.fineActual)} short against{" "}
            {wt(preview.fineAllowed)} allowed.
          </p>
        )}

        {leg.wastage_basis === "ratti_of_received" && received !== "" && (
          <p className="num rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
            {Number(leg.wastage_ratti ?? 0)} ratti on {wt(net)} allows{" "}
            {wt(preview.allowed)} — added to his credit before it is converted to pure.
          </p>
        )}

        {(terms.basis === "per_100_pieces" || leg.labour_basis === "per_piece") && (
          <TextField
            label="Stones set"
            type="number"
            min={0}
            value={pieceCount}
            onChange={(e) => setPieceCount(e.target.value)}
            placeholder={String(leg.piece_count)}
            hint={`Agreed at ${leg.piece_count} when it went out. What he actually set is what pays him and what his allowance is worked out from.`}
          />
        )}

        {received === "" ? (
          <p className="rounded-xl border border-dashed border-slate-300 px-3 py-4 text-center text-xs leading-relaxed text-slate-500">
            Weigh the piece and enter it above — the wastage settlement appears here before you
            commit it. {allowanceWorking(terms, allowanceOf(terms, issued))}.
          </p>
        ) : (
          <>
            <Settlement
              allowed={preview.allowed}
              actual={preview.actual}
              excess={preview.excess}
              terms={terms}
              worker={leg.worker_name}
              // Live, from the same locals the preview is computed from, so
              // the working on screen can never describe a different sum than
              // the figure under it.
              given={issued}
              back={gross}
              stonesSetCt={setCt || null}
              fine={
                preview.crossPurity
                  ? {
                      allowed: preview.fineAllowed,
                      actual: preview.fineActual,
                      excess: preview.fineExcess,
                    }
                  : null
              }
            />
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="text-slate-500">Labour on this leg</span>
              <span className="text-right">
                <span className="num block font-medium text-slate-900">{fmtMoney(labour)}</span>
                {labourWorking(leg, labour) && (
                  <span className="num block text-[11px] text-slate-400">
                    {labourWorking(leg, labour)}
                  </span>
                )}
              </span>
            </div>
          </>
        )}

        {leg.stones.length > 0 && (
          <div className="space-y-3 border-t border-slate-100 pt-3">
            <div>
              <p className="eyebrow">Where the stones went</p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
                Stones inside a finished piece can't be weighed, so state what was set. What is
                left over — neither set, returned nor broken — is what he owes.
              </p>
            </div>
            {leg.stones.map((s) => {
              const owed = owedCt(s);
              const over = overAccounted(s);
              return (
                <div key={s.id} className="rounded-xl border border-slate-200 p-3">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-xs font-medium text-slate-800">
                      {s.stone_name ?? `#${s.stone_id}`}
                    </span>
                    <span className="num text-[11px] text-slate-500">
                      {wt(s.weight_issued_ct, "ct")} · {s.quantity_issued} out
                    </span>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <TextField
                      label="Set — qty"
                      type="number"
                      min={0}
                      max={s.quantity_issued}
                      value={lineOf(s.id).setQty}
                      onChange={(e) => setReturn(s.id, { setQty: e.target.value })}
                    />
                    <TextField
                      label="Set — ct"
                      type="number"
                      step="0.0001"
                      min={0}
                      value={lineOf(s.id).setCt}
                      onChange={(e) => setReturn(s.id, { setCt: e.target.value })}
                    />
                    <TextField
                      label="Back whole — qty"
                      type="number"
                      min={0}
                      value={lineOf(s.id).qty}
                      onChange={(e) => setReturn(s.id, { qty: e.target.value })}
                    />
                    <TextField
                      label="Back whole — ct"
                      type="number"
                      step="0.0001"
                      min={0}
                      value={lineOf(s.id).ct}
                      onChange={(e) => setReturn(s.id, { ct: e.target.value })}
                    />
                    <TextField
                      label="Broken — qty"
                      type="number"
                      min={0}
                      value={lineOf(s.id).brokeQty}
                      onChange={(e) => setReturn(s.id, { brokeQty: e.target.value })}
                    />
                    <TextField
                      label="Broken — ct"
                      type="number"
                      step="0.0001"
                      min={0}
                      value={lineOf(s.id).brokeCt}
                      onChange={(e) => setReturn(s.id, { brokeCt: e.target.value })}
                    />
                  </div>
                  {over ? (
                    <p className="mt-2 text-[11px] leading-relaxed text-red-600">
                      That accounts for more than the {wt(s.weight_issued_ct, "ct")} issued.
                    </p>
                  ) : owed > 0 ? (
                    <p className="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-900">
                      <span className="num font-medium">{wt(owed, "ct")}</span> unaccounted for —
                      charged to {holder} at {fmtMoney(s.owed_rate_per_ct)}/ct ={" "}
                      <span className="num font-medium">
                        {fmtMoney(owed * Number(s.owed_rate_per_ct))}
                      </span>
                      .
                    </p>
                  ) : (
                    <p className="mt-2 text-[11px] text-slate-400">Every carat accounted for.</p>
                  )}
                  {Number(lineOf(s.id).brokeCt || 0) > 0 && (
                    <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                      Broken stones go to their own stock at cost — still the shop's, still
                      saleable.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <button
          className="btn-primary w-full"
          disabled={
            busy ||
            received === "" ||
            net < 0 ||
            !!stoneProblem ||
            (needsPurity && !recvPurity && !recvTunch)
          }
        >
          {busy ? "Receiving…" : "Receive and settle"}
        </button>
        {stoneProblem && (
          <p className="text-center text-[11px] text-red-600">
            {stoneProblem.stone_name ?? "A stone line"} accounts for more than was issued.
          </p>
        )}
      </form>

      <div className="mt-4 border-t border-slate-100 pt-3 text-center">
        <button
          className="text-xs text-slate-500 hover:text-red-600 hover:underline"
          onClick={() => setAskCancel(true)}
        >
          The piece isn't coming back — cancel this leg
        </button>
      </div>

      <PasswordConfirm
        open={askCancel}
        onClose={() => setAskCancel(false)}
        title={`Cancel leg #${leg.sequence} on ${designNo}?`}
        description={
          `This reverses the leg's postings. ${wt(leg.gold_issued_g)}` +
          (Number(leg.stones_issued_ct) ? ` and ${wt(leg.stones_issued_ct, "ct")}` : "") +
          " went out. Say what came back — anything you don't stays outstanding against the worker."
        }
        confirmLabel="Cancel leg"
        extraValid={
          cancelReason.trim().length > 0 &&
          Number(cancelGold || 0) <= issued &&
          Number(cancelStones || 0) <= Number(leg.stones_issued_ct)
        }
        extra={
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <TextField
                label={`Gold recovered (g) — max ${issued}`}
                type="number"
                step="0.0001"
                min="0"
                max={issued}
                value={cancelGold}
                onChange={(e) => setCancelGold(e.target.value)}
              />
              <TextField
                label={`Stones recovered (ct) — max ${Number(leg.stones_issued_ct)}`}
                type="number"
                step="0.0001"
                min="0"
                max={Number(leg.stones_issued_ct)}
                disabled={Number(leg.stones_issued_ct) <= 0}
                value={cancelStones}
                onChange={(e) => setCancelStones(e.target.value)}
              />
            </div>
            <TextField
              label="Reason"
              required
              placeholder="e.g. worker left, piece not returned"
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
            />
          </div>
        }
        onConfirm={confirmCancel}
      />
    </div>
  );
}

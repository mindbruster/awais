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
import { staticUrl } from "@/lib/url";
import { IssueSheet } from "@/pages/designs/IssueSheet";
import {
  DesignStatusChip,
  Figure,
  Leg,
  LegStatusChip,
  Metric,
  Settlement,
  Terms,
  allowanceOf,
  allowanceWorking,
  designStatusLabel,
  labourOn,
  labourWorking,
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
            <img
              src={staticUrl(design.image_url)}
              alt={design.design_no}
              className="h-20 w-20 flex-none rounded-xl border border-slate-200 object-cover"
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
              label="Gold issued"
              value={wt(leg.gold_issued_g)}
              sub={leg.gold_issued_purity ? `${leg.gold_issued_purity}k` : undefined}
            />
            <Figure
              label="Gold received"
              value={live ? "pending" : wt(leg.gold_received_g)}
              muted={live}
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
              // The stored reckoning, on the legs that have one and where the
              // purities actually differed. Legs closed before the fine columns
              // existed have nothing here and read exactly as they always did.
              fine={
                leg.wastage_allowed_fine_g !== null &&
                leg.gold_received_purity !== null &&
                leg.gold_received_purity !== leg.gold_issued_purity
                  ? {
                      allowed: Number(leg.wastage_allowed_fine_g),
                      actual: Number(leg.wastage_actual_fine_g),
                      excess: Number(leg.wastage_excess_fine_g),
                    }
                  : undefined
              }
              terms={terms}
              worker={leg.worker_name}
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

function ReceivePanel({
  leg,
  designNo,
  reload,
}: {
  leg: Leg;
  designNo: string;
  reload: () => void;
}) {
  const [received, setReceived] = useState("");
  // Blank means "the same metal came back", which is the ordinary case and the
  // one the server reads a null as. Only the maker's leg fills this in.
  const [receivedPurity, setReceivedPurity] = useState("");
  const [returns, setReturns] = useState<Record<number, { qty: string; ct: string }>>({});
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [askCancel, setAskCancel] = useState(false);
  const [cancelGold, setCancelGold] = useState("");
  const [cancelStones, setCancelStones] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  const issued = Number(leg.gold_issued_g);
  const terms: Terms = termsOf(leg);
  // Typed weight, not the committed one: this is what makes the settlement
  // visible before the operator signs off on it.
  const backPurity = receivedPurity === "" ? null : Number(receivedPurity);
  const preview = settle(issued, Number(received || 0), terms, backPurity);
  const labour = labourOn(leg, Number(received || 0));
  const holder = leg.worker_name ?? "the bench";

  const setReturn = (id: number, patch: Partial<{ qty: string; ct: string }>) =>
    setReturns((r) => ({ ...r, [id]: { ...(r[id] ?? { qty: "", ct: "" }), ...patch } }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/designs/legs/${leg.id}/receive`, {
        gold_received_g: received || "0",
        gold_received_purity: backPurity,
        stones: leg.stones.map((s) => ({
          leg_stone_id: s.id,
          quantity_returned: Number(returns[s.id]?.qty || 0),
          weight_returned_ct: returns[s.id]?.ct || "0",
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
          label="Gold received (g)"
          type="number"
          step="0.0001"
          min={0}
          required
          autoFocus
          value={received}
          onChange={(e) => setReceived(e.target.value)}
          hint="Heavier than issued is fine — solder and findings add weight"
        />

        {/* Pure metal goes out to the maker and 21k jewellery comes back. Left
            blank the piece is taken to be the same metal that was issued,
            which is what every other stage returns. */}
        <TextField
          label="Purity back (k)"
          type="number"
          step="1"
          min={1}
          max={24}
          value={receivedPurity}
          onChange={(e) => setReceivedPurity(e.target.value)}
          hint={
            leg.gold_issued_purity
              ? `Blank means it came back at ${leg.gold_issued_purity}k, as issued`
              : "Blank means it came back as issued"
          }
        />

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
              // Only once the two ends differ — on an ordinary leg the two
              // readings are the same number and showing both would suggest a
              // distinction the operator does not have to think about.
              fine={
                preview.mixed
                  ? {
                      allowed: preview.allowedFine,
                      actual: preview.actualFine,
                      excess: preview.excessFine,
                    }
                  : undefined
              }
              terms={terms}
              worker={leg.worker_name}
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
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <p className="eyebrow">Stones returned</p>
            {leg.stones.map((s) => (
              <div key={s.id} className="grid grid-cols-2 gap-2">
                <TextField
                  label={`${s.stone_name ?? `#${s.stone_id}`} qty (of ${s.quantity_issued})`}
                  type="number"
                  min={0}
                  max={s.quantity_issued}
                  value={returns[s.id]?.qty ?? ""}
                  onChange={(e) => setReturn(s.id, { qty: e.target.value })}
                />
                <TextField
                  label={`ct (of ${Number(s.weight_issued_ct)})`}
                  type="number"
                  step="0.0001"
                  min={0}
                  max={Number(s.weight_issued_ct)}
                  value={returns[s.id]?.ct ?? ""}
                  onChange={(e) => setReturn(s.id, { ct: e.target.value })}
                />
              </div>
            ))}
          </div>
        )}

        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <button className="btn-primary w-full" disabled={busy || received === ""}>
          {busy ? "Receiving…" : "Receive and settle"}
        </button>
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

/**
 * The shared vocabulary of the design feature.
 *
 * The list, the detail page and the issue sheet all render the same handful of
 * things — a status, a weight, a wastage settlement — and they have to render
 * them identically: an operator who learns that amber means "out with someone"
 * on one screen must not meet a different amber on the next. The types, the
 * arithmetic and the components for those live here rather than being restated
 * per page, which is also how the settlement preview and the settled leg stay
 * guaranteed to draw the same picture.
 */
import { ReactNode } from "react";
import { fmtMoney } from "@/lib/money";

export type WastageBasis = "percent_of_issued" | "per_100_pieces";
export type LegStatus = "issued" | "received" | "cancelled";

export interface LegStone {
  id: number;
  stone_id: number;
  stone_name: string | null;
  quantity_issued: number;
  weight_issued_ct: string;
  quantity_returned: number;
  weight_returned_ct: string;
  rate_per_ct: string;
}

export interface Leg {
  id: number;
  sequence: number;
  department_id: number;
  department_name: string | null;
  worker_id: number | null;
  worker_name: string | null;
  status: LegStatus;
  issued_at: string | null;
  gold_issued_g: string;
  gold_issued_purity: number | null;
  stones_issued_ct: string;
  received_at: string | null;
  gold_received_g: string;
  stones_used_ct: string;
  stones_returned_ct: string;
  piece_count: number;
  wastage_basis: WastageBasis;
  wastage_per_100_pcs_g: string | null;
  wastage_allowed_pct: string | null;
  wastage_allowed_g: string;
  wastage_actual_g: string;
  wastage_excess_g: string;
  labour_basis: string;
  labour_rate: string;
  labour_amount: string;
  notes: string | null;
  stones: LegStone[];
}

/* ------------------------------------------------------------------ numbers */

// The backend quantises every weight to four places before it settles wastage;
// a preview that rounds differently would show the operator one number and
// commit another.
export const round4 = (n: number) => Math.round(n * 1e4) / 1e4;

export function wt(
  v: string | number | null | undefined,
  unit: "g" | "ct" = "g",
): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 4 })} ${unit}`;
}

// Grams are quoted to three places on the floor — 0.400 per 100, not 0.4.
export const g3 = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 4 });

export function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/**
 * How long ago, in the terms a shop chasing a piece uses. A worklist is read
 * to find what has been sitting too long, and "14d" answers that where a date
 * makes the reader do the subtraction.
 */
export function age(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const days = Math.floor(ms / 86_400_000);
  if (days < 1) return "today";
  if (days < 30) return `${days}d`;
  const months = Math.floor(days / 30);
  return months < 12 ? `${months}mo` : `${Math.floor(days / 365)}y`;
}

/* ------------------------------------------------------------------ statuses */

export const DESIGN_STATUSES = [
  { value: "", label: "All" },
  { value: "in_production", label: "In production" },
  { value: "stocked", label: "Stocked" },
  { value: "sold", label: "Sold" },
  { value: "cancelled", label: "Cancelled" },
];

/** Human wording for a design status. `replace("_", " ")` only ever caught the
 *  first underscore, and "in production" is worth saying properly anyway. */
export function designStatusLabel(status: string): string {
  return DESIGN_STATUSES.find((s) => s.value === status)?.label ?? status.replace(/_/g, " ");
}

export function designChipClass(status: string): string {
  switch (status) {
    case "in_production":
      return "chip-out";
    case "stocked":
      return "chip-back";
    case "sold":
      return "chip-idle";
    default:
      return "chip-dead";
  }
}

export function DesignStatusChip({ status }: { status: string }) {
  return (
    <span className={designChipClass(status)}>
      <span
        className={`dot ${
          status === "in_production"
            ? "bg-amber-500"
            : status === "stocked"
            ? "bg-emerald-500"
            : status === "sold"
            ? "bg-slate-400"
            : "bg-slate-400"
        }`}
        aria-hidden
      />
      {designStatusLabel(status)}
    </span>
  );
}

export function LegStatusChip({ status }: { status: LegStatus }) {
  if (status === "issued") {
    return (
      <span className="chip-out">
        <span className="dot bg-amber-500" aria-hidden />
        Out with worker
      </span>
    );
  }
  if (status === "cancelled") {
    return (
      <span className="chip-dead">
        <span className="dot bg-slate-400" aria-hidden />
        Cancelled
      </span>
    );
  }
  return (
    <span className="chip-back">
      <span className="dot bg-emerald-500" aria-hidden />
      Received
    </span>
  );
}

/* ------------------------------------------------------- wastage and labour */

/** The terms a leg settles on, read off the leg — never off the department. */
export interface Terms {
  basis: WastageBasis;
  allowedPct: number;
  per100: number;
  pieces: number;
}

export function termsOf(leg: Leg): Terms {
  return {
    basis: leg.wastage_basis,
    allowedPct: Number(leg.wastage_allowed_pct ?? 0),
    per100: Number(leg.wastage_per_100_pcs_g ?? 0),
    pieces: leg.piece_count,
  };
}

export function allowanceOf(t: Terms, issued: number): number {
  return t.basis === "per_100_pieces"
    ? round4((t.per100 * t.pieces) / 100)
    : round4((issued * t.allowedPct) / 100);
}

export function settle(issued: number, received: number, t: Terms) {
  const allowed = allowanceOf(t, issued);
  const actual = round4(issued - received);
  return { allowed, actual, excess: Math.max(round4(actual - allowed), 0) };
}

/**
 * The allowance spelled out as the shop works it out, so the operator can check
 * the arithmetic rather than trust the number.
 */
export function allowanceWorking(t: Terms, allowed: number): string {
  return t.basis === "per_100_pieces"
    ? `${t.pieces} pcs × ${g3(t.per100)}g/100 = ${g3(allowed)} g allowed`
    : `${t.allowedPct}% of issued`;
}

/** The same terms in a phrase, for "X beyond the … agreed with him". */
export function termsPhrase(t: Terms): string {
  return t.basis === "per_100_pieces"
    ? `${g3(t.per100)}g per 100 pieces`
    : `${t.allowedPct}%`;
}

/** What the worker earns, on the basis this leg was issued under. */
export function labourOn(leg: Leg, receivedG: number): number {
  const rate = Number(leg.labour_rate);
  if (leg.labour_basis === "per_gram") return rate * receivedG;
  if (leg.labour_basis === "per_piece") return rate * leg.piece_count;
  return rate;
}

/**
 * The per-piece charge as a sum: "350 stones × ₨ 5.00 = ₨ 1,750.00". Anything
 * else is shown as the plain amount — there is nothing to show a working for.
 */
export function labourWorking(leg: Leg, amount: number): string | undefined {
  if (leg.labour_basis !== "per_piece") return undefined;
  const noun = leg.stones.length > 0 ? "stones" : "pcs";
  return `${leg.piece_count} ${noun} × ${fmtMoney(leg.labour_rate)} = ${fmtMoney(amount)}`;
}

/* --------------------------------------------------------------- components */

export function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "good" | "bad" | "gain";
}) {
  const colour =
    tone === "bad"
      ? "text-red-600"
      : tone === "good"
      ? "text-emerald-700"
      : tone === "gain"
      ? "text-sky-700"
      : "text-slate-900";
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p className={`num-lg mt-1 ${colour}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

/** A smaller Metric, for the grid of figures inside a leg card. */
export function Figure({
  label,
  value,
  sub,
  muted,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  muted?: boolean;
}) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p className={`num mt-0.5 text-sm ${muted ? "text-slate-400" : "text-slate-900"}`}>
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs leading-snug text-slate-500">{sub}</p>}
    </div>
  );
}

/**
 * Allowed vs actual vs excess, drawn the same way whether it is a settled leg
 * or a live preview — the operator should recognise the number he approved.
 */
export function Settlement({
  allowed,
  actual,
  excess,
  terms,
  worker,
  className = "",
}: {
  allowed: number;
  actual: number;
  excess: number;
  terms: Terms;
  worker: string | null;
  className?: string;
}) {
  const gain = actual < 0;
  const span = Math.max(allowed, actual, 0.0001);
  const pct = (v: number) => `${Math.min(100, Math.max(0, (v / span) * 100))}%`;
  const within = Math.min(Math.max(actual, 0), allowed);

  return (
    <div className={`rounded-xl border border-slate-200 bg-slate-50/70 p-3 ${className}`}>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <p className="eyebrow">Allowed</p>
          <p className="num mt-0.5 text-sm font-medium text-slate-900">{wt(allowed)}</p>
          <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
            {allowanceWorking(terms, allowed)}
          </p>
        </div>
        <div>
          <p className="eyebrow">{gain ? "Gain" : "Actual"}</p>
          <p
            className={`num mt-0.5 text-sm font-medium ${
              gain ? "text-sky-700" : "text-slate-900"
            }`}
          >
            {wt(gain ? -actual : actual)}
          </p>
          <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
            {gain ? "came back heavier" : "issued − received"}
          </p>
        </div>
        <div>
          <p className="eyebrow">Excess</p>
          <p
            className={`num mt-0.5 text-sm font-medium ${
              excess > 0 ? "text-red-600" : "text-emerald-700"
            }`}
          >
            {wt(excess)}
          </p>
          <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
            {excess > 0 ? "worker's liability" : "within allowance"}
          </p>
        </div>
      </div>

      {gain ? (
        <p className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-xs leading-relaxed text-sky-900">
          The piece came back {wt(-actual)} heavier than it went out — solder, alloy and findings
          do that. Nothing is owed.
        </p>
      ) : (
        <>
          <div className="relative mt-3 h-2 rounded-full bg-slate-200">
            <div
              className="absolute inset-y-0 left-0 rounded-l-full bg-emerald-400"
              style={{ width: pct(within) }}
            />
            <div
              className="absolute inset-y-0 rounded-r-full bg-red-500"
              style={{ left: pct(within), width: pct(excess) }}
            />
            <div
              className="absolute -inset-y-1 w-px bg-slate-600"
              style={{ left: pct(allowed) }}
              title="Allowance"
            />
          </div>
          {excess > 0 && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-800">
              {wt(excess)} beyond the {termsPhrase(terms)} agreed with {worker ?? "this worker"} —
              charged back to him, not to the shop.
            </p>
          )}
        </>
      )}
    </div>
  );
}

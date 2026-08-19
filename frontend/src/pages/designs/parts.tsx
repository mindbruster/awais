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

export type WastageBasis = "percent_of_issued" | "per_100_pieces" | "ratti_of_received";
export type LegStatus = "issued" | "received" | "cancelled";
export type Metal = "gold" | "silver";

// A carat is a fifth of a gram, by definition. The one place stones are spoken
// of in grams is the reckoning with a setter, who hands back one object on one
// scale — so the stones he set have to come out of that weight to leave the
// metal alone.
export const CARATS_PER_G = 5;

export interface LegStone {
  id: number;
  stone_id: number;
  stone_name: string | null;
  quantity_issued: number;
  weight_issued_ct: string;
  quantity_set: number;
  weight_set_ct: string;
  quantity_returned: number;
  weight_returned_ct: string;
  quantity_broken: number;
  weight_broken_ct: string;
  weight_owed_ct: string;
  rate_per_ct: string;
  owed_rate_per_ct: string;
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
  metal: Metal;
  gold_issued_g: string;
  gold_issued_purity: number | null;
  gold_issued_tunch_pct: string | null;
  stones_issued_ct: string;
  /** Metal and stones on one scale, as the shop states what it handed over. */
  gold_issued_with_stones_g: string;
  received_at: string | null;
  // What the scale read, stones and all, and the metal left once the set
  // stones come back out. Equal on a leg carrying no stones.
  gold_received_gross_g: string;
  gold_received_g: string;
  gold_received_purity: number | null;
  gold_received_tunch_pct: string | null;
  // Where every issued carat went: set + returned + broken + owed = issued.
  stones_set_ct: string;
  stones_used_ct: string;
  stones_returned_ct: string;
  stones_broken_ct: string;
  stones_owed_ct: string;
  piece_count: number;
  wastage_basis: WastageBasis;
  wastage_per_100_pcs_g: string | null;
  wastage_pieces_base: number;
  wastage_allowed_pct: string | null;
  wastage_ratti: string | null;
  wastage_ratti_base: number;
  wastage_allowed_g: string;
  wastage_actual_g: string;
  wastage_excess_g: string;
  // The reckoning that actually settled. Once a maker returns 21k against
  // issued 24k the raw trio above compares two different assets, and only
  // these can be subtracted from one another.
  wastage_allowed_fine_g: string | null;
  wastage_actual_fine_g: string | null;
  wastage_excess_fine_g: string | null;
  metal_due_date: string | null;
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
  // A lot whose metal came back and was divided into pieces. Its own state
  // rather than "cancelled" or a silent absence: the row is real history — the
  // dealing with the maker and the ledger entries hang off it — but it is not
  // a thing on the bench and must never sit in a worklist of pieces to be made.
  { value: "split", label: "Divided into pieces" },
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
    case "split":
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
  // How many pieces `per100` is quoted against. A hundred is the common case
  // and never the only one; the deal is struck in whatever number the two of
  // them argue in.
  piecesBase: number;
  ratti: number;
  rattiBase: number;
  issuedPurity: number | null;
  issuedTunch: number | null;
}

export function termsOf(leg: Leg): Terms {
  return {
    basis: leg.wastage_basis,
    allowedPct: Number(leg.wastage_allowed_pct ?? 0),
    per100: Number(leg.wastage_per_100_pcs_g ?? 0),
    pieces: leg.piece_count,
    piecesBase: leg.wastage_pieces_base || 100,
    ratti: Number(leg.wastage_ratti ?? 0),
    rattiBase: leg.wastage_ratti_base || 96,
    issuedPurity: leg.gold_issued_purity,
    issuedTunch: leg.gold_issued_tunch_pct === null ? null : Number(leg.gold_issued_tunch_pct),
  };
}

/**
 * How much of a weight is pure metal.
 *
 * Tunch wins wherever it is present: it is the fineness as the trade quotes it
 * — 91.6, 99.9, 92.5 — and a karat integer cannot express those. Karat is the
 * fallback, and "neither stated" means pure, which is how bullion is entered.
 * Silver only ever arrives here as a tunch; the /24 scale would call 925 silver
 * thirty-eight karat.
 */
export function fineFactor(purity: number | null, tunch: number | null): number {
  if (tunch) return tunch / 100;
  if (purity) return purity / 24;
  return 1;
}

/**
 * The metal in a returned piece, from what the scale said.
 *
 * A setter hands back one object. The gram figure includes the stones he set
 * into it, so comparing it against the metal issued compares two different
 * things — on a piece carrying 30ct the gross reads six grams heavy, four
 * times any allowance the shop would agree.
 */
export function netMetal(grossG: number, setCt: number): number {
  return round4(grossG - setCt / CARATS_PER_G);
}

export function allowanceOf(t: Terms, issued: number, received = 0): number {
  if (t.basis === "ratti_of_received") {
    // The maker's convention, and the only one measured against what came
    // *back*: 6 ratti on 107.560g of 21k allows 6.7225g of 21k, added to what
    // he is credited with before the sum is converted to pure.
    return round4((received / t.rattiBase) * t.ratti);
  }
  if (t.basis === "per_100_pieces")
    return round4((t.per100 * t.pieces) / (t.piecesBase || 100));
  return round4((issued * t.allowedPct) / 100);
}

/**
 * The settlement, in both the units it is spoken in and the one it settles in.
 *
 * Mirrors `settle_wastage` on the server, and has to: this is what the operator
 * reads before committing, and a preview that computes differently would show
 * one number and post another.
 *
 * The fine figures are the ones that mean anything once the two ends of a job
 * differ in purity. Pure metal goes to a maker and 21k comes back; subtracting
 * those raw is subtracting apples from oranges, and it reads as the maker
 * having *gained* seven grams on a job he is actually short on.
 */
export function settle(
  issued: number,
  received: number,
  t: Terms,
  recvPurity: number | null = null,
  recvTunch: number | null = null,
) {
  const ratti = t.basis === "ratti_of_received";
  // Both halves of the received pair, or neither. Falling back field by field
  // would let an issued tunch of 99.9 override a stated received karat of 21.
  const usingRecv = recvPurity !== null || recvTunch !== null;
  const recvFactor = usingRecv
    ? fineFactor(recvPurity, recvTunch)
    : fineFactor(t.issuedPurity, t.issuedTunch);
  const issuedFactor = fineFactor(t.issuedPurity, t.issuedTunch);
  // A ratti allowance is denominated in the karat that came back; the other
  // two are grams of the metal that went out.
  const allowFactor = ratti ? recvFactor : issuedFactor;

  const allowed = allowanceOf(t, issued, received);
  const fineIssued = round4(issued * issuedFactor);
  const fineRecv = round4(received * recvFactor);
  const fineAllowed = round4(allowed * allowFactor);
  const fineActual = round4(fineIssued - fineRecv);
  // On the maker's ratti the allowance is metal he is *entitled* to keep, so an
  // unused part is owed back to him and the figure is signed. A percentage or a
  // per-100 figure is only a cap on what he can be charged, so it floors at 0.
  const fineExcess = ratti
    ? round4(fineActual - fineAllowed)
    : Math.max(round4(fineActual - fineAllowed), 0);

  return {
    allowed,
    // Raw actual is meaningless across a purity change — restated in the karat
    // that came back, the way the server stores it.
    actual: ratti && recvFactor ? round4(fineActual / recvFactor) : round4(issued - received),
    excess: ratti && recvFactor ? round4(fineExcess / recvFactor) : Math.max(round4(issued - received - allowed), 0),
    fineAllowed,
    fineActual,
    fineExcess,
    crossPurity: round4(issuedFactor * 1e4) !== round4(recvFactor * 1e4),
  };
}

/**
 * The allowance spelled out as the shop works it out, so the operator can check
 * the arithmetic rather than trust the number.
 */
export function allowanceWorking(t: Terms, allowed: number): string {
  if (t.basis === "ratti_of_received")
    return `${t.ratti} ratti of ${t.rattiBase} on what comes back = ${g3(allowed)} g allowed`;
  return t.basis === "per_100_pieces"
    ? `${t.pieces} pcs × ${g3(t.per100)}g/${t.piecesBase || 100} = ${g3(allowed)} g allowed`
    : `${t.allowedPct}% of issued`;
}

/** The same terms in a phrase, for "X beyond the … agreed with him". */
export function termsPhrase(t: Terms): string {
  if (t.basis === "ratti_of_received") return `${t.ratti} ratti of ${t.rattiBase}`;
  return t.basis === "per_100_pieces"
    ? `${g3(t.per100)}g per ${t.piecesBase || 100} pieces`
    : `${t.allowedPct}%`;
}

export const WASTAGE_BASES: { value: WastageBasis; label: string; hint: string }[] = [
  {
    value: "percent_of_issued",
    label: "Percent of what goes out",
    hint: "What casting and goldsmithing work on.",
  },
  {
    value: "per_100_pieces",
    label: "Grams per 100 pieces",
    hint: "What setting works on — a setter's loss follows how many stones he handles, not how heavy the piece is.",
  },
  {
    value: "ratti_of_received",
    label: "Ratti of what comes back",
    hint: "The maker's convention: quoted 1 to 24 against 96, worked out on the weight he returns and added to his credit.",
  },
];

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
  fine,
  given,
  back,
  stonesSetCt,
}: {
  allowed: number;
  actual: number;
  excess: number;
  terms: Terms;
  worker: string | null;
  className?: string;
  // The two weights the difference came from. The UI specification's "critical
  // UX rule" is that a calculated gold movement shows its working rather than
  // only its answer, and it names disputes as the reason. "4.000 g short" is
  // an assertion; "106.000 given − 102.000 back = 4.000" is something the
  // karigar standing at the counter can check against his own scale, which is
  // the difference between a figure he accepts and one he argues with.
  given?: number | null;
  back?: number | null;
  /**
   * Carats that stayed in the piece, when this leg set stones.
   *
   * Set rather than issued, and the distinction is not cosmetic: what the
   * server subtracted is the stone weight now *inside* the returned piece.
   * Stones the setter did not use came back as stones and are settled in the
   * carat columns, so counting them here would inflate the given side and
   * invent a shortage that the ledger never posted.
   */
  stonesSetCt?: number | null;
  // The same three in fine grams, when the two ends of the job differ in
  // purity. Shown alongside rather than instead: the raw figures are what the
  // scale read and what the worker will argue about, the fine ones are what
  // actually settled his account.
  fine?: { allowed: number; actual: number; excess: number } | null;
}) {
  const gain = actual < 0;
  const span = Math.max(allowed, actual, 0.0001);
  const pct = (v: number) => `${Math.min(100, Math.max(0, (v / span) * 100))}%`;
  const within = Math.min(Math.max(actual, 0), allowed);

  const stoneG = (stonesSetCt ?? 0) / CARATS_PER_G;
  const totalGiven = given != null ? round4(given + stoneG) : null;
  const showWorking = totalGiven != null && back != null && totalGiven > 0;

  return (
    <div className={`rounded-xl border border-slate-200 bg-slate-50/70 p-3 ${className}`}>
      {showWorking && (
        <div className="mb-3 border-b border-slate-200 pb-3">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
            <span className="num font-medium text-slate-900">{wt(totalGiven!)}</span>
            <span className="text-xs text-slate-500">given</span>
            <span className="text-slate-400">−</span>
            <span className="num font-medium text-slate-900">{wt(back!)}</span>
            <span className="text-xs text-slate-500">back</span>
            <span className="text-slate-400">=</span>
            <span className={`num font-medium ${gain ? "text-sky-700" : "text-slate-900"}`}>
              {wt(Math.abs(round4(totalGiven! - back!)))}
            </span>
            <span className="text-xs text-slate-500">
              {gain ? "heavier" : "difference"}
            </span>
          </div>
          {stoneG > 0 && (
            <p className="num mt-1 text-[11px] leading-snug text-slate-500">
              {wt(given!)} metal + {wt(stoneG)} of stones set ({(stonesSetCt ?? 0).toFixed(2)}{" "}
              ct ÷ {CARATS_PER_G})
            </p>
          )}
        </div>
      )}
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

      {fine && (
        <div className="mt-3 rounded-lg bg-white px-3 py-2 ring-1 ring-slate-200">
          <p className="eyebrow">Settled in fine grams</p>
          <p className="num mt-1 text-[11px] leading-relaxed text-slate-600">
            {wt(fine.allowed)} allowed · {wt(fine.actual)} short ·{" "}
            <span
              className={
                fine.excess > 0
                  ? "font-medium text-red-600"
                  : fine.excess < 0
                  ? "font-medium text-sky-700"
                  : "font-medium text-emerald-700"
              }
            >
              {wt(Math.abs(fine.excess))}{" "}
              {fine.excess > 0 ? "owed by" : fine.excess < 0 ? "owed to" : "square with"}{" "}
              {worker ?? "the bench"}
            </span>
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
            What went out and what came back are different purities, so they can only be
            subtracted as pure metal. The grams above are what the scale read.
          </p>
        </div>
      )}

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

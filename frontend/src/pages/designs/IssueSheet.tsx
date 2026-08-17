/**
 * Issuing a piece to a department.
 *
 * This used to be a twelve-field form folded into a 22rem sidebar column, with
 * stone lines nested inside it, and a single button that posted an irreversible
 * ledger entry and deducted stock the moment it was clicked. Two things are
 * different here. The form gets the width it needs and is broken into the four
 * questions the counter is actually answering — where it goes, what goes out,
 * on what terms, and which stones — with a running summary of the terms that
 * are about to be *frozen onto the leg* beside it. And the commit is a two-step:
 * the operator reads back what will happen before it happens, because cancelling
 * this afterwards costs a password and a reversing journal entry.
 */
import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { Sheet } from "@/components/Sheet";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";
import {
  Metal,
  WASTAGE_BASES,
  WastageBasis,
  allowanceOf,
  g3,
  round4,
  wt,
} from "@/pages/designs/parts";

interface Department {
  id: number;
  name: string;
  consumes_stones: boolean;
  default_wastage_basis: WastageBasis;
  default_wastage_per_100_pcs_g: string | null;
  default_wastage_pieces_base: number | null;
  default_rate_per_piece: string | null;
}

interface Worker {
  id: number;
  name: string;
  department_id: number | null;
  effective_wastage_pct: string | null;
  is_active: boolean;
}

interface InvItem {
  id: number;
  label: string;
  weight_g: string;
  weight_ct: string;
  purity: number | null;
}

interface Stone {
  id: number;
  name: string;
  default_rate_per_ct: string | null;
}

interface StoneLine {
  key: number;
  stone_id: string;
  qty: string;
  ct: string;
  rate: string;
}

const LABOUR_BASES = [
  { value: "per_gram", label: "Per gram received" },
  { value: "per_piece", label: "Per piece" },
  { value: "flat", label: "Flat amount" },
];

let nextStoneKey = 1;

function Section({
  step,
  title,
  hint,
  children,
}: {
  step: number;
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <div className="flex items-baseline gap-2.5">
        <span className="flex h-5 w-5 flex-none items-center justify-center rounded-full bg-brand-100 text-[11px] font-semibold text-brand-800">
          {step}
        </span>
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
        </div>
      </div>
      <div className="mt-4 space-y-3">{children}</div>
    </section>
  );
}

function SummaryRow({
  label,
  value,
  working,
  tone,
}: {
  label: string;
  value: ReactNode;
  working?: ReactNode;
  tone?: "muted";
}) {
  return (
    <div className="flex items-start justify-between gap-3 py-2">
      <span className="flex-none text-xs text-slate-500">{label}</span>
      <span className="min-w-0 text-right">
        <span
          className={`num block text-sm ${
            tone === "muted" ? "text-slate-400" : "font-medium text-slate-900"
          }`}
        >
          {value}
        </span>
        {working && (
          <span className="num mt-0.5 block text-[11px] leading-snug text-slate-500">
            {working}
          </span>
        )}
      </span>
    </div>
  );
}

export function IssueSheet({
  open,
  onClose,
  designId,
  designNo,
  onIssued,
}: {
  open: boolean;
  onClose: () => void;
  designId: number;
  designNo: string;
  onIssued: () => void;
}) {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [goldSources, setGoldSources] = useState<InvItem[]>([]);
  const [silverSources, setSilverSources] = useState<InvItem[]>([]);
  const [stoneSources, setStoneSources] = useState<InvItem[]>([]);
  const [stones, setStones] = useState<Stone[]>([]);
  const [loaded, setLoaded] = useState(false);

  const [deptId, setDeptId] = useState("");
  // "" is a real choice here — the shop's own bench — so it is only ever set
  // deliberately, never used as "nothing picked yet".
  const [workerId, setWorkerId] = useState("");
  const [goldSrc, setGoldSrc] = useState("");
  const [gold, setGold] = useState("");
  const [purity, setPurity] = useState("22");
  // Silver is quoted out of a thousand and gold in karat. The two are not two
  // ways of saying the same thing, so silver states a fineness here and the
  // karat box is not offered at all — there is no such thing as 21k silver.
  const [metal, setMetal] = useState<Metal>("gold");
  const [tunch, setTunch] = useState("");
  const [basis, setBasis] = useState("per_gram");
  const [rate, setRate] = useState("0");
  const [pieces, setPieces] = useState("");
  const [per100, setPer100] = useState("");
  // The number of pieces the figure above is quoted against. A hundred is the
  // common way to say it, not the only one — deals are struck per 50, per 250,
  // per 1000, and hard-coding a hundred made those unrecordable.
  const [piecesBase, setPiecesBase] = useState("100");
  // The wastage convention, chosen rather than inherited. The department's
  // default fills it in, but a maker on ratti and a setter on per-100 can both
  // be legitimate at the same stage, and the leg is frozen on what is sent.
  const [wastageBasis, setWastageBasis] = useState<WastageBasis>("percent_of_issued");
  const [ratti, setRatti] = useState("");
  // Only meaningful when the shop issues nothing: the maker works on his own
  // gold and is owed it back by this date. A promise nobody wrote down is one
  // nobody chases, so the server requires it on a zero-weight leg.
  const [dueDate, setDueDate] = useState("");
  const [lines, setLines] = useState<StoneLine[]>([]);
  const [stoneSrc, setStoneSrc] = useState("");
  const [notes, setNotes] = useState("");

  const [stage, setStage] = useState<"form" | "review">("form");
  const [busy, setBusy] = useState(false);

  // The workshop reference data is only worth fetching once the sheet is asked
  // for. The old panel fired five requests on every visit to the design page,
  // including the ones where the piece was already out and the form could not
  // be shown at all.
  useEffect(() => {
    if (!open || loaded) return;
    Promise.all([
      api.get<Department[]>("/departments", { params: { is_active: true } }),
      api.get<Worker[]>("/vendors", { params: { limit: 500 } }),
      api.get<InvItem[]>("/inventory", { params: { type: "raw_gold" } }),
      api.get<InvItem[]>("/inventory", { params: { type: "raw_stone" } }),
      api.get<Stone[]>("/stones", { params: { limit: 500 } }),
      // Silver stock is its own category. Offering the gold drawer for a
      // silver leg is refused by the API anyway, and would post to the silver
      // accounts while emptying the gold one.
      api.get<InvItem[]>("/inventory", { params: { type: "raw_silver" } }),
    ])
      .then(([d, w, ig, is, s, isv]) => {
        setDepartments(d.data);
        setWorkers(w.data);
        setGoldSources(ig.data);
        setSilverSources(isv.data);
        setStoneSources(is.data);
        setStones(s.data);
        setDeptId((prev) => prev || String(d.data[0]?.id ?? ""));
        setGoldSrc((prev) => prev || String(ig.data[0]?.id ?? ""));
        setStoneSrc((prev) => prev || String(is.data[0]?.id ?? ""));
        setLoaded(true);
      })
      .catch((e) => toast("error", apiError(e, "Could not load workshop data")));
  }, [open, loaded]);

  useEffect(() => {
    if (open) setStage("form");
  }, [open]);

  // The API refuses a worker who belongs to another department, so the choice
  // is narrowed here rather than explained after the fact.
  const eligible = useMemo(
    () => workers.filter((w) => w.is_active && String(w.department_id ?? "") === deptId),
    [workers, deptId],
  );

  useEffect(() => {
    setWorkerId((prev) =>
      eligible.some((w) => String(w.id) === prev) ? prev : String(eligible[0]?.id ?? ""),
    );
  }, [eligible]);

  const worker = eligible.find((w) => String(w.id) === workerId);
  const dept = departments.find((d) => String(d.id) === deptId);
  // Read off the chosen basis, not the department default: the operator can
  // switch a leg to another convention and every dependent field has to follow.
  const perPieces = wastageBasis === "per_100_pieces";

  // The department's standing terms are the shop's own numbers, so they are
  // filled in rather than asked for again. They stay editable: what is sent is
  // what the leg is frozen on, and one job can legitimately be off the norm.
  //
  // Both halves reset. Carrying setting's per-piece rate across to casting —
  // which the old form did — left the leg on a basis the new department does
  // not work in, and the API then refused it for a missing piece count.
  useEffect(() => {
    if (!dept) return;
    setPer100(dept.default_wastage_per_100_pcs_g ?? "");
    setPiecesBase(String(dept.default_wastage_pieces_base ?? 100));
    setWastageBasis(dept.default_wastage_basis ?? "percent_of_issued");
    if (dept.default_rate_per_piece !== null && dept.default_rate_per_piece !== undefined) {
      setBasis("per_piece");
      setRate(dept.default_rate_per_piece);
    } else {
      setBasis("per_gram");
      setRate("0");
    }
  }, [dept]);

  // Which drawer the metal comes out of follows the metal, and the selection
  // resets when it changes — a silver leg pointing at the gold vault is the one
  // mistake that empties one stock while crediting the other.
  const sources = metal === "silver" ? silverSources : goldSources;
  useEffect(() => {
    setGoldSrc((prev) =>
      sources.some((s) => String(s.id) === prev) ? prev : String(sources[0]?.id ?? ""),
    );
  }, [sources]);

  const goldSource = sources.find((g) => String(g.id) === goldSrc);
  const goldG = Number(gold || 0);
  const pieceN = Number(pieces || 0);
  const validLines = lines.filter((l) => l.stone_id && Number(l.ct) > 0);
  const stoneCt = round4(validLines.reduce((s, l) => s + Number(l.ct || 0), 0));

  const allowancePct = Number(worker?.effective_wastage_pct ?? 0);
  const onRatti = wastageBasis === "ratti_of_received";
  const allowanceG = allowanceOf(
    {
      basis: wastageBasis,
      allowedPct: allowancePct,
      per100: Number(per100 || 0),
      pieces: pieceN,
      piecesBase: Number(piecesBase || 100),
      ratti: Number(ratti || 0),
      rattiBase: 96,
      issuedPurity: null,
      issuedTunch: null,
    },
    goldG,
    // A ratti allowance is worked out on the weight that comes *back*, which
    // nobody knows yet. There is deliberately no guess here: showing one would
    // put a figure on the review screen that the settlement will not match.
    0,
  );
  const allowanceWorking = onRatti
    ? `${ratti || 0} ratti of 96, on what comes back`
    : perPieces
    ? `${pieceN} pcs × ${g3(Number(per100 || 0))}g/100`
    : `${allowancePct}% of ${wt(goldG)}`;

  const labourAmount =
    basis === "per_piece"
      ? Number(rate || 0) * pieceN
      : basis === "flat"
      ? Number(rate || 0)
      : 0; // per_gram settles on the weight that comes back, which isn't known yet
  const labourWorking =
    basis === "per_piece"
      ? `${pieceN} × ${fmtMoney(rate || 0)}`
      : basis === "flat"
      ? "flat, whatever comes back"
      : `${fmtMoney(rate || 0)} × grams received`;

  // Every one of these is refused by the API too. Blocking here saves the round
  // trip and, more to the point, says which answer is missing while the operator
  // is still looking at the field.
  const problems: string[] = [];
  if (!deptId) problems.push("Pick a department.");
  if (!goldSrc)
    problems.push(
      metal === "silver"
        ? "Pick which silver stock the metal comes out of."
        : "Pick which stock the gold comes out of.",
    );
  if (metal === "silver" && silverSources.length === 0)
    problems.push("There is no silver in stock to issue. Add a raw silver item first.");
  if (metal === "silver" && !tunch)
    problems.push(
      "Silver is quoted out of a thousand — enter its fineness (99.9 for the pure silver the shop buys).",
    );
  if (onRatti && !ratti)
    problems.push(
      "This leg settles in ratti, so it needs the agreed figure — with none the maker is charged the whole difference between the pure metal out and the jewellery back.",
    );
  if (onRatti && Number(ratti || 0) >= 96)
    problems.push("A ratti figure at or above 96 would allow the entire returned weight.");
  // Zero is a real deal on a ratti leg: the maker works on his own gold and
  // the shop owes it back by an agreed date. It is only meaningless under the
  // other conventions, where the excess floors at zero and his metal would
  // arrive credited to nobody.
  if (goldG < 0) problems.push("The metal going out cannot be negative.");
  if (goldG === 0 && !onRatti)
    problems.push(
      "A leg that issues no metal is the maker working on his own gold, so it has to settle in ratti — under any other convention his metal arrives and he is owed none of it.",
    );
  if (goldG === 0 && !dueDate)
    problems.push("This leg issues no metal, so the shop will owe it back — set the date it is due.");
  if (goldSource && goldG > Number(goldSource.weight_g))
    problems.push(
      `${goldSource.label} holds ${wt(goldSource.weight_g)} — less than the ${wt(goldG)} being issued.`,
    );
  if (wastageBasis === "per_100_pieces" && pieceN <= 0)
    problems.push(
      `This leg allows wastage per 100 pieces, so it needs a piece count — without one the allowance is zero and the worker carries the whole loss.`,
    );
  if (wastageBasis === "per_100_pieces" && !per100)
    problems.push(`No grams-per-100 figure is set for ${dept?.name}.`);
  if (basis === "per_piece" && pieceN <= 0)
    problems.push("Labour is charged per piece, so this leg needs a piece count — without one the worker is paid nothing.");
  if (validLines.length > 0 && !stoneSrc)
    problems.push("Pick which stock the stones come out of.");

  const ready = problems.length === 0;

  const holder = worker?.name ?? "the shop's own bench";

  const commit = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    try {
      await api.post(`/designs/${designId}/legs`, {
        department_id: Number(deptId),
        // null, not 0 — an in-house leg has no ledger party at all.
        worker_id: workerId ? Number(workerId) : null,
        metal,
        gold_issued_g: gold || "0",
        // Karat is gold's scale and the server refuses it on silver, so the
        // two are sent exclusively rather than both being filled in.
        gold_issued_purity: metal === "silver" ? null : purity ? parseInt(purity, 10) : null,
        gold_issued_tunch_pct: tunch || null,
        gold_source_inventory_id: Number(goldSrc),
        stones: validLines.map((l) => ({
          stone_id: Number(l.stone_id),
          quantity_issued: Number(l.qty || 0),
          weight_issued_ct: l.ct,
          rate_per_ct: l.rate || "0",
        })),
        stone_source_inventory_id: validLines.length ? Number(stoneSrc) : null,
        piece_count: pieceN,
        // Sent explicitly rather than left to the server's fallback so the leg
        // is frozen on exactly the terms shown on this form.
        wastage_basis: wastageBasis,
        wastage_per_100_pcs_g: wastageBasis === "per_100_pieces" ? per100 || "0" : null,
        wastage_pieces_base:
          wastageBasis === "per_100_pieces" ? Number(piecesBase || 100) : null,
        wastage_ratti: onRatti ? ratti || "0" : null,
        metal_due_date: dueDate || null,
        labour_basis: basis,
        labour_rate: rate || "0",
        notes: notes || null,
      });
      toast("success", `${designNo} issued to ${holder}`);
      setGold("");
      setNotes("");
      setPieces("");
      setLines([]);
      setStage("form");
      onIssued();
      onClose();
    } catch (err) {
      toast("error", apiError(err, "Could not issue"));
      setStage("form");
    } finally {
      setBusy(false);
    }
  };

  const summary = (
    <div className="card lg:sticky lg:top-0">
      <p className="eyebrow">This leg will be frozen on</p>
      <div className="mt-2 divide-y divide-slate-100">
        <SummaryRow
          label="Going to"
          value={dept?.name ?? "—"}
          working={worker ? worker.name : "in-house — the shop's own bench"}
        />
        <SummaryRow
          label={metal === "silver" ? "Silver out" : "Gold out"}
          value={goldG > 0 ? wt(goldG) : "—"}
          working={
            goldSource
              ? `${goldSource.label} · ${
                  metal === "silver"
                    ? `${tunch || "?"}% fine`
                    : tunch
                    ? `${tunch}% tunch`
                    : purity
                    ? `${purity}k`
                    : "purity not stated"
                }`
              : "no source picked"
          }
          tone={goldG > 0 ? undefined : "muted"}
        />
        <SummaryRow
          label="Stones out"
          value={stoneCt > 0 ? wt(stoneCt, "ct") : "none"}
          working={
            stoneCt > 0
              ? `${validLines.length} line${validLines.length === 1 ? "" : "s"}`
              : undefined
          }
          tone={stoneCt > 0 ? undefined : "muted"}
        />
        <SummaryRow
          label="Wastage allowed"
          // A ratti allowance is a fraction of a weight nobody has yet, so
          // there is no gram figure to show. Printing 0.0000 would read as
          // "he is allowed nothing", which is the opposite of the deal.
          value={onRatti ? "on receive" : wt(allowanceG)}
          working={allowanceWorking}
          tone={onRatti || allowanceG > 0 ? undefined : "muted"}
        />
        <SummaryRow
          label="Labour"
          value={basis === "per_gram" ? "on receive" : fmtMoney(labourAmount)}
          working={labourWorking}
          tone={basis === "per_gram" ? "muted" : undefined}
        />
      </div>

      {!worker && deptId && (
        <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
          In-house: the metal stays the shop's own. The leg tracks every gram, but there is no
          worker to owe a shortfall back, so any loss is the shop's cost.
        </p>
      )}
      {worker && allowanceG === 0 && goldG > 0 && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-900">
          No allowance is agreed with {worker.name}, so every gram short on return is charged
          back to him.
        </p>
      )}
    </div>
  );

  const review = (
    <div className="mx-auto max-w-xl space-y-4">
      <div className="rounded-xl border border-brand-200 bg-brand-50 p-5">
        <p className="eyebrow text-brand-700">
          {goldG === 0 ? "About to record" : "About to issue"}
        </p>
        {/* A zero-weight leg is not a small issue, it is a different deal —
            nothing leaves the safe and the shop takes on an obligation. Saying
            "issue 0 g" would describe the wrong event entirely. */}
        {goldG === 0 ? (
          <p className="mt-2 text-lg leading-snug text-brand-900">
            <span className="text-brand-800">No metal goes out.</span> {holder}{" "}
            <span className="text-brand-800">
              works on his own gold, and the shop owes it back by
            </span>{" "}
            <span className="font-semibold">{dueDate || "—"}</span>.
          </p>
        ) : (
          <p className="mt-2 text-lg leading-snug text-brand-900">
            <span className="num font-semibold">{wt(goldG)}</span>
            {purity ? <span className="text-brand-800"> of {purity}k gold</span> : null}
            {stoneCt > 0 && (
              <>
                {" and "}
                <span className="num font-semibold">{wt(stoneCt, "ct")}</span>
                <span className="text-brand-800"> of stones</span>
              </>
            )}{" "}
            <span className="text-brand-800">go out to</span> {holder}{" "}
            <span className="text-brand-800">at</span> {dept?.name}.
          </p>
        )}
      </div>

      <div className="card">
        <p className="eyebrow">What this commits</p>
        <ul className="mt-3 space-y-2 text-sm text-slate-700">
          <li className="flex gap-2">
            <span className="dot mt-1.5 bg-red-400" aria-hidden />
            <span>
              <span className="num font-medium">{wt(goldG)}</span> comes off{" "}
              {goldSource?.label ?? "stock"}
              {stoneCt > 0 && (
                <>
                  , and <span className="num font-medium">{wt(stoneCt, "ct")}</span> off{" "}
                  {stoneSources.find((s) => String(s.id) === stoneSrc)?.label ?? "stone stock"}
                </>
              )}
              .
            </span>
          </li>
          <li className="flex gap-2">
            <span className="dot mt-1.5 bg-amber-400" aria-hidden />
            <span>
              A journal entry moves the metal from Gold in Hand to{" "}
              {worker ? `Gold with Workers, against ${worker.name}` : "Gold with Workers"}, valued
              at today's rate.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="dot mt-1.5 bg-slate-400" aria-hidden />
            <span>
              The allowance of <span className="num font-medium">{wt(allowanceG)}</span> (
              {allowanceWorking}) is fixed onto this leg. Renegotiating the terms later will not
              change how it settles.
            </span>
          </li>
        </ul>
        <p className="mt-4 border-t border-slate-100 pt-3 text-xs leading-relaxed text-slate-500">
          Undoing this means cancelling the leg, which needs your password and posts a reversing
          entry. {designNo} cannot be issued anywhere else until this leg comes back.
        </p>
      </div>
    </div>
  );

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={stage === "review" ? "Check before issuing" : "Issue to department"}
      subtitle={
        <>
          <span className="font-mono">{designNo}</span>
          {dept ? ` · ${dept.name}` : ""}
          {stage === "form" ? " · nothing is committed until you review" : ""}
        </>
      }
      widthClass="max-w-4xl"
      footer={
        stage === "review" ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setStage("form")}>
              ← Back to the form
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={busy}
              onClick={() => commit()}
            >
              {busy
                ? "Recording…"
                : goldG === 0
                ? `Record what ${worker?.name ?? "the bench"} is owed`
                : `Issue ${wt(goldG)} to ${worker?.name ?? "the bench"}`}
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="min-w-0 flex-1 text-xs text-slate-500">
              {ready
                ? "Nothing has moved yet — the next screen shows exactly what will."
                : problems[0]}
            </p>
            <div className="flex flex-none gap-2">
              <button type="button" className="btn-ghost" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={!ready}
                onClick={() => setStage("review")}
              >
                Review issue
              </button>
            </div>
          </div>
        )
      }
    >
      {stage === "review" ? (
        review
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
          <div className="space-y-4">
            <Section
              step={1}
              title="Where it's going"
              hint="A piece is only ever in one pair of hands at a time."
            >
              <SelectField
                label="Department"
                required
                value={deptId}
                onChange={(e) => setDeptId(e.target.value)}
                options={departments.map((d) => ({ value: d.id, label: d.name }))}
              />
              {/* Not required. A stage the shop does on its own bench has no
                  outside worker holding the metal and nobody to charge a
                  shortfall to. Leaving this blank tracks the metal through the
                  leg without inventing a worker. */}
              <SelectField
                label="Worker"
                value={workerId}
                onChange={(e) => setWorkerId(e.target.value)}
                options={[
                  { value: "", label: "In-house — the shop's own bench" },
                  ...eligible.map((w) => ({ value: w.id, label: w.name })),
                ]}
                hint={
                  workerId
                    ? `${allowancePct}% wastage allowance, frozen onto this leg`
                    : "No outside worker holds the metal, so nothing can be charged back."
                }
              />
              {eligible.length === 0 && deptId && (
                <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
                  No worker is assigned to {dept?.name ?? "this department"}. That is fine for a
                  stage the shop does itself — otherwise add one under Workers and set their
                  department.
                </p>
              )}
            </Section>

            <Section step={2} title="What goes out" hint="Deducted from stock when you commit.">
              <SelectField
                label="Metal"
                value={metal}
                onChange={(e) => setMetal(e.target.value as Metal)}
                options={[
                  { value: "gold", label: "Gold" },
                  { value: "silver", label: "Silver" },
                ]}
                hint={
                  metal === "silver"
                    ? "Silver keeps its own stock and its own accounts — a gram of it never settles a gram of gold."
                    : undefined
                }
              />
              <SelectField
                label={metal === "silver" ? "Silver from" : "Gold from"}
                required
                value={goldSrc}
                onChange={(e) => setGoldSrc(e.target.value)}
                options={sources.map((g) => ({
                  value: g.id,
                  label: `${g.label} — ${wt(g.weight_g)}${g.purity ? `, ${g.purity}k` : ""}`,
                }))}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                  label={metal === "silver" ? "Silver (g)" : "Gold (g)"}
                  type="number"
                  step="0.0001"
                  min={0}
                  value={gold}
                  onChange={(e) => setGold(e.target.value)}
                  hint={
                    goldG === 0
                      ? "Zero means he works on his own metal and the shop owes it back"
                      : goldSource
                      ? `${wt(goldSource.weight_g)} on hand`
                      : undefined
                  }
                  error={
                    goldSource && goldG > Number(goldSource.weight_g)
                      ? `Only ${wt(goldSource.weight_g)} is in ${goldSource.label}`
                      : null
                  }
                />
                {/* Karat is gold's scale and stops at 24; silver is quoted out
                    of a thousand. Showing both boxes at once invites "21k
                    silver", which is not a thing and which the server refuses. */}
                {metal === "silver" ? (
                  <TextField
                    label="Fineness (%)"
                    type="number"
                    step="0.001"
                    min={0.001}
                    max={100}
                    required
                    value={tunch}
                    onChange={(e) => setTunch(e.target.value)}
                    placeholder="99.9"
                    hint="99.9 for 999 silver, 92.5 for 925"
                  />
                ) : (
                  <TextField
                    label="Purity (k)"
                    type="number"
                    min={1}
                    max={24}
                    value={purity}
                    onChange={(e) => setPurity(e.target.value)}
                    hint="Or leave it and state an assayed tunch below"
                  />
                )}
              </div>
              {/* The one case where the shop owes metal rather than holding
                  it. Shown only when nothing is going out, because on an
                  ordinary leg a "due date" would read as a delivery promise
                  from the worker, which is the opposite obligation. */}
              {goldG === 0 && (
                <div className="rounded-xl border border-brand-200 bg-brand-50 p-3">
                  <p className="text-xs font-medium text-brand-900">
                    He works on his own metal
                  </p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-brand-800">
                    Nothing leaves the safe and nothing posts now. When he hands the piece
                    over, the shop owes him its fine content plus his ratti — so this leg has
                    to settle in ratti and carry the date the metal is due back.
                  </p>
                  <div className="mt-2">
                    <TextField
                      label="Metal due back by"
                      type="date"
                      required
                      value={dueDate}
                      onChange={(e) => setDueDate(e.target.value)}
                      hint="A promise nobody wrote down is one nobody chases"
                    />
                  </div>
                </div>
              )}
              {metal === "gold" && (
                <TextField
                  label="Assayed tunch (%)"
                  type="number"
                  step="0.001"
                  min={0.001}
                  max={100}
                  value={tunch}
                  onChange={(e) => setTunch(e.target.value)}
                  placeholder="optional"
                  hint="Wins over the karat when the metal was actually tested — 91.6 is not 22k rounded, and on a kilo the difference is twenty fine grams."
                />
              )}
            </Section>

            <Section
              step={3}
              title="Terms"
              hint="Fixed onto the leg now and settled against on return — not looked up again."
            >
              <SelectField
                label="Wastage settled as"
                value={wastageBasis}
                onChange={(e) => setWastageBasis(e.target.value as WastageBasis)}
                options={WASTAGE_BASES.map((b) => ({ value: b.value, label: b.label }))}
                hint={WASTAGE_BASES.find((b) => b.value === wastageBasis)?.hint}
              />
              {onRatti && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <TextField
                    label="Ratti allowed (of 96)"
                    type="number"
                    step="0.001"
                    min={0}
                    max={95.999}
                    required
                    value={ratti}
                    onChange={(e) => setRatti(e.target.value)}
                    placeholder="6"
                    error={
                      Number(ratti || 0) >= 96
                        ? "At or above 96 the whole returned weight would be allowed"
                        : null
                    }
                  />
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
                    Worked out on the weight he <em>returns</em>, not what goes out, and added to
                    his credit before it is converted to pure. 6 ratti on 107.560 g of 21k allows
                    6.7225 g.
                  </div>
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <SelectField
                  label="Labour basis"
                  value={basis}
                  onChange={(e) => setBasis(e.target.value)}
                  options={LABOUR_BASES}
                  hint={dept?.default_rate_per_piece ? `${dept.name} standard` : undefined}
                />
                <TextField
                  label={basis === "flat" ? "Labour amount" : "Labour rate"}
                  type="number"
                  step="0.01"
                  min={0}
                  value={rate}
                  onChange={(e) => setRate(e.target.value)}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                  label="Pieces"
                  type="number"
                  min={0}
                  required={perPieces || basis === "per_piece"}
                  value={pieces}
                  onChange={(e) => setPieces(e.target.value)}
                  hint={
                    perPieces
                      ? "Stones to be set — the allowance is worked out from this"
                      : dept?.consumes_stones
                      ? "Stones to be set on this leg"
                      : "Items handled on this leg"
                  }
                />
                {wastageBasis === "per_100_pieces" && (
                  <TextField
                    label={`Waste per ${piecesBase || 100} pcs (g)`}
                    type="number"
                    step="0.0001"
                    min={0}
                    value={per100}
                    onChange={(e) => setPer100(e.target.value)}
                    hint={`${dept?.name} standard`}
                  />
                )}
              </div>
              {perPieces && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <TextField
                    label="…per how many pieces"
                    type="number"
                    min={1}
                    value={piecesBase}
                    onChange={(e) => setPiecesBase(e.target.value)}
                    hint="A hundred is the usual way to say it, not the only one — per 50, per 250, per 1000 are all real deals."
                  />
                  <div className="num self-end rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
                    {g3(Number(per100 || 0))}g / {piecesBase || 100} × {pieceN} pcs ={" "}
                    <span className="font-medium text-slate-900">{wt(allowanceG)}</span>
                  </div>
                </div>
              )}
              {perPieces && pieceN <= 0 && (
                <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
                  {dept?.name} allows wastage per {piecesBase || 100} pieces. Without a piece
                  count the allowance is zero and the worker carries the whole loss, so the
                  count is required.
                </p>
              )}
            </Section>

            <Section
              step={4}
              title="Stones"
              hint={
                dept?.consumes_stones
                  ? "This department sets stones — add the lines going out with the piece."
                  : "Only if stones go out with the piece."
              }
            >
              {lines.length === 0 ? (
                <button
                  type="button"
                  className="btn-outline w-full"
                  disabled={stones.length === 0}
                  onClick={() =>
                    setLines([
                      {
                        key: nextStoneKey++,
                        stone_id: String(stones[0]?.id ?? ""),
                        qty: "0",
                        ct: "",
                        rate: stones[0]?.default_rate_per_ct ?? "0",
                      },
                    ])
                  }
                >
                  {stones.length === 0 ? "No stones on record" : "+ Add a stone line"}
                </button>
              ) : (
                <>
                  <div className="space-y-3">
                    {lines.map((l) => (
                      <div key={l.key} className="rounded-xl border border-slate-200 p-3">
                        <div className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))]">
                          <SelectField
                            label="Stone"
                            value={l.stone_id}
                            onChange={(e) =>
                              setLines((ls) =>
                                ls.map((x) =>
                                  x.key === l.key
                                    ? {
                                        ...x,
                                        stone_id: e.target.value,
                                        rate:
                                          stones.find((s) => String(s.id) === e.target.value)
                                            ?.default_rate_per_ct ?? x.rate,
                                      }
                                    : x,
                                ),
                              )
                            }
                            options={stones.map((s) => ({ value: s.id, label: s.name }))}
                          />
                          <TextField
                            label="Qty"
                            type="number"
                            min={0}
                            value={l.qty}
                            onChange={(e) =>
                              setLines((ls) =>
                                ls.map((x) => (x.key === l.key ? { ...x, qty: e.target.value } : x)),
                              )
                            }
                          />
                          <TextField
                            label="Carats"
                            type="number"
                            step="0.0001"
                            min={0.0001}
                            value={l.ct}
                            onChange={(e) =>
                              setLines((ls) =>
                                ls.map((x) => (x.key === l.key ? { ...x, ct: e.target.value } : x)),
                              )
                            }
                          />
                          <TextField
                            label="Rate / ct"
                            type="number"
                            step="0.01"
                            min={0}
                            value={l.rate}
                            onChange={(e) =>
                              setLines((ls) =>
                                ls.map((x) =>
                                  x.key === l.key ? { ...x, rate: e.target.value } : x,
                                ),
                              )
                            }
                          />
                        </div>
                        <button
                          type="button"
                          className="mt-2 text-xs text-red-600 hover:underline"
                          onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
                        >
                          Remove line
                        </button>
                      </div>
                    ))}
                  </div>
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="min-w-[12rem] flex-1">
                      <SelectField
                        label="Stones from"
                        required
                        value={stoneSrc}
                        onChange={(e) => setStoneSrc(e.target.value)}
                        options={stoneSources.map((s) => ({
                          value: s.id,
                          label: `${s.label} — ${wt(s.weight_ct, "ct")}`,
                        }))}
                      />
                    </div>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() =>
                        setLines((ls) => [
                          ...ls,
                          {
                            key: nextStoneKey++,
                            stone_id: String(stones[0]?.id ?? ""),
                            qty: "0",
                            ct: "",
                            rate: stones[0]?.default_rate_per_ct ?? "0",
                          },
                        ])
                      }
                    >
                      + Add line
                    </button>
                  </div>
                </>
              )}
              <TextArea
                label="Notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </Section>
          </div>

          <div className="lg:sticky lg:top-0">{summary}</div>
        </div>
      )}
    </Sheet>
  );
}

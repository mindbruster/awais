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
import { WastageBasis, g3, round4, wt } from "@/pages/designs/parts";

interface Department {
  id: number;
  name: string;
  consumes_stones: boolean;
  default_wastage_basis: WastageBasis;
  default_wastage_per_100_pcs_g: string | null;
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
  const [basis, setBasis] = useState("per_gram");
  const [rate, setRate] = useState("0");
  const [pieces, setPieces] = useState("");
  const [per100, setPer100] = useState("");
  // The maker's deal, and it is a per-job switch rather than a department
  // setting: the same man works one piece on a ratti wastage and the next on a
  // flat per-gram with none at all.
  const [rattiOn, setRattiOn] = useState(false);
  const [ratti, setRatti] = useState("");
  // The piece is being made on the worker's own gold, which the shop will owe
  // back. Nothing leaves the safe, so there is no stock to draw on.
  const [onCredit, setOnCredit] = useState(false);
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
    ])
      .then(([d, w, ig, is, s]) => {
        setDepartments(d.data);
        setWorkers(w.data);
        setGoldSources(ig.data);
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
  const perPieces = dept?.default_wastage_basis === "per_100_pieces";

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
    if (dept.default_rate_per_piece !== null && dept.default_rate_per_piece !== undefined) {
      setBasis("per_piece");
      setRate(dept.default_rate_per_piece);
    } else {
      setBasis("per_gram");
      setRate("0");
    }
  }, [dept]);

  const goldSource = goldSources.find((g) => String(g.id) === goldSrc);
  const goldG = Number(gold || 0);
  const pieceN = Number(pieces || 0);
  const validLines = lines.filter((l) => l.stone_id && Number(l.ct) > 0);
  const stoneCt = round4(validLines.reduce((s, l) => s + Number(l.ct || 0), 0));

  const allowancePct = Number(worker?.effective_wastage_pct ?? 0);
  // A ratti allowance is measured against the weight that comes *back*, so at
  // issue time there is no figure to show — and showing a zero would read as
  // "he is allowed nothing", which is the opposite of what was agreed.
  const allowanceG = rattiOn
    ? 0
    : perPieces
    ? round4((Number(per100 || 0) * pieceN) / 100)
    : round4((goldG * allowancePct) / 100);
  const allowanceWorking = rattiOn
    ? `${ratti || 0} ratti of 96 on what comes back`
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
  if (goldG > 0 && !goldSrc) problems.push("Pick which stock the gold comes out of.");
  if (goldG <= 0 && !onCredit) problems.push("Enter the gold going out.");
  // Credit needs somebody to owe: the shop cannot owe gold back to its own bench.
  if (onCredit && !workerId)
    problems.push(
      "A piece made on credit needs the worker whose metal it is — mark the leg in-house or pick him.",
    );
  if (rattiOn && !ratti)
    problems.push(
      "Enter the ratti agreed — with none the worker is allowed nothing and charged for the whole difference.",
    );
  if (goldSource && goldG > Number(goldSource.weight_g))
    problems.push(
      `${goldSource.label} holds ${wt(goldSource.weight_g)} — less than the ${wt(goldG)} being issued.`,
    );
  if (perPieces && !rattiOn && pieceN <= 0)
    problems.push(
      `${dept?.name} allows wastage per 100 pieces, so this leg needs a piece count — without one the allowance is zero and the worker carries the whole loss.`,
    );
  if (perPieces && !rattiOn && !per100)
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
        gold_issued_g: gold || "0",
        gold_issued_purity: purity ? parseInt(purity, 10) : null,
        // Null on a leg the worker supplies the metal for: nothing comes off a
        // shelf, so there is no shelf to name.
        gold_source_inventory_id: goldSrc ? Number(goldSrc) : null,
        metal_on_credit: onCredit,
        metal_due_date: onCredit && dueDate ? dueDate : null,
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
        wastage_basis: rattiOn
          ? "ratti_of_received"
          : dept?.default_wastage_basis ?? "percent_of_issued",
        wastage_per_100_pcs_g: perPieces && !rattiOn ? per100 || "0" : null,
        wastage_ratti: rattiOn ? ratti || "0" : null,
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
          label="Gold out"
          value={goldG > 0 ? wt(goldG) : "—"}
          working={
            goldSource
              ? `${goldSource.label}${purity ? ` · ${purity}k` : ""}`
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
          value={wt(allowanceG)}
          working={allowanceWorking}
          tone={allowanceG > 0 ? undefined : "muted"}
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
        <p className="eyebrow text-brand-700">About to issue</p>
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
              {busy ? "Issuing…" : `Issue ${wt(goldG)} to ${worker?.name ?? "the bench"}`}
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

            <Section
              step={2}
              title="What goes out"
              hint={
                onCredit
                  ? "Nothing leaves the safe — the metal is his and the shop owes it back."
                  : "Deducted from stock when you commit."
              }
            >
              {/* A maker will make a piece on his own gold. Nothing comes off a
                  shelf, so the source and the weight both fall away — what
                  arrives on return is credited to him instead. */}
              <label className="flex items-start gap-2 rounded-xl border border-slate-200 px-3 py-2.5">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={onCredit}
                  onChange={(e) => setOnCredit(e.target.checked)}
                />
                <span className="text-xs leading-relaxed text-slate-700">
                  <span className="font-medium text-slate-900">Made on his own gold</span>
                  <span className="block text-slate-500">
                    The shop issues nothing and owes {holder} the metal back when the piece
                    arrives.
                  </span>
                </span>
              </label>
              {onCredit && (
                <TextField
                  label="Metal due back"
                  type="date"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                  hint="A promise nobody wrote down is one nobody chases"
                />
              )}
              <SelectField
                label="Gold from"
                required={!onCredit}
                value={goldSrc}
                onChange={(e) => setGoldSrc(e.target.value)}
                options={[
                  ...(onCredit ? [{ value: "", label: "None — his own metal" }] : []),
                  ...goldSources.map((g) => ({
                    value: g.id,
                    label: `${g.label} — ${wt(g.weight_g)}${g.purity ? `, ${g.purity}k` : ""}`,
                  })),
                ]}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                  label="Gold (g)"
                  type="number"
                  step="0.0001"
                  required={!onCredit}
                  min={onCredit ? 0 : 0.0001}
                  value={gold}
                  onChange={(e) => setGold(e.target.value)}
                  hint={goldSource ? `${wt(goldSource.weight_g)} on hand` : undefined}
                  error={
                    goldSource && goldG > Number(goldSource.weight_g)
                      ? `Only ${wt(goldSource.weight_g)} is in ${goldSource.label}`
                      : null
                  }
                />
                <TextField
                  label="Purity (k)"
                  type="number"
                  min={1}
                  max={24}
                  value={purity}
                  onChange={(e) => setPurity(e.target.value)}
                />
              </div>
            </Section>

            <Section
              step={3}
              title="Terms"
              hint="Fixed onto the leg now and settled against on return — not looked up again."
            >
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
                  required={(perPieces && !rattiOn) || basis === "per_piece"}
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
                {perPieces && !rattiOn && (
                  <TextField
                    label="Waste per 100 pcs (g)"
                    type="number"
                    step="0.0001"
                    min={0}
                    value={per100}
                    onChange={(e) => setPer100(e.target.value)}
                    hint={`${dept?.name} standard`}
                  />
                )}
              </div>

              {/* The maker's convention, and the one deal that cannot be worked
                  out at issue: it is a share of the weight he hands back, which
                  nobody knows until he does. */}
              <label className="flex items-start gap-2 rounded-xl border border-slate-200 px-3 py-2.5">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={rattiOn}
                  onChange={(e) => setRattiOn(e.target.checked)}
                />
                <span className="text-xs leading-relaxed text-slate-700">
                  <span className="font-medium text-slate-900">Wastage agreed in ratti</span>
                  <span className="block text-slate-500">
                    Worked out on the weight that comes back, not on what goes out.
                  </span>
                </span>
              </label>
              {rattiOn && (
                <TextField
                  label="Ratti (of 96)"
                  type="number"
                  step="0.001"
                  min={0}
                  max={96}
                  required
                  value={ratti}
                  onChange={(e) => setRatti(e.target.value)}
                  hint="6 ratti on 107.560g back allows 6.723g — added to what he's credited with"
                />
              )}
              {perPieces && !rattiOn && pieceN <= 0 && (
                <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
                  {dept?.name} allows wastage per 100 pieces. Without a piece count the allowance
                  is zero and the worker carries the whole loss, so the count is required.
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

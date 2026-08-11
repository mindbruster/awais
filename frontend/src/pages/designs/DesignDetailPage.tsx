import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";
import { statusPill } from "@/pages/designs/DesignsPage";

interface LegStone {
  id: number;
  stone_id: number;
  stone_name: string | null;
  quantity_issued: number;
  weight_issued_ct: string;
  quantity_returned: number;
  weight_returned_ct: string;
  rate_per_ct: string;
}

interface Leg {
  id: number;
  sequence: number;
  department_id: number;
  department_name: string | null;
  worker_id: number | null;
  worker_name: string | null;
  status: "issued" | "received" | "cancelled";
  issued_at: string | null;
  gold_issued_g: string;
  gold_issued_purity: number | null;
  stones_issued_ct: string;
  received_at: string | null;
  gold_received_g: string;
  stones_used_ct: string;
  stones_returned_ct: string;
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

interface DesignDetail {
  id: number;
  design_no: string;
  tag_no: string | null;
  item_name: string | null;
  customer_name: string | null;
  current_department_name: string | null;
  status: string;
  notes: string | null;
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

interface Department {
  id: number;
  name: string;
  consumes_stones: boolean;
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

const LABOUR_BASES = [
  { value: "per_gram", label: "Per gram received" },
  { value: "per_piece", label: "Per piece" },
  { value: "flat", label: "Flat amount" },
];

// The backend quantises every weight to four places before it settles wastage;
// a preview that rounds differently would show the operator one number and
// commit another.
const round4 = (n: number) => Math.round(n * 1e4) / 1e4;

function wt(v: string | number | null | undefined, unit: "g" | "ct" = "g"): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 4 })} ${unit}`;
}

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function settle(issued: number, received: number, allowedPct: number) {
  const allowed = round4((issued * allowedPct) / 100);
  const actual = round4(issued - received);
  return { allowed, actual, excess: Math.max(round4(actual - allowed), 0) };
}

export function DesignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const designId = Number(id);
  const [design, setDesign] = useState<DesignDetail | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="space-y-6">
      <Header design={design} trace={trace} reload={load} />
      <Totals totals={trace.totals} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Route legs={design.legs} daysHeld={daysHeld} />
        <div className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          {closed ? (
            <div className="card text-sm text-slate-500">
              {design.design_no} is {design.status.replace("_", " ")}. No further work can be
              issued.
            </div>
          ) : openLeg ? (
            <ReceivePanel leg={openLeg} designNo={design.design_no} reload={load} />
          ) : (
            <IssuePanel designId={design.id} reload={load} />
          )}
        </div>
      </div>
    </div>
  );
}

function Header({
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
    <div className="card">
      <Link to="/designs" className="text-sm text-slate-500 hover:underline">
        ← Designs
      </Link>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-mono text-3xl font-semibold text-slate-900">{design.design_no}</h1>
          <p className="mt-1 text-sm text-slate-600">
            {design.item_name ?? "—"} · {design.customer_name ?? "Stock"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-3 py-1 text-sm ${statusPill(design.status)}`}>
            {design.status.replace("_", " ")}
          </span>
          {design.current_department_name ? (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-sm text-amber-800">
              Out at {design.current_department_name}
            </span>
          ) : (
            <span className="rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-600">
              In house
            </span>
          )}
        </div>
      </div>
      <dl className="mt-5 grid gap-4 border-t border-slate-100 pt-4 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Tag</dt>
          <dd className="mt-1 font-mono">
            {design.tag_no ?? (
              <button
                className="rounded-md bg-slate-100 px-2 py-1 font-sans text-xs text-slate-700 hover:bg-slate-200 disabled:opacity-60"
                onClick={generateTag}
                disabled={busy}
              >
                {busy ? "Generating…" : "Generate tag"}
              </button>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Started</dt>
          <dd className="mt-1">{when(trace.started_at)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Completed</dt>
          <dd className="mt-1">{when(trace.completed_at)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-slate-500">Days in production</dt>
          <dd className="mt-1">{trace.days_in_production ?? "—"}</dd>
        </div>
      </dl>
      {design.notes && (
        <p className="mt-4 whitespace-pre-line border-t border-slate-100 pt-3 text-xs text-slate-500">
          {design.notes}
        </p>
      )}
    </div>
  );
}

function Totals({ totals }: { totals: Trace["totals"] }) {
  const excess = Number(totals.wastage_excess_g);
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <Tile label="Gold issued" value={wt(totals.gold_issued_g)} sub={`${totals.hops} legs`} />
      <Tile
        label="Gold received"
        value={wt(totals.gold_received_g)}
        sub={totals.open_hops ? `${totals.open_hops} still out` : "all legs closed"}
      />
      <Tile
        label="Wastage"
        value={wt(totals.wastage_actual_g)}
        sub={`${wt(totals.wastage_allowed_g)} allowed`}
      />
      <Tile
        label="Owed by workers"
        value={wt(totals.wastage_excess_g)}
        sub="beyond allowance"
        tone={excess > 0 ? "bad" : "good"}
      />
      <Tile label="Labour" value={fmtMoney(totals.labour_amount)} sub="accrued on closed legs" />
    </div>
  );
}

function Tile({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="card p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p
        className={`mt-1 text-xl font-semibold ${
          tone === "bad" ? "text-red-600" : tone === "good" ? "text-emerald-700" : "text-slate-900"
        }`}
      >
        {value}
      </p>
      <p className="mt-0.5 text-xs text-slate-500">{sub}</p>
    </div>
  );
}

function Route({ legs, daysHeld }: { legs: Leg[]; daysHeld: Map<number, number | null> }) {
  if (legs.length === 0) {
    return (
      <div className="card text-sm text-slate-500">
        Nothing has been issued yet. The route builds itself as the piece moves.
      </div>
    );
  }
  return (
    <ol className="space-y-3">
      {legs.map((leg, i) => (
        <li key={leg.id} className="relative pl-10">
          {i < legs.length - 1 && (
            <span className="absolute left-[15px] top-8 h-full w-px bg-slate-200" aria-hidden />
          )}
          <span
            className={`absolute left-0 top-1 flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold ${
              leg.status === "issued"
                ? "bg-amber-100 text-amber-800 ring-4 ring-amber-50"
                : leg.status === "received"
                ? "bg-emerald-100 text-emerald-800"
                : "bg-slate-200 text-slate-500"
            }`}
          >
            {leg.sequence}
          </span>
          <LegCard leg={leg} daysHeld={daysHeld.get(leg.id) ?? null} />
        </li>
      ))}
    </ol>
  );
}

function LegCard({ leg, daysHeld }: { leg: Leg; daysHeld: number | null }) {
  const cancelled = leg.status === "cancelled";
  const open = leg.status === "issued";
  return (
    <div className={`card ${cancelled ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-slate-900">
            {leg.department_name ?? "—"}
            <span className="ml-2 text-sm font-normal text-slate-600">
              {leg.worker_name ?? "unassigned"}
            </span>
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Issued {when(leg.issued_at)}
            {leg.received_at ? ` · received ${when(leg.received_at)}` : ""}
            {daysHeld !== null ? ` · ${daysHeld} day${daysHeld === 1 ? "" : "s"} held` : ""}
          </p>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            open
              ? "bg-amber-100 text-amber-800"
              : cancelled
              ? "bg-slate-200 text-slate-600"
              : "bg-emerald-100 text-emerald-800"
          }`}
        >
          {open ? "out with worker" : leg.status}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
        <Figure
          label="Gold issued"
          value={wt(leg.gold_issued_g)}
          sub={leg.gold_issued_purity ? `${leg.gold_issued_purity}k` : undefined}
        />
        <Figure label="Gold received" value={open ? "pending" : wt(leg.gold_received_g)} />
        <Figure
          label="Labour"
          value={fmtMoney(open ? null : leg.labour_amount)}
          sub={`${leg.labour_basis.replace("_", " ")} @ ${Number(leg.labour_rate)}`}
        />
        <Figure
          label="Stones"
          value={Number(leg.stones_issued_ct) ? wt(leg.stones_used_ct, "ct") : "—"}
          sub={
            Number(leg.stones_issued_ct)
              ? `${wt(leg.stones_issued_ct, "ct")} issued, ${wt(
                  leg.stones_returned_ct,
                  "ct",
                )} back`
              : undefined
          }
        />
      </div>

      {!open && !cancelled && (
        <Settlement
          className="mt-4"
          allowed={Number(leg.wastage_allowed_g)}
          actual={Number(leg.wastage_actual_g)}
          excess={Number(leg.wastage_excess_g)}
          allowedPct={leg.wastage_allowed_pct}
          worker={leg.worker_name}
        />
      )}
      {open && (
        <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {wt(leg.gold_issued_g)} is with {leg.worker_name ?? "this worker"}. Wastage is settled
          when the piece comes back — {Number(leg.wastage_allowed_pct ?? 0)}% is allowed on this
          leg.
        </p>
      )}

      {leg.stones.length > 0 && (
        <table className="mt-4 w-full border-t border-slate-100 pt-2 text-xs">
          <thead className="text-left uppercase text-slate-400">
            <tr>
              <th className="py-1">Stone</th>
              <th className="py-1 text-right">Issued</th>
              <th className="py-1 text-right">Returned</th>
              <th className="py-1 text-right">Used</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {leg.stones.map((s) => (
              <tr key={s.id}>
                <td className="py-1">{s.stone_name ?? `#${s.stone_id}`}</td>
                <td className="py-1 text-right font-mono">
                  {s.quantity_issued} · {wt(s.weight_issued_ct, "ct")}
                </td>
                <td className="py-1 text-right font-mono">
                  {s.quantity_returned} · {wt(s.weight_returned_ct, "ct")}
                </td>
                <td className="py-1 text-right font-mono">
                  {wt(round4(Number(s.weight_issued_ct) - Number(s.weight_returned_ct)), "ct")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {leg.notes && (
        <p className="mt-3 whitespace-pre-line border-t border-slate-100 pt-3 text-xs text-slate-500">
          {leg.notes}
        </p>
      )}
    </div>
  );
}

function Figure({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 font-mono text-slate-900">{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

/**
 * Allowed vs actual vs excess, drawn the same way whether it is a settled leg
 * or a live preview — the operator should recognise the number he approved.
 */
function Settlement({
  allowed,
  actual,
  excess,
  allowedPct,
  worker,
  className = "",
}: {
  allowed: number;
  actual: number;
  excess: number;
  allowedPct: string | number | null;
  worker: string | null;
  className?: string;
}) {
  const gain = actual < 0;
  const span = Math.max(allowed, actual, 0.0001);
  const pct = (v: number) => `${Math.min(100, Math.max(0, (v / span) * 100))}%`;
  const within = Math.min(Math.max(actual, 0), allowed);

  return (
    <div className={`rounded-lg border border-slate-200 p-3 ${className}`}>
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Allowed</p>
          <p className="mt-0.5 font-mono">{wt(allowed)}</p>
          <p className="text-xs text-slate-500">{Number(allowedPct ?? 0)}% of issued</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">
            {gain ? "Gain" : "Actual"}
          </p>
          <p className={`mt-0.5 font-mono ${gain ? "text-sky-700" : ""}`}>
            {wt(gain ? -actual : actual)}
          </p>
          <p className="text-xs text-slate-500">{gain ? "came back heavier" : "issued − received"}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Excess</p>
          <p className={`mt-0.5 font-mono ${excess > 0 ? "text-red-600" : "text-emerald-700"}`}>
            {wt(excess)}
          </p>
          <p className="text-xs text-slate-500">{excess > 0 ? "worker's liability" : "within allowance"}</p>
        </div>
      </div>

      {gain ? (
        <p className="mt-3 rounded-md bg-sky-50 px-3 py-2 text-xs text-sky-900">
          The piece came back {wt(-actual)} heavier than it went out — solder, alloy and findings do
          that. Nothing is owed.
        </p>
      ) : (
        <>
          <div className="relative mt-3 h-2 rounded-full bg-slate-100">
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
            <p className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-800">
              {wt(excess)} beyond the {Number(allowedPct ?? 0)}% agreed with{" "}
              {worker ?? "this worker"} — charged back to him, not to the shop.
            </p>
          )}
        </>
      )}
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
  const [returns, setReturns] = useState<Record<number, { qty: string; ct: string }>>({});
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [askCancel, setAskCancel] = useState(false);
  const [cancelGold, setCancelGold] = useState("");
  const [cancelStones, setCancelStones] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  const issued = Number(leg.gold_issued_g);
  const allowedPct = Number(leg.wastage_allowed_pct ?? 0);
  // Typed weight, not the committed one: this is what makes the settlement
  // visible before the operator signs off on it.
  const preview = settle(issued, Number(received || 0), allowedPct);
  const labour =
    leg.labour_basis === "per_gram"
      ? Number(leg.labour_rate) * Number(received || 0)
      : Number(leg.labour_rate);

  const setReturn = (id: number, patch: Partial<{ qty: string; ct: string }>) =>
    setReturns((r) => ({ ...r, [id]: { ...(r[id] ?? { qty: "", ct: "" }), ...patch } }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/designs/legs/${leg.id}/receive`, {
        gold_received_g: received || "0",
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
    <div className="card">
      <h3 className="text-sm font-semibold text-slate-700">
        Receive from {leg.worker_name ?? "worker"}
      </h3>
      <p className="mt-1 text-xs text-slate-500">
        Leg #{leg.sequence} at {leg.department_name} · {wt(leg.gold_issued_g)} out
      </p>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <TextField
          label="Gold received (g)"
          type="number"
          step="0.0001"
          min={0}
          required
          value={received}
          onChange={(e) => setReceived(e.target.value)}
          hint="Heavier than issued is fine — solder and findings add weight"
        />

        {received === "" ? (
          <p className="rounded-lg border border-dashed border-slate-300 px-3 py-4 text-center text-xs text-slate-500">
            Weigh the piece and enter it above — the wastage settlement appears here before you
            commit it. {allowedPct}% of {wt(leg.gold_issued_g)} is allowed.
          </p>
        ) : (
          <>
            <Settlement
              allowed={preview.allowed}
              actual={preview.actual}
              excess={preview.excess}
              allowedPct={allowedPct}
              worker={leg.worker_name}
            />
            <p className="text-xs text-slate-500">
              Labour on this leg: <span className="font-mono">{fmtMoney(labour)}</span>
            </p>
          </>
        )}

        {leg.stones.length > 0 && (
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Stones returned
            </p>
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

      <div className="mt-4 border-t border-slate-100 pt-3">
        <button className="text-xs text-red-600 hover:underline" onClick={() => setAskCancel(true)}>
          Cancel this leg
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

interface StoneLine {
  key: number;
  stone_id: string;
  qty: string;
  ct: string;
  rate: string;
}

let nextStoneKey = 1;

function IssuePanel({ designId, reload }: { designId: number; reload: () => void }) {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [goldSources, setGoldSources] = useState<InvItem[]>([]);
  const [stoneSources, setStoneSources] = useState<InvItem[]>([]);
  const [stones, setStones] = useState<Stone[]>([]);

  const [deptId, setDeptId] = useState("");
  const [workerId, setWorkerId] = useState("");
  const [goldSrc, setGoldSrc] = useState("");
  const [gold, setGold] = useState("");
  const [purity, setPurity] = useState("22");
  const [basis, setBasis] = useState("per_gram");
  const [rate, setRate] = useState("0");
  const [lines, setLines] = useState<StoneLine[]>([]);
  const [stoneSrc, setStoneSrc] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
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
      })
      .catch((e) => toast("error", apiError(e, "Could not load workshop data")));
  }, []);

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

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/designs/${designId}/legs`, {
        department_id: Number(deptId),
        worker_id: Number(workerId),
        gold_issued_g: gold || "0",
        gold_issued_purity: purity ? parseInt(purity, 10) : null,
        gold_source_inventory_id: Number(goldSrc),
        stones: lines
          .filter((l) => l.stone_id && Number(l.ct) > 0)
          .map((l) => ({
            stone_id: Number(l.stone_id),
            quantity_issued: Number(l.qty || 0),
            weight_issued_ct: l.ct,
            rate_per_ct: l.rate || "0",
          })),
        stone_source_inventory_id: lines.length ? Number(stoneSrc) : null,
        labour_basis: basis,
        labour_rate: rate || "0",
        notes: notes || null,
      });
      toast("success", `Issued to ${worker?.name ?? "worker"}`);
      setGold("");
      setNotes("");
      setLines([]);
      reload();
    } catch (err) {
      toast("error", apiError(err, "Could not issue"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card space-y-3">
      <h3 className="text-sm font-semibold text-slate-700">Issue to department</h3>
      <SelectField
        label="Department"
        required
        value={deptId}
        onChange={(e) => setDeptId(e.target.value)}
        options={departments.map((d) => ({ value: d.id, label: d.name }))}
      />
      <SelectField
        label="Worker"
        required
        value={workerId}
        onChange={(e) => setWorkerId(e.target.value)}
        options={eligible.map((w) => ({ value: w.id, label: w.name }))}
        hint={
          eligible.length === 0
            ? `No active worker belongs to ${dept?.name ?? "this department"}.`
            : `Wastage allowance frozen onto this leg: ${Number(
                worker?.effective_wastage_pct ?? 0,
              )}%`
        }
      />
      <SelectField
        label="Gold from"
        required
        value={goldSrc}
        onChange={(e) => setGoldSrc(e.target.value)}
        options={goldSources.map((g) => ({
          value: g.id,
          label: `${g.label} (${wt(g.weight_g)}${g.purity ? `, ${g.purity}k` : ""})`,
        }))}
      />
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Gold (g)"
          type="number"
          step="0.0001"
          required
          min={0.0001}
          value={gold}
          onChange={(e) => setGold(e.target.value)}
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
      <div className="grid grid-cols-2 gap-3">
        <SelectField
          label="Labour basis"
          value={basis}
          onChange={(e) => setBasis(e.target.value)}
          options={LABOUR_BASES}
        />
        <TextField
          label="Labour rate"
          type="number"
          step="0.01"
          min={0}
          value={rate}
          onChange={(e) => setRate(e.target.value)}
        />
      </div>

      <div className="border-t border-slate-100 pt-3">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Stones</p>
          <button
            type="button"
            className="text-xs text-brand-700 hover:underline"
            onClick={() =>
              setLines((l) => [
                ...l,
                {
                  key: nextStoneKey++,
                  stone_id: String(stones[0]?.id ?? ""),
                  qty: "0",
                  ct: "",
                  rate: stones[0]?.default_rate_per_ct ?? "0",
                },
              ])
            }
            disabled={stones.length === 0}
          >
            Add stone
          </button>
        </div>
        {lines.length === 0 ? (
          <p className="mt-1 text-xs text-slate-400">
            {dept?.consumes_stones
              ? "This department sets stones — add the lines going out with the piece."
              : "None."}
          </p>
        ) : (
          <div className="mt-2 space-y-3">
            {lines.map((l) => (
              <div key={l.key} className="rounded-lg border border-slate-200 p-2">
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
                <div className="mt-2 grid grid-cols-3 gap-2">
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
                        ls.map((x) => (x.key === l.key ? { ...x, rate: e.target.value } : x)),
                      )
                    }
                  />
                </div>
                <button
                  type="button"
                  className="mt-2 text-xs text-red-600 hover:underline"
                  onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
                >
                  Remove
                </button>
              </div>
            ))}
            <SelectField
              label="Stones from"
              required
              value={stoneSrc}
              onChange={(e) => setStoneSrc(e.target.value)}
              options={stoneSources.map((s) => ({
                value: s.id,
                label: `${s.label} (${wt(s.weight_ct, "ct")})`,
              }))}
            />
          </div>
        )}
      </div>

      <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button
        className="btn-primary w-full"
        disabled={busy || !workerId || !goldSrc || !gold || (lines.length > 0 && !stoneSrc)}
      >
        {busy ? "Issuing…" : "Issue (deducts stock)"}
      </button>
    </form>
  );
}

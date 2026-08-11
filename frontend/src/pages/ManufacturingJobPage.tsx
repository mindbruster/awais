import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";

interface Job {
  id: number;
  job_no: string;
  stage: string;
  karigar_id: number | null;
  gold_assigned_g: string;
  gold_assigned_purity: number | null;
  jewelry_received_g: string;
  karigar_loss_g: string;
  stone_fixer_id: number | null;
  stones_assigned_ct: string;
  stones_used_ct: string;
  stones_returned_ct: string;
  polish_vendor_id: number | null;
  weight_before_polish_g: string;
  weight_after_polish_g: string;
  polish_loss_g: string;
  karigar_cost: string;
  stone_fixing_cost: string;
  polish_cost: string;
  other_cost: string;
  product_id: number | null;
  notes: string | null;
}

interface Vendor {
  id: number;
  name: string;
  type: string;
}

interface InvItem {
  id: number;
  type: string;
  label: string;
  weight_g: string;
  weight_ct: string;
  purity: number | null;
}

const STAGES = [
  "draft",
  "karigar_assigned",
  "karigar_received",
  "stone_fixer_assigned",
  "stone_fixer_received",
  "polish_assigned",
  "polish_received",
  "completed",
];

export function ManufacturingJobPage() {
  const { id } = useParams<{ id: string }>();
  const jobId = Number(id);
  const [job, setJob] = useState<Job | null>(null);
  const [karigars, setKarigars] = useState<Vendor[]>([]);
  const [fixers, setFixers] = useState<Vendor[]>([]);
  const [polishers, setPolishers] = useState<Vendor[]>([]);
  const [rawGold, setRawGold] = useState<InvItem[]>([]);
  const [rawStones, setRawStones] = useState<InvItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [j, k, f, p, ig, is] = await Promise.all([
        api.get<Job>(`/manufacturing/${jobId}`),
        api.get<Vendor[]>("/vendors", { params: { type: "karigar" } }),
        api.get<Vendor[]>("/vendors", { params: { type: "stone_fixer" } }),
        api.get<Vendor[]>("/vendors", { params: { type: "polish" } }),
        api.get<InvItem[]>("/inventory", { params: { type: "raw_gold" } }),
        api.get<InvItem[]>("/inventory", { params: { type: "raw_stone" } }),
      ]);
      setJob(j.data);
      setKarigars(k.data);
      setFixers(f.data);
      setPolishers(p.data);
      setRawGold(ig.data);
      setRawStones(is.data);
    } catch (e) {
      setError(apiError(e, "Failed to load job"));
    }
  }, [jobId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!job) return <div className="text-sm text-slate-500">Loading…</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/manufacturing" className="text-sm text-slate-500 hover:underline">
            ← Manufacturing
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">{job.job_no}</h1>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-sm">{job.stage}</span>
      </div>

      <StageBar stage={job.stage} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Summary job={job} />
        <Costs job={job} reload={load} />
      </div>

      <ActionPanel
        job={job}
        karigars={karigars}
        fixers={fixers}
        polishers={polishers}
        rawGold={rawGold}
        rawStones={rawStones}
        reload={load}
      />
    </div>
  );
}

function StageBar({ stage }: { stage: string }) {
  const idx = STAGES.indexOf(stage);
  return (
    <ol className="flex items-center gap-2">
      {STAGES.map((s, i) => (
        <li key={s} className="flex flex-1 items-center gap-2">
          <div
            className={`h-2 flex-1 rounded-full ${
              stage === "cancelled"
                ? "bg-red-200"
                : i <= idx
                ? "bg-brand-500"
                : "bg-slate-200"
            }`}
            title={s}
          />
        </li>
      ))}
    </ol>
  );
}

function Summary({ job }: { job: Job }) {
  return (
    <div className="card">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">Summary</h3>
      <dl className="grid grid-cols-2 gap-y-2 text-sm">
        <Stat label="Karigar" value={job.karigar_id ? `#${job.karigar_id}` : "—"} />
        <Stat label="Gold assigned" value={`${job.gold_assigned_g} g (${job.gold_assigned_purity ?? "—"}k)`} />
        <Stat label="Received" value={`${job.jewelry_received_g} g`} />
        <Stat label="Karigar loss" value={`${job.karigar_loss_g} g`} kind="loss" />
        <Stat label="Stone fixer" value={job.stone_fixer_id ? `#${job.stone_fixer_id}` : "—"} />
        <Stat label="Stones used" value={`${job.stones_used_ct} ct`} />
        <Stat label="Polish vendor" value={job.polish_vendor_id ? `#${job.polish_vendor_id}` : "—"} />
        <Stat label="Polish loss" value={`${job.polish_loss_g} g`} kind="loss" />
        <Stat label="Product" value={job.product_id ? `#${job.product_id}` : "—"} />
      </dl>
      {job.notes && (
        <p className="mt-3 whitespace-pre-line border-t border-slate-100 pt-3 text-xs text-slate-500">
          {job.notes}
        </p>
      )}
    </div>
  );
}

function Stat({ label, value, kind }: { label: string; value: string; kind?: "loss" }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className={kind === "loss" ? "text-right text-red-600" : "text-right"}>{value}</dd>
    </>
  );
}

function Costs({ job, reload }: { job: Job; reload: () => void }) {
  const [karigar, setKarigar] = useState(job.karigar_cost);
  const [fixing, setFixing] = useState(job.stone_fixing_cost);
  const [polish, setPolish] = useState(job.polish_cost);
  const [other, setOther] = useState(job.other_cost);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setKarigar(job.karigar_cost);
    setFixing(job.stone_fixing_cost);
    setPolish(job.polish_cost);
    setOther(job.other_cost);
  }, [job]);

  const finalised = job.stage === "completed" || job.stage === "cancelled";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.post(`/manufacturing/${job.id}/costs`, {
        karigar_cost: karigar || "0",
        stone_fixing_cost: fixing || "0",
        polish_cost: polish || "0",
        other_cost: other || "0",
      });
      toast("success", "Costs updated");
      reload();
    } catch (err) {
      toast("error", apiError(err, "Could not save costs"));
    } finally {
      setSubmitting(false);
    }
  };

  const total =
    Number(karigar || 0) + Number(fixing || 0) + Number(polish || 0) + Number(other || 0);

  return (
    <form onSubmit={submit} className="card">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">Costs</h3>
        <span className="text-sm text-slate-500">
          Total: <span className="font-semibold text-slate-900">{total.toFixed(2)}</span>
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Karigar"
          type="number"
          step="0.01"
          min={0}
          value={karigar}
          onChange={(e) => setKarigar(e.target.value)}
          disabled={finalised}
        />
        <TextField
          label="Stone fixing"
          type="number"
          step="0.01"
          min={0}
          value={fixing}
          onChange={(e) => setFixing(e.target.value)}
          disabled={finalised}
        />
        <TextField
          label="Polish"
          type="number"
          step="0.01"
          min={0}
          value={polish}
          onChange={(e) => setPolish(e.target.value)}
          disabled={finalised}
        />
        <TextField
          label="Other"
          type="number"
          step="0.01"
          min={0}
          value={other}
          onChange={(e) => setOther(e.target.value)}
          disabled={finalised}
        />
      </div>
      <button
        type="submit"
        className="btn-primary mt-4 w-full"
        disabled={finalised || submitting}
      >
        {finalised ? "Locked (job finalised)" : submitting ? "Saving…" : "Save costs"}
      </button>
    </form>
  );
}

function ActionPanel(props: {
  job: Job;
  karigars: Vendor[];
  fixers: Vendor[];
  polishers: Vendor[];
  rawGold: InvItem[];
  rawStones: InvItem[];
  reload: () => void;
}) {
  const { job, karigars, fixers, polishers, rawGold, rawStones, reload } = props;
  const [askCancel, setAskCancel] = useState(false);
  const [cancelGold, setCancelGold] = useState("");
  const [cancelStones, setCancelStones] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  const post = async (path: string, body: unknown, msg: string) => {
    try {
      await api.post(`/manufacturing/${job.id}/${path}`, body);
      toast("success", msg);
      reload();
    } catch (err) {
      toast("error", apiError(err, "Action failed"));
    }
  };

  const [completing, setCompleting] = useState<{ name: string; category: string; location: string } | null>(null);

  const confirmComplete = async (password: string) => {
    if (!completing) return;
    try {
      await api.post(
        `/manufacturing/${job.id}/complete`,
        {
          product_name: completing.name,
          category: completing.category || null,
          finished_inventory_location: completing.location || null,
        },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", "Job completed");
      setCompleting(null);
      reload();
    } catch (err) {
      toast("error", apiError(err, "Complete failed"));
    }
  };

  const completeOnSubmit = async (body: any) => {
    setCompleting({
      name: body.product_name,
      category: body.category ?? "",
      location: body.finished_inventory_location ?? "",
    });
  };

  // Material issued against a job is only credited back when it completes, so
  // cancelling has to say what came back. Anything not recovered is written off
  // and stays outstanding against the worker.
  const goldOutstanding = Number(job.gold_assigned_g ?? 0);
  const stonesOutstanding =
    Number(job.stones_assigned_ct ?? 0) - Number(job.stones_returned_ct ?? 0);
  const writeOffGold = Math.max(0, goldOutstanding - Number(cancelGold || 0));
  const cancelValid =
    cancelReason.trim().length > 0 &&
    Number(cancelGold || 0) <= goldOutstanding &&
    Number(cancelStones || 0) <= stonesOutstanding;

  const confirmCancel = async (password: string) => {
    try {
      await api.post(
        `/manufacturing/${job.id}/cancel`,
        {
          gold_recovered_g: cancelGold || "0",
          stones_recovered_ct: cancelStones || "0",
          reason: cancelReason.trim(),
        },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", "Job cancelled");
      setAskCancel(false);
      setCancelGold("");
      setCancelStones("");
      setCancelReason("");
      reload();
    } catch (err) {
      toast("error", apiError(err, "Cancel failed"));
    }
  };

  if (job.stage === "completed" || job.stage === "cancelled") {
    return (
      <div className="card text-sm text-slate-500">
        Job is {job.stage}. No further actions available.
      </div>
    );
  }

  return (
    <div className="card">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">Next action</h3>
      {job.stage === "draft" && (
        <AssignKarigarForm
          karigars={karigars}
          rawGold={rawGold}
          onSubmit={(body) => post("assign-karigar", body, "Karigar assigned")}
        />
      )}
      {job.stage === "karigar_assigned" && (
        <ReceiveKarigarForm
          assigned={job.gold_assigned_g}
          onSubmit={(body) => post("receive-karigar", body, "Received from karigar")}
        />
      )}
      {job.stage === "karigar_received" && (
        <NextStepChoice
          choices={[
            {
              label: "Assign stone fixer",
              form: (
                <AssignStoneFixerForm
                  fixers={fixers}
                  rawStones={rawStones}
                  onSubmit={(body) => post("assign-stone-fixer", body, "Stones assigned")}
                />
              ),
            },
            {
              label: "Skip stones — assign polish",
              form: (
                <AssignPolishForm
                  polishers={polishers}
                  defaultBefore={job.jewelry_received_g}
                  onSubmit={(body) => post("assign-polish", body, "Polish assigned")}
                />
              ),
            },
            {
              label: "Skip both — complete job",
              form: <CompleteJobForm onSubmit={completeOnSubmit} />,
            },
          ]}
        />
      )}
      {job.stage === "stone_fixer_assigned" && (
        <ReceiveStoneFixerForm
          assigned={job.stones_assigned_ct}
          onSubmit={(body) => post("receive-stone-fixer", body, "Received from stone fixer")}
        />
      )}
      {job.stage === "stone_fixer_received" && (
        <NextStepChoice
          choices={[
            {
              label: "Assign polish",
              form: (
                <AssignPolishForm
                  polishers={polishers}
                  defaultBefore={job.jewelry_received_g}
                  onSubmit={(body) => post("assign-polish", body, "Polish assigned")}
                />
              ),
            },
            {
              label: "Skip polish — complete",
              form: <CompleteJobForm onSubmit={completeOnSubmit} />,
            },
          ]}
        />
      )}
      {job.stage === "polish_assigned" && (
        <ReceivePolishForm
          before={job.weight_before_polish_g}
          onSubmit={(body) => post("receive-polish", body, "Received from polish")}
        />
      )}
      {job.stage === "polish_received" && (
        <CompleteJobForm onSubmit={completeOnSubmit} />
      )}

      <div className="mt-6 border-t border-slate-100 pt-3">
        <button
          className="text-xs text-red-600 hover:underline"
          onClick={() => setAskCancel(true)}
        >
          Cancel job
        </button>
      </div>

      <PasswordConfirm
        open={askCancel}
        onClose={() => setAskCancel(false)}
        title={`Cancel job ${job.job_no}?`}
        description={
          `This is irreversible. ${goldOutstanding} g of gold` +
          (stonesOutstanding > 0 ? ` and ${stonesOutstanding} ct of stones` : "") +
          " went out on this job. Enter what you are getting back — anything you don't stays outstanding against the worker."
        }
        confirmLabel="Cancel job"
        extraValid={cancelValid}
        extra={
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <TextField
                label={`Gold recovered (g) — max ${goldOutstanding}`}
                type="number"
                step="0.0001"
                min="0"
                max={goldOutstanding}
                value={cancelGold}
                onChange={(e) => setCancelGold(e.target.value)}
              />
              <TextField
                label={`Stones recovered (ct) — max ${stonesOutstanding}`}
                type="number"
                step="0.0001"
                min="0"
                max={stonesOutstanding}
                disabled={stonesOutstanding <= 0}
                value={cancelStones}
                onChange={(e) => setCancelStones(e.target.value)}
              />
            </div>
            <TextField
              label="Reason"
              required
              placeholder="e.g. karigar returned partial, kept 3g"
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
            />
            {writeOffGold > 0 && (
              <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {writeOffGold.toFixed(4)} g will be written off and remain outstanding
                against this worker.
              </p>
            )}
          </div>
        }
        onConfirm={confirmCancel}
      />
      <PasswordConfirm
        open={!!completing}
        onClose={() => setCompleting(null)}
        title={`Complete job ${job.job_no}?`}
        description={`Creating "${completing?.name}" as a finished product and adding 1 unit to inventory. Confirm with your password.`}
        confirmLabel="Complete job"
        destructive={false}
        onConfirm={confirmComplete}
      />
    </div>
  );
}

function NextStepChoice({
  choices,
}: {
  choices: { label: string; form: React.ReactNode }[];
}) {
  const [idx, setIdx] = useState(0);
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        {choices.map((c, i) => (
          <button
            key={c.label}
            onClick={() => setIdx(i)}
            className={`rounded-full px-3 py-1 text-xs ${
              i === idx ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-700"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
      {choices[idx].form}
    </div>
  );
}

function AssignKarigarForm({
  karigars,
  rawGold,
  onSubmit,
}: {
  karigars: Vendor[];
  rawGold: InvItem[];
  onSubmit: (body: any) => Promise<void>;
}) {
  const [karigarId, setKarigarId] = useState(karigars[0]?.id ?? 0);
  const [gold, setGold] = useState("0");
  const [purity, setPurity] = useState("22");
  const [src, setSrc] = useState(rawGold[0]?.id ?? 0);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await onSubmit({
          karigar_id: Number(karigarId),
          gold_assigned_g: gold || "0",
          gold_assigned_purity: purity ? parseInt(purity, 10) : null,
          gold_source_inventory_id: Number(src),
          notes: notes || null,
        });
        setBusy(false);
      }}
    >
      <SelectField
        label="Karigar"
        required
        value={String(karigarId)}
        onChange={(e) => setKarigarId(Number(e.target.value))}
        options={karigars.map((k) => ({ value: k.id, label: k.name }))}
      />
      <SelectField
        label="Source raw gold"
        required
        value={String(src)}
        onChange={(e) => setSrc(Number(e.target.value))}
        options={rawGold.map((g) => ({
          value: g.id,
          label: `${g.label} (${g.weight_g} g${g.purity ? `, ${g.purity}k` : ""})`,
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
          label="Purity"
          type="number"
          min={1}
          max={24}
          value={purity}
          onChange={(e) => setPurity(e.target.value)}
        />
      </div>
      <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button className="btn-primary w-full" disabled={busy || !karigars.length || !rawGold.length}>
        {busy ? "Assigning…" : "Assign karigar (deducts stock)"}
      </button>
    </form>
  );
}

function ReceiveKarigarForm({
  assigned,
  onSubmit,
}: {
  assigned: string;
  onSubmit: (body: any) => Promise<void>;
}) {
  const [g, setG] = useState(assigned);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await onSubmit({ jewelry_received_g: g || "0", notes: notes || null });
        setBusy(false);
      }}
    >
      <TextField
        label={`Jewelry received (assigned: ${assigned} g)`}
        type="number"
        step="0.0001"
        required
        min={0.0001}
        value={g}
        onChange={(e) => setG(e.target.value)}
      />
      <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button className="btn-primary w-full" disabled={busy}>
        {busy ? "Saving…" : "Receive from karigar"}
      </button>
    </form>
  );
}

function AssignStoneFixerForm({
  fixers,
  rawStones,
  onSubmit,
}: {
  fixers: Vendor[];
  rawStones: InvItem[];
  onSubmit: (body: any) => Promise<void>;
}) {
  const [vid, setVid] = useState(fixers[0]?.id ?? 0);
  const [src, setSrc] = useState(rawStones[0]?.id ?? 0);
  const [ct, setCt] = useState("0");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await onSubmit({
          stone_fixer_id: Number(vid),
          stones_assigned_ct: ct || "0",
          stone_source_inventory_id: Number(src),
          notes: notes || null,
        });
        setBusy(false);
      }}
    >
      <SelectField
        label="Stone fixer"
        required
        value={String(vid)}
        onChange={(e) => setVid(Number(e.target.value))}
        options={fixers.map((v) => ({ value: v.id, label: v.name }))}
      />
      <SelectField
        label="Source raw stones"
        required
        value={String(src)}
        onChange={(e) => setSrc(Number(e.target.value))}
        options={rawStones.map((s) => ({
          value: s.id,
          label: `${s.label} (${s.weight_ct} ct)`,
        }))}
      />
      <TextField
        label="Stones (ct)"
        type="number"
        step="0.0001"
        required
        min={0.0001}
        value={ct}
        onChange={(e) => setCt(e.target.value)}
      />
      <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button className="btn-primary w-full" disabled={busy || !fixers.length || !rawStones.length}>
        {busy ? "Assigning…" : "Assign stone fixer (deducts stock)"}
      </button>
    </form>
  );
}

function ReceiveStoneFixerForm({
  assigned,
  onSubmit,
}: {
  assigned: string;
  onSubmit: (body: any) => Promise<void>;
}) {
  const [used, setUsed] = useState(assigned);
  const [returned, setReturned] = useState("0");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await onSubmit({
          stones_used_ct: used || "0",
          stones_returned_ct: returned || "0",
          notes: notes || null,
        });
        setBusy(false);
      }}
    >
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label={`Used (assigned: ${assigned} ct)`}
          type="number"
          step="0.0001"
          min={0}
          value={used}
          onChange={(e) => setUsed(e.target.value)}
        />
        <TextField
          label="Returned"
          type="number"
          step="0.0001"
          min={0}
          value={returned}
          onChange={(e) => setReturned(e.target.value)}
        />
      </div>
      <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button className="btn-primary w-full" disabled={busy}>
        {busy ? "Saving…" : "Receive from stone fixer"}
      </button>
    </form>
  );
}

function AssignPolishForm({
  polishers,
  defaultBefore,
  onSubmit,
}: {
  polishers: Vendor[];
  defaultBefore: string;
  onSubmit: (body: any) => Promise<void>;
}) {
  const [vid, setVid] = useState(polishers[0]?.id ?? 0);
  const [g, setG] = useState(defaultBefore);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await onSubmit({
          polish_vendor_id: Number(vid),
          weight_before_polish_g: g || "0",
          notes: notes || null,
        });
        setBusy(false);
      }}
    >
      <SelectField
        label="Polish vendor"
        required
        value={String(vid)}
        onChange={(e) => setVid(Number(e.target.value))}
        options={polishers.map((p) => ({ value: p.id, label: p.name }))}
      />
      <TextField
        label="Weight before polish (g)"
        type="number"
        step="0.0001"
        required
        min={0.0001}
        value={g}
        onChange={(e) => setG(e.target.value)}
      />
      <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button className="btn-primary w-full" disabled={busy || !polishers.length}>
        {busy ? "Assigning…" : "Send for polish"}
      </button>
    </form>
  );
}

function ReceivePolishForm({
  before,
  onSubmit,
}: {
  before: string;
  onSubmit: (body: any) => Promise<void>;
}) {
  const [g, setG] = useState(before);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await onSubmit({ weight_after_polish_g: g || "0", notes: notes || null });
        setBusy(false);
      }}
    >
      <TextField
        label={`Polished weight (sent: ${before} g)`}
        type="number"
        step="0.0001"
        required
        min={0.0001}
        value={g}
        onChange={(e) => setG(e.target.value)}
      />
      <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button className="btn-primary w-full" disabled={busy}>
        {busy ? "Saving…" : "Receive from polish"}
      </button>
    </form>
  );
}

function CompleteJobForm({ onSubmit }: { onSubmit: (body: any) => Promise<void> }) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        await onSubmit({
          product_name: name,
          category: category || null,
          finished_inventory_location: location || null,
        });
        setBusy(false);
      }}
    >
      <TextField
        label="Product name"
        required
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        />
        <TextField
          label="Location"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
        />
      </div>
      <button className="btn-primary w-full" disabled={busy || !name}>
        {busy ? "Completing…" : "Complete job (creates product + stock)"}
      </button>
    </form>
  );
}

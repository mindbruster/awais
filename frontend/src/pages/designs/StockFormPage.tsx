/**
 * The stock form: the screen where a finished design becomes a sellable piece.
 *
 * It exists to answer one question before anything is committed — what has this
 * piece cost? — so the roll-up is shown first and the form second. Every figure
 * comes off the preview endpoint, which derives it from the design's legs; the
 * arithmetic repeated here is only the live recomputation as the operator edits
 * the weights, and it is deliberately spelled out on screen so he can check it
 * rather than trust it.
 */
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface StoneUse {
  stone_id: number;
  stone_name: string | null;
  quantity_used: number;
  weight_used_ct: string;
  rate_per_ct: string;
  value: string;
}

interface Hop {
  leg_id: number;
  sequence: number;
  department: string;
  worker: string | null;
  status: "issued" | "received" | "cancelled";
  gold_in_g: string;
  gold_out_g: string;
  gold_purity: number | null;
  piece_count: number;
  wastage_allowed_g: string;
  wastage_actual_g: string;
  wastage_excess_g: string;
  labour_basis: string;
  labour_rate: string;
  labour_amount: string;
  stone_value: string;
  stones: StoneUse[];
}

interface Weights {
  gross_weight_g: string;
  stone_weight_ct: string;
  stone_weight_g: string;
  net_metal_g: string;
  gold_purity: number | null;
  pure_weight_g: string;
}

interface Preview {
  design_id: number;
  design_no: string;
  tag_no: string | null;
  item: string | null;
  customer: string | null;
  status: string;
  hops: Hop[];
  stones: StoneUse[];
  totals: {
    hops: number;
    pieces: number;
    gold_issued_g: string;
    gold_received_g: string;
    wastage_allowed_g: string;
    wastage_actual_g: string;
    wastage_excess_g: string;
    stone_weight_ct: string;
    stone_value: string;
    labour_total: string;
  };
  suggested_gold_weight_g: string;
  suggested_gold_purity: number | null;
  suggested_name: string;
  gold_rate_per_g: string;
  weights: Weights;
  gold_value: string;
  material_cost: string;
  piece_cost: string;
}

interface StockResult {
  product_id: number;
  serial_no: string;
  total_cost: string;
  material_cost: string;
  piece_cost: string;
  entry_no: string;
}

interface Line {
  key: number;
  stone_id: number;
  stone_name: string | null;
  quantity: string;
  ct: string;
  rate: string;
}

let nextKey = 1;

// A carat is a fifth of a gram — the constant the server converts by. Anything
// else here would show the operator a metal weight the commit disagrees with.
const CARAT_G = 0.2;

// The server quantises every weight to four places before it prices anything;
// previewing at a different precision would show one number and commit another.
const round4 = (n: number) => Math.round(n * 1e4) / 1e4;
const round2 = (n: number) => Math.round(n * 1e2) / 1e2;

function wt(v: string | number | null | undefined, unit: "g" | "ct" = "g"): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (Number.isNaN(n)) return String(v);
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 4 })} ${unit}`;
}

const PURITIES = [24, 22, 21, 18, 14, 9].map((k) => ({ value: k, label: `${k}k` }));

export function StockFormPage() {
  const { id } = useParams<{ id: string }>();
  const designId = Number(id);
  const navigate = useNavigate();

  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [gross, setGross] = useState("");
  const [metal, setMetal] = useState("");
  // Until the operator types a metal weight of his own, it follows the gross
  // less the stones — the same subtraction the server does. Once he has
  // overridden it (he may have weighed the casting before setting), his figure
  // stands and is only checked, never silently replaced.
  const [metalTouched, setMetalTouched] = useState(false);
  const [purity, setPurity] = useState("22");
  const [otherCharges, setOtherCharges] = useState("0");
  const [location, setLocation] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [asking, setAsking] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get<Preview>(`/stocking/designs/${designId}/preview`);
      const p = r.data;
      setPreview(p);
      setName(p.suggested_name);
      setCategory(p.item ?? "");
      setGross(p.suggested_gold_weight_g);
      setPurity(String(p.suggested_gold_purity ?? 22));
      setLines(
        p.stones.map((s) => ({
          key: nextKey++,
          stone_id: s.stone_id,
          stone_name: s.stone_name,
          quantity: String(Math.max(s.quantity_used, 1)),
          ct: s.weight_used_ct,
          rate: s.rate_per_ct,
        })),
      );
    } catch (e) {
      setError(apiError(e, "This design cannot be stocked"));
    }
  }, [designId]);

  useEffect(() => {
    load();
  }, [load]);

  const stoneCt = useMemo(
    () => round4(lines.reduce((sum, l) => sum + Number(l.ct || 0), 0)),
    [lines],
  );
  const stoneValue = useMemo(
    () => round2(lines.reduce((sum, l) => sum + Number(l.ct || 0) * Number(l.rate || 0), 0)),
    [lines],
  );
  const stoneG = round4(stoneCt * CARAT_G);
  const implied = round4(Number(gross || 0) - stoneG);

  // The suggestion follows the weights until the operator takes it over.
  useEffect(() => {
    if (!metalTouched) setMetal(implied > 0 ? String(implied) : "");
  }, [implied, metalTouched]);

  const net = metalTouched ? round4(Number(metal || 0)) : implied;
  const purityK = Number(purity || 0);
  const pure = round4((net * purityK) / 24);
  const rate = Number(preview?.gold_rate_per_g ?? 0);
  const goldValue = round2(pure * rate);
  const material = round2(goldValue + stoneValue);
  const labour = Number(preview?.totals.labour_total ?? 0);
  const making = round2(labour + Number(otherCharges || 0));
  const pieceCost = round2(making + material);

  const impossible = net > implied + 0.00005 || net <= 0;

  const submit = async (password: string) => {
    try {
      const r = await api.post<StockResult>(
        `/stocking/designs/${designId}/stock`,
        {
          name: name.trim(),
          category: category.trim() || null,
          description: description.trim() || null,
          gross_weight_g: gross || "0",
          gold_weight_g: String(net),
          gold_purity: purityK || null,
          other_charges: otherCharges || "0",
          finished_inventory_location: location.trim() || null,
          stones: lines
            .filter((l) => Number(l.ct) > 0)
            .map((l) => ({
              stone_id: l.stone_id,
              quantity: Math.max(Number(l.quantity || 1), 1),
              weight_ct: l.ct,
              rate_per_ct: l.rate || "0",
            })),
        },
        { headers: { "X-Confirm-Password": password } },
      );
      setAsking(false);
      toast("success", `${preview?.design_no} stocked as ${r.data.serial_no}`);
      navigate(`/products/${r.data.product_id}`);
    } catch (e) {
      toast("error", apiError(e, "Could not stock this piece"));
    }
  };

  if (error) {
    return (
      <div className="card space-y-3">
        <Link to={`/designs/${designId}`} className="text-sm text-slate-500 hover:underline">
          ← Back to the design
        </Link>
        <p className="text-red-600">{error}</p>
      </div>
    );
  }
  if (!preview) return <div className="text-sm text-slate-500">Loading…</div>;

  return (
    <div className="space-y-6">
      <div className="card">
        <Link to={`/designs/${designId}`} className="text-sm text-slate-500 hover:underline">
          ← {preview.design_no}
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold text-slate-900">Stock this piece</h1>
            <p className="mt-1 text-sm text-slate-600">
              <span className="font-mono">{preview.design_no}</span>
              {preview.tag_no ? ` · ${preview.tag_no}` : ""} · {preview.item ?? "—"} ·{" "}
              {preview.customer ?? "Stock"}
            </p>
          </div>
          <p className="text-xs text-slate-500">
            {preview.totals.hops} legs · {preview.totals.pieces} pcs handled · gold at{" "}
            <span className="font-mono">{fmtMoney(preview.gold_rate_per_g)}</span>/fine g
          </p>
        </div>
      </div>

      <CostBanner
        labour={labour}
        other={Number(otherCharges || 0)}
        material={material}
        goldValue={goldValue}
        stoneValue={stoneValue}
        total={pieceCost}
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-6">
          <Departments hops={preview.hops} totals={preview.totals} />
          {preview.stones.length > 0 && <StonesUsed stones={preview.stones} />}
        </div>

        <form
          className="card space-y-3 lg:sticky lg:top-6 lg:self-start"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            setAsking(true);
          }}
        >
          <h3 className="text-sm font-semibold text-slate-700">Stock form</h3>
          <TextField
            label="Product name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <TextField
            label="Category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="Gross weight (g)"
              type="number"
              step="0.0001"
              min={0.0001}
              required
              value={gross}
              onChange={(e) => setGross(e.target.value)}
              hint={`${wt(preview.suggested_gold_weight_g)} came back from the last department`}
            />
            <SelectField
              label="Purity"
              value={purity}
              onChange={(e) => setPurity(e.target.value)}
              options={PURITIES}
            />
          </div>
          <TextField
            label="Gold weight (g)"
            type="number"
            step="0.0001"
            min={0.0001}
            required
            value={metal}
            onChange={(e) => {
              setMetalTouched(true);
              setMetal(e.target.value);
            }}
            error={
              impossible
                ? `At most ${wt(implied)} of a ${wt(gross)} piece carrying ${wt(
                    stoneCt,
                    "ct",
                  )} of stones is metal.`
                : null
            }
            hint={metalTouched ? "Your figure — the stones are not deducted again." : undefined}
          />

          <Working gross={Number(gross || 0)} stoneCt={stoneCt} stoneG={stoneG} net={net} purity={purityK} pure={pure} />

          <StoneLines lines={lines} setLines={setLines} />

          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="Other charges"
              type="number"
              step="0.01"
              min={0}
              value={otherCharges}
              onChange={(e) => setOtherCharges(e.target.value)}
              hint="Packing, courier, anything not on a leg"
            />
            <TextField
              label="Shelf / location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Showcase A"
            />
          </div>
          <TextArea
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />

          <button
            className="btn-primary w-full"
            disabled={!name.trim() || !gross || !metal || impossible}
          >
            Stock the piece
          </button>
          <p className="text-xs text-slate-500">
            Mints a product, puts it on the shelf and moves{" "}
            <span className="font-mono">{wt(pure)}</span> fine into Finished Goods.
          </p>
        </form>
      </div>

      <PasswordConfirm
        open={asking}
        onClose={() => setAsking(false)}
        title={`Stock ${preview.design_no}?`}
        description={
          `${name || "This piece"} — ${wt(net)} of ${purityK}k metal` +
          (stoneCt > 0 ? ` and ${wt(stoneCt, "ct")} of stones` : "") +
          `, costed at ${fmtMoney(pieceCost)} (${fmtMoney(making)} making + ${fmtMoney(
            material,
          )} material). This posts to the books and cannot be undone without a reversal.`
        }
        confirmLabel="Stock the piece"
        destructive={false}
        onConfirm={submit}
      />
    </div>
  );
}

/**
 * The figure the screen exists for. Labour and material are kept visible either
 * side of it because they are the two levers the shop can actually pull.
 */
function CostBanner({
  labour,
  other,
  material,
  goldValue,
  stoneValue,
  total,
}: {
  labour: number;
  other: number;
  material: number;
  goldValue: number;
  stoneValue: number;
  total: number;
}) {
  return (
    <div className="card bg-slate-900 text-white">
      <div className="grid gap-6 sm:grid-cols-[repeat(2,minmax(0,1fr))_auto] sm:items-end">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-400">Labour</p>
          <p className="mt-1 font-mono text-2xl">{fmtMoney(labour + other)}</p>
          <p className="mt-0.5 text-xs text-slate-400">
            {fmtMoney(labour)} accrued on the legs
            {other > 0 ? ` + ${fmtMoney(other)} other charges` : ""}
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-400">Material</p>
          <p className="mt-1 font-mono text-2xl">{fmtMoney(material)}</p>
          <p className="mt-0.5 text-xs text-slate-400">
            {fmtMoney(goldValue)} gold
            {stoneValue > 0 ? ` + ${fmtMoney(stoneValue)} stones` : ""}
          </p>
        </div>
        <div className="border-t border-slate-700 pt-4 sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
          <p className="text-xs uppercase tracking-wide text-emerald-300">Total cost</p>
          <p className="mt-1 font-mono text-3xl font-semibold">{fmtMoney(total)}</p>
          <p className="mt-0.5 text-xs text-slate-400">what this piece has cost to make</p>
        </div>
      </div>
    </div>
  );
}

/** Where the cost came from: one row per department the piece passed through. */
function Departments({
  hops,
  totals,
}: {
  hops: Hop[];
  totals: Preview["totals"];
}) {
  return (
    <div className="card overflow-x-auto">
      <h3 className="text-sm font-semibold text-slate-700">Where it has been</h3>
      <table className="mt-3 w-full min-w-[46rem] text-sm">
        <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
          <tr>
            <th className="py-2">Department</th>
            <th className="py-2">Worker</th>
            <th className="py-2 text-right">Gold in</th>
            <th className="py-2 text-right">Gold out</th>
            <th className="py-2 text-right">Allowed</th>
            <th className="py-2 text-right">Actual</th>
            <th className="py-2 text-right">Excess</th>
            <th className="py-2 text-right">Labour</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {hops.map((h) => (
            <tr key={h.leg_id}>
              <td className="py-2">
                <span className="text-slate-400">{h.sequence}.</span> {h.department}
                {h.piece_count > 0 && (
                  <span className="ml-1 text-xs text-slate-500">({h.piece_count} pcs)</span>
                )}
              </td>
              <td className="py-2 text-slate-600">{h.worker ?? "—"}</td>
              <td className="py-2 text-right font-mono">{wt(h.gold_in_g)}</td>
              <td className="py-2 text-right font-mono">{wt(h.gold_out_g)}</td>
              <td className="py-2 text-right font-mono text-slate-500">
                {wt(h.wastage_allowed_g)}
              </td>
              <td
                className={`py-2 text-right font-mono ${
                  Number(h.wastage_actual_g) < 0 ? "text-sky-700" : ""
                }`}
              >
                {wt(h.wastage_actual_g)}
              </td>
              <td
                className={`py-2 text-right font-mono ${
                  Number(h.wastage_excess_g) > 0 ? "text-red-600" : "text-emerald-700"
                }`}
              >
                {wt(h.wastage_excess_g)}
              </td>
              <td className="py-2 text-right font-mono">{fmtMoney(h.labour_amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-slate-200 font-medium">
            <td className="py-2" colSpan={2}>
              {totals.hops} legs
            </td>
            <td className="py-2 text-right font-mono">{wt(totals.gold_issued_g)}</td>
            <td className="py-2 text-right font-mono">{wt(totals.gold_received_g)}</td>
            <td className="py-2 text-right font-mono">{wt(totals.wastage_allowed_g)}</td>
            <td className="py-2 text-right font-mono">{wt(totals.wastage_actual_g)}</td>
            <td className="py-2 text-right font-mono">{wt(totals.wastage_excess_g)}</td>
            <td className="py-2 text-right font-mono">{fmtMoney(totals.labour_total)}</td>
          </tr>
        </tfoot>
      </table>
      <p className="mt-3 text-xs text-slate-500">
        Gold in and out repeat down the column because the same piece is issued and received at
        every hop — the metal is not the sum, it is what the last department handed back.
      </p>
    </div>
  );
}

/** What the setter actually consumed, and what it was worth. */
function StonesUsed({ stones }: { stones: StoneUse[] }) {
  const total = stones.reduce((s, x) => s + Number(x.value), 0);
  return (
    <div className="card overflow-x-auto">
      <h3 className="text-sm font-semibold text-slate-700">Stones in the piece</h3>
      <table className="mt-3 w-full min-w-[28rem] text-sm">
        <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
          <tr>
            <th className="py-2">Stone</th>
            <th className="py-2 text-right">Used</th>
            <th className="py-2 text-right">Carats</th>
            <th className="py-2 text-right">Rate / ct</th>
            <th className="py-2 text-right">Value</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {stones.map((s, i) => (
            <tr key={`${s.stone_id}-${i}`}>
              <td className="py-2">{s.stone_name ?? `#${s.stone_id}`}</td>
              <td className="py-2 text-right font-mono">{s.quantity_used}</td>
              <td className="py-2 text-right font-mono">{wt(s.weight_used_ct, "ct")}</td>
              <td className="py-2 text-right font-mono">{fmtMoney(s.rate_per_ct)}</td>
              <td className="py-2 text-right font-mono">{fmtMoney(s.value)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-slate-200 font-medium">
            <td className="py-2" colSpan={4}>
              Issued less returned, across every leg
            </td>
            <td className="py-2 text-right font-mono">{fmtMoney(total)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/**
 * gross − stones = metal, metal × purity/24 = pure. Shown as a sum rather than
 * an answer: the operator is signing off on a weight that prices the piece.
 */
function Working({
  gross,
  stoneCt,
  stoneG,
  net,
  purity,
  pure,
}: {
  gross: number;
  stoneCt: number;
  stoneG: number;
  net: number;
  purity: number;
  pure: number;
}) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <p className="font-mono">
        {wt(gross)} gross − {wt(stoneG)} stones ({wt(stoneCt, "ct")}) = {wt(net)} metal
      </p>
      <p className="mt-1 font-mono">
        {wt(net)} × {purity}/24 = <span className="font-semibold text-slate-900">{wt(pure)}</span>{" "}
        pure
      </p>
      <p className="mt-1">Pure grams are what the ledger moves and what the gold is priced on.</p>
    </div>
  );
}

/**
 * The stone lines, pre-filled with what the design consumed. Editable because
 * the setter's carats and the finished piece's carats are not always the same
 * number, and the piece is what is being stocked.
 */
function StoneLines({
  lines,
  setLines,
}: {
  lines: Line[];
  setLines: (fn: (l: Line[]) => Line[]) => void;
}) {
  if (lines.length === 0) {
    return (
      <p className="border-t border-slate-100 pt-3 text-xs text-slate-400">
        No stones were consumed on this design.
      </p>
    );
  }
  const patch = (key: number, p: Partial<Line>) =>
    setLines((ls) => ls.map((x) => (x.key === key ? { ...x, ...p } : x)));

  return (
    <div className="space-y-2 border-t border-slate-100 pt-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Stones</p>
      {lines.map((l) => (
        <div key={l.key} className="rounded-lg border border-slate-200 p-2">
          <p className="text-sm text-slate-700">{l.stone_name ?? `#${l.stone_id}`}</p>
          <div className="mt-2 grid grid-cols-3 gap-2">
            <TextField
              label="Qty"
              type="number"
              min={1}
              value={l.quantity}
              onChange={(e) => patch(l.key, { quantity: e.target.value })}
            />
            <TextField
              label="Total ct"
              type="number"
              step="0.0001"
              min={0}
              value={l.ct}
              onChange={(e) => patch(l.key, { ct: e.target.value })}
            />
            <TextField
              label="Rate / ct"
              type="number"
              step="0.01"
              min={0}
              value={l.rate}
              onChange={(e) => patch(l.key, { rate: e.target.value })}
            />
          </div>
          <button
            type="button"
            className="mt-2 text-xs text-red-600 hover:underline"
            onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
          >
            Not in this piece
          </button>
        </div>
      ))}
    </div>
  );
}

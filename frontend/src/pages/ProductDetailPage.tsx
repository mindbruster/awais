import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { Modal } from "@/components/Modal";
import { SelectField, TextField } from "@/components/Field";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { Currency, fmtMoney } from "@/lib/money";

interface Stone {
  id: number;
  name: string;
  kind: string;
  cut: string | null;
  color: string | null;
  clarity: string | null;
  default_rate_per_ct: string | null;
  currency: Currency;
}

interface ProductStone {
  id: number;
  product_id: number;
  stone_id: number;
  quantity: number;
  weight_ct: string;
  rate_per_ct: string;
  notes: string | null;
  stone: Stone;
}

interface Product {
  id: number;
  serial_no: string;
  name: string;
  category: string | null;
  description: string | null;
  gold_weight_g: string;
  gold_purity: number | null;
  stone_weight_ct: string;
  total_cost: string;
  status: string;
  image_url: string | null;
  stones: ProductStone[];
}

export function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const pid = Number(id);
  const [product, setProduct] = useState<Product | null>(null);
  const [allStones, setAllStones] = useState<Stone[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<ProductStone | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([
        api.get<Product>(`/products/${pid}`),
        api.get<Stone[]>("/stones", { params: { limit: 500 } }),
      ]);
      setProduct(p.data);
      setAllStones(s.data);
    } catch (e) {
      setError(apiError(e, "Failed to load"));
    }
  }, [pid]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="card text-red-600">{error}</div>;
  if (!product) return <div className="text-sm text-slate-500">Loading…</div>;

  const stoneTotal = product.stones.reduce(
    (sum, ps) => sum + Number(ps.weight_ct) * Number(ps.rate_per_ct) * ps.quantity,
    0,
  );

  const removeStone = async () => {
    if (!removing) return;
    try {
      await api.delete(`/products/${pid}/stones/${removing.id}`);
      toast("success", "Stone removed");
      setRemoving(null);
      load();
    } catch (err) {
      toast("error", apiError(err, "Could not remove"));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <Link to="/products" className="text-sm text-slate-500 hover:underline">
          ← Products
        </Link>
        <div className="mt-1 flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-semibold text-slate-900">{product.name}</h1>
          <span className="font-mono text-xs text-slate-500">{product.serial_no}</span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">{product.status}</span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="card lg:col-span-1">
          {product.image_url ? (
            <img
              src={`http://localhost:8000${product.image_url}`}
              alt={product.name}
              className="aspect-square w-full rounded-lg object-cover"
            />
          ) : (
            <div className="flex aspect-square w-full items-center justify-center rounded-lg bg-slate-100 text-sm text-slate-400">
              No image
            </div>
          )}
        </section>

        <section className="card lg:col-span-2">
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Specifications</h3>
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <Row label="Category">{product.category ?? "—"}</Row>
            <Row label="Gold weight">{product.gold_weight_g} g</Row>
            <Row label="Gold purity">{product.gold_purity ? `${product.gold_purity}k` : "—"}</Row>
            <Row label="Stone weight (header)">{product.stone_weight_ct} ct</Row>
            <Row label="Making cost">{fmtMoney(product.total_cost, "PKR")}</Row>
          </dl>
          {product.description && (
            <p className="mt-3 whitespace-pre-line border-t border-slate-100 pt-3 text-sm text-slate-600">
              {product.description}
            </p>
          )}
        </section>
      </div>

      <section className="card overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-700">Stone breakdown</h3>
            <p className="text-xs text-slate-500">
              Stones mounted on this piece — pick from the Stones master.
            </p>
          </div>
          <button className="btn-primary" onClick={() => setAdding(true)} disabled={!allStones.length}>
            Add stone
          </button>
        </div>
        {product.stones.length === 0 ? (
          <div className="p-6 text-sm text-slate-500">
            No stones attached yet. {allStones.length === 0 && "Add some to the Stones master first."}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Stone</th>
                <th className="px-4 py-3">Specs</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-right">Weight (ct)</th>
                <th className="px-4 py-3 text-right">Rate / ct</th>
                <th className="px-4 py-3 text-right">Subtotal</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {product.stones.map((ps) => (
                <tr key={ps.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium">
                    {ps.stone.name}
                    <div className="text-xs text-slate-500">{ps.stone.kind}</div>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {[ps.stone.cut, ps.stone.color, ps.stone.clarity].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="px-4 py-3 text-right">{ps.quantity}</td>
                  <td className="px-4 py-3 text-right">{ps.weight_ct}</td>
                  <td className="px-4 py-3 text-right font-mono">
                    {fmtMoney(ps.rate_per_ct, ps.stone.currency)}
                  </td>
                  <td className="px-4 py-3 text-right font-semibold">
                    {fmtMoney(
                      Number(ps.weight_ct) * Number(ps.rate_per_ct) * ps.quantity,
                      ps.stone.currency,
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="text-xs text-red-600 hover:underline"
                      onClick={() => setRemoving(ps)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
              <tr className="bg-slate-50 font-medium">
                <td className="px-4 py-3" colSpan={5}>
                  Total stone value
                </td>
                <td className="px-4 py-3 text-right">{fmtMoney(stoneTotal, "PKR")}</td>
                <td></td>
              </tr>
            </tbody>
          </table>
        )}
      </section>

      <AddStoneModal
        open={adding}
        onClose={() => setAdding(false)}
        productId={pid}
        stones={allStones}
        onSaved={() => {
          setAdding(false);
          load();
        }}
      />
      <ConfirmDialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        title="Remove stone from product?"
        description="This unlinks the stone — it remains in the Stones master."
        destructive
        confirmLabel="Remove"
        onConfirm={removeStone}
      />
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right">{children}</dd>
    </>
  );
}

function AddStoneModal({
  open,
  onClose,
  productId,
  stones,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  productId: number;
  stones: Stone[];
  onSaved: () => void;
}) {
  const [stoneId, setStoneId] = useState<number>(0);
  const [qty, setQty] = useState("1");
  const [weight, setWeight] = useState("0");
  const [rate, setRate] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      const first = stones[0];
      setStoneId(first?.id ?? 0);
      setQty("1");
      setWeight("0");
      setRate(first?.default_rate_per_ct ?? "");
      setNotes("");
    }
  }, [open, stones]);

  const onPick = (id: number) => {
    setStoneId(id);
    const s = stones.find((x) => x.id === id);
    if (s?.default_rate_per_ct) setRate(s.default_rate_per_ct);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post(`/products/${productId}/stones`, {
        stone_id: stoneId,
        quantity: parseInt(qty || "1", 10),
        weight_ct: weight || "0",
        rate_per_ct: rate || null,
        notes: notes || null,
      });
      toast("success", "Stone attached");
      onSaved();
    } catch (err) {
      toast("error", apiError(err, "Could not attach"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Add stone to product">
      <form onSubmit={submit} className="space-y-4">
        <SelectField
          label="Stone"
          required
          value={String(stoneId)}
          onChange={(e) => onPick(Number(e.target.value))}
          options={stones.map((s) => ({
            value: s.id,
            label: `${s.name} · ${s.kind}${s.cut ? ` · ${s.cut}` : ""}`,
          }))}
        />
        <div className="grid grid-cols-3 gap-3">
          <TextField
            label="Quantity"
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
          <TextField
            label="Weight (ct)"
            type="number"
            step="0.0001"
            min={0}
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
          />
          <TextField
            label="Rate / ct"
            type="number"
            step="0.0001"
            min={0}
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            hint="Defaults from stone master"
          />
        </div>
        <TextField
          label="Notes (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy || !stoneId}>
            {busy ? "Attaching…" : "Attach stone"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

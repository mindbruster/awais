/**
 * Goods moving between shops.
 *
 * The screen is built around the one thing a paper transfer book cannot tell
 * you: what is on the road right now. A sent transfer is on neither branch's
 * shelf, so it gets its own tab and its own colour, and receiving it is a
 * single action from the list rather than something buried in a detail page.
 */
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { SelectField, TextArea, TextField } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { Sheet } from "@/components/Sheet";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtWeight } from "@/lib/money";

interface Branch {
  id: number;
  code: string;
  name: string;
  is_active: boolean;
  is_default: boolean;
}

interface TransferLine {
  id: number;
  product_id: number | null;
  product_serial: string | null;
  product_name: string | null;
  inventory_item_id: number | null;
  inventory_label: string | null;
  quantity: number;
  weight_g: string;
  weight_ct: string;
}

interface Transfer {
  id: number;
  transfer_no: string;
  from_branch_id: number;
  from_branch_name: string | null;
  to_branch_id: number;
  to_branch_name: string | null;
  status: "draft" | "sent" | "received" | "cancelled";
  sent_at: string | null;
  received_at: string | null;
  notes: string | null;
  lines: TransferLine[];
}

interface InvItem {
  id: number;
  label: string;
  weight_g: string;
  weight_ct: string;
  type: string;
}

interface Product {
  id: number;
  serial_no: string;
  name: string;
}

const TABS = [
  { value: "", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "sent", label: "On the road" },
  { value: "received", label: "Received" },
  { value: "cancelled", label: "Cancelled" },
];

function statusChip(s: Transfer["status"]) {
  if (s === "sent")
    return (
      <span className="chip-out">
        <span className="dot bg-amber-500" aria-hidden />
        On the road
      </span>
    );
  if (s === "received")
    return (
      <span className="chip-back">
        <span className="dot bg-emerald-500" aria-hidden />
        Received
      </span>
    );
  if (s === "cancelled") return <span className="chip-dead">Cancelled</span>;
  return <span className="chip-idle">Draft</span>;
}

function lineLabel(l: TransferLine): string {
  if (l.product_id) return `${l.product_serial ?? `#${l.product_id}`} — ${l.product_name ?? ""}`;
  const bits = [l.inventory_label ?? `Item #${l.inventory_item_id}`];
  if (Number(l.weight_g) > 0) bits.push(`${fmtWeight(l.weight_g)} g`);
  if (Number(l.weight_ct) > 0) bits.push(`${fmtWeight(l.weight_ct)} ct`);
  if (l.quantity > 0) bits.push(`${l.quantity} pcs`);
  return bits.join(" · ");
}

export function TransfersPage() {
  const [rows, setRows] = useState<Transfer[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState<Transfer | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (status) params.status = status;
    api
      .get<Transfer[]>("/transfers", { params })
      .then((r) => setRows(r.data))
      .catch((e) => setError(apiError(e, "Could not load transfers")))
      .finally(() => setLoading(false));
  }, [status]);

  useEffect(load, [load]);

  useEffect(() => {
    api
      .get<Branch[]>("/branches", { params: { is_active: true } })
      .then((r) => setBranches(r.data))
      .catch(() => setBranches([]));
  }, []);

  const act = async (t: Transfer, what: "send" | "receive") => {
    setBusyId(t.id);
    try {
      await api.post(`/transfers/${t.id}/${what}`, {});
      toast(
        "success",
        what === "send"
          ? `${t.transfer_no} sent to ${t.to_branch_name}`
          : `${t.transfer_no} received at ${t.to_branch_name}`,
      );
      load();
    } catch (e) {
      toast("error", apiError(e, `Could not ${what} the transfer`));
    } finally {
      setBusyId(null);
    }
  };

  const confirmCancel = async (password: string) => {
    if (!cancelling) return;
    try {
      await api.post(
        `/transfers/${cancelling.id}/cancel`,
        { reason: cancelReason.trim() },
        { headers: { "X-Confirm-Password": password } },
      );
      toast("success", `${cancelling.transfer_no} cancelled`);
      setCancelling(null);
      setCancelReason("");
      load();
    } catch (e) {
      toast("error", apiError(e, "Could not cancel"));
    }
  };

  const onRoad = rows.filter((r) => r.status === "sent").length;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Transfers</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Stock moving between your shops. A transfer leaves one branch when it's sent and only
            arrives when the other branch signs for it — until then it's on the road and on nobody's
            shelf.
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => setCreating(true)}
          disabled={branches.length < 2}
          title={branches.length < 2 ? "You need a second branch first" : undefined}
        >
          New transfer
        </button>
      </div>

      {branches.length < 2 && (
        <div className="card mt-4 text-sm text-slate-600">
          There's only one branch, so there's nowhere to transfer to. Add another under{" "}
          <span className="font-medium">Setup → Branches</span> first.
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-1 border-b border-slate-200">
        {TABS.map((t) => {
          const active = status === t.value;
          return (
            <button
              key={t.value || "all"}
              onClick={() => setStatus(t.value)}
              aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
                active
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"
              }`}
            >
              {t.label}
              {t.value === "sent" && onRoad > 0 && !status && (
                <span className="num ml-1.5 rounded-full bg-amber-100 px-1.5 text-xs text-amber-900">
                  {onRoad}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {loading && <div className="card mt-4 text-sm text-slate-500">Loading…</div>}
      {error && <div className="card mt-4 text-sm text-red-600">{error}</div>}

      {!loading && !error && rows.length === 0 && (
        <div className="card mt-4 py-12 text-center">
          <p className="text-sm font-medium text-slate-700">
            {status ? "Nothing here." : "No transfers yet."}
          </p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-slate-500">
            {status
              ? "Try another tab."
              : "When you move a piece or some metal from one shop to another, record it here so both branches' stock stays honest."}
          </p>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {rows.map((t) => (
          <div key={t.id} className="card-flush p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="num font-medium text-slate-900">{t.transfer_no}</span>
                  {statusChip(t.status)}
                </div>
                <p className="mt-1 text-sm text-slate-600">
                  {t.from_branch_name} <span className="text-slate-400">→</span>{" "}
                  {t.to_branch_name}
                </p>
                <ul className="mt-2 space-y-0.5">
                  {t.lines.map((l) => (
                    <li key={l.id} className="num text-xs text-slate-500">
                      {lineLabel(l)}
                    </li>
                  ))}
                  {t.lines.length === 0 && (
                    <li className="text-xs italic text-slate-400">No lines yet</li>
                  )}
                </ul>
              </div>

              <div className="flex flex-none flex-wrap gap-2">
                {t.status === "draft" && (
                  <button
                    className="btn-primary"
                    disabled={busyId === t.id || t.lines.length === 0}
                    onClick={() => act(t, "send")}
                  >
                    {busyId === t.id ? "Sending…" : "Send"}
                  </button>
                )}
                {t.status === "sent" && (
                  <button
                    className="btn-primary"
                    disabled={busyId === t.id}
                    onClick={() => act(t, "receive")}
                  >
                    {busyId === t.id ? "Receiving…" : `Receive at ${t.to_branch_name}`}
                  </button>
                )}
                {(t.status === "draft" || t.status === "sent") && (
                  <button className="btn-outline" onClick={() => setCancelling(t)}>
                    Cancel
                  </button>
                )}
              </div>
            </div>
            {t.notes && (
              <p className="mt-3 whitespace-pre-line border-t border-slate-100 pt-2 text-xs text-slate-500">
                {t.notes}
              </p>
            )}
          </div>
        ))}
      </div>

      <NewTransfer
        open={creating}
        branches={branches}
        onClose={() => setCreating(false)}
        onCreated={() => {
          setCreating(false);
          load();
        }}
      />

      <PasswordConfirm
        open={cancelling !== null}
        onClose={() => setCancelling(null)}
        title={`Cancel ${cancelling?.transfer_no ?? ""}?`}
        description={
          cancelling?.status === "sent"
            ? "This transfer has already left. Cancelling puts every line back on the sending branch's shelf, so the goods are never on nobody's books."
            : "This transfer hasn't been sent, so nothing moves. It is simply closed."
        }
        confirmLabel="Cancel transfer"
        extraValid={cancelReason.trim().length > 0}
        extra={
          <TextField
            label="Reason"
            required
            placeholder="e.g. sent to the wrong shop"
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
          />
        }
        onConfirm={confirmCancel}
      />
    </div>
  );
}

interface Line {
  key: number;
  kind: "product" | "stock";
  product_id: string;
  inventory_item_id: string;
  weight_g: string;
  weight_ct: string;
  quantity: string;
}

let nextKey = 1;

function NewTransfer({
  open,
  branches,
  onClose,
  onCreated,
}: {
  open: boolean;
  branches: Branch[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [stock, setStock] = useState<InvItem[]>([]);
  const [pieces, setPieces] = useState<Product[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || branches.length === 0) return;
    const def = branches.find((b) => b.is_default) ?? branches[0];
    setFrom((p) => p || String(def.id));
    setTo((p) => p || String(branches.find((b) => b.id !== def.id)?.id ?? ""));
    setLines([]);
    setNotes("");
  }, [open, branches]);

  // Only what the sending branch actually holds can go on the van. Refetched
  // whenever the source changes, so the pickers can never offer another shop's
  // stock — which the API would refuse anyway, after the operator had typed it.
  useEffect(() => {
    if (!open || !from) return;
    Promise.all([
      api.get<InvItem[]>("/inventory", { params: { branch_id: from, limit: 200 } }),
      api.get<Product[]>("/products", {
        params: { branch_id: from, status: "in_stock", limit: 200 },
      }),
    ])
      .then(([i, p]) => {
        setStock(i.data.filter((x) => x.type !== "finished_product"));
        setPieces(p.data);
      })
      .catch(() => {
        setStock([]);
        setPieces([]);
      });
  }, [open, from]);

  const valid = useMemo(
    () =>
      from &&
      to &&
      from !== to &&
      lines.length > 0 &&
      lines.every((l) =>
        l.kind === "product"
          ? Boolean(l.product_id)
          : Boolean(l.inventory_item_id) &&
            (Number(l.weight_g) > 0 || Number(l.weight_ct) > 0 || Number(l.quantity) > 0),
      ),
    [from, to, lines],
  );

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/transfers", {
        from_branch_id: Number(from),
        to_branch_id: Number(to),
        notes: notes || null,
        lines: lines.map((l) =>
          l.kind === "product"
            ? { product_id: Number(l.product_id) }
            : {
                inventory_item_id: Number(l.inventory_item_id),
                weight_g: l.weight_g || "0",
                weight_ct: l.weight_ct || "0",
                quantity: Number(l.quantity || 0),
              },
        ),
      });
      toast("success", "Transfer drafted — send it when the goods leave");
      onCreated();
    } catch (err) {
      toast("error", apiError(err, "Could not create the transfer"));
    } finally {
      setBusy(false);
    }
  };

  const addLine = (kind: Line["kind"]) =>
    setLines((ls) => [
      ...ls,
      {
        key: nextKey++,
        kind,
        product_id: String(pieces[0]?.id ?? ""),
        inventory_item_id: String(stock[0]?.id ?? ""),
        weight_g: "",
        weight_ct: "",
        quantity: "",
      },
    ]);

  const patch = (key: number, p: Partial<Line>) =>
    setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...p } : l)));

  const branchOpts = branches.map((b) => ({ value: b.id, label: `${b.name} (${b.code})` }));

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="New transfer"
      subtitle="Drafted first — nothing leaves until you send it"
      widthClass="max-w-2xl"
      footer={
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            {valid ? "Creates a draft. Send it when the goods actually leave." : "Pick two branches and add at least one line."}
          </p>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={!valid || busy}
              onClick={submit}
            >
              {busy ? "Creating…" : "Create draft"}
            </button>
          </div>
        </div>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="card grid gap-3 sm:grid-cols-2">
          <SelectField
            label="From"
            required
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              setLines([]);
            }}
            options={branchOpts}
            hint="Only this shop's stock can be sent"
          />
          <SelectField
            label="To"
            required
            value={to}
            onChange={(e) => setTo(e.target.value)}
            options={branchOpts}
            error={from && from === to ? "Pick a different branch" : null}
          />
        </div>

        <div className="card">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">What's going</h3>
            <div className="flex gap-2">
              <button
                type="button"
                className="text-xs text-brand-700 hover:underline disabled:text-slate-300"
                disabled={pieces.length === 0}
                onClick={() => addLine("product")}
              >
                + Finished piece
              </button>
              <button
                type="button"
                className="text-xs text-brand-700 hover:underline disabled:text-slate-300"
                disabled={stock.length === 0}
                onClick={() => addLine("stock")}
              >
                + Metal or stones
              </button>
            </div>
          </div>

          {lines.length === 0 ? (
            <p className="mt-3 rounded-xl border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-500">
              Nothing on the van yet. Add a finished piece, or a weight of metal or stones from{" "}
              {branches.find((b) => String(b.id) === from)?.name ?? "the sending branch"}.
            </p>
          ) : (
            <div className="mt-3 space-y-3">
              {lines.map((l) => (
                <div key={l.key} className="rounded-xl border border-slate-200 p-3">
                  {l.kind === "product" ? (
                    <SelectField
                      label="Piece"
                      value={l.product_id}
                      onChange={(e) => patch(l.key, { product_id: e.target.value })}
                      options={pieces.map((p) => ({
                        value: p.id,
                        label: `${p.serial_no} — ${p.name}`,
                      }))}
                      hint="Moves whole; it carries its own weight"
                    />
                  ) : (
                    <>
                      <SelectField
                        label="From stock"
                        value={l.inventory_item_id}
                        onChange={(e) => patch(l.key, { inventory_item_id: e.target.value })}
                        options={stock.map((s) => ({
                          value: s.id,
                          label: `${s.label} — ${fmtWeight(s.weight_g)} g / ${fmtWeight(
                            s.weight_ct,
                          )} ct`,
                        }))}
                      />
                      <div className="mt-2 grid grid-cols-3 gap-2">
                        <TextField
                          label="Grams"
                          type="number"
                          step="0.0001"
                          min={0}
                          value={l.weight_g}
                          onChange={(e) => patch(l.key, { weight_g: e.target.value })}
                        />
                        <TextField
                          label="Carats"
                          type="number"
                          step="0.0001"
                          min={0}
                          value={l.weight_ct}
                          onChange={(e) => patch(l.key, { weight_ct: e.target.value })}
                        />
                        <TextField
                          label="Pieces"
                          type="number"
                          min={0}
                          value={l.quantity}
                          onChange={(e) => patch(l.key, { quantity: e.target.value })}
                        />
                      </div>
                    </>
                  )}
                  <button
                    type="button"
                    className="mt-2 text-xs text-red-600 hover:underline"
                    onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </form>
    </Sheet>
  );
}

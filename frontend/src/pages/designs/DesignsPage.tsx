/**
 * The design register — every piece on the floor.
 *
 * Read as a worklist, not a table: the questions it exists to answer are "what
 * is still out", "who is holding it" and "what has been sitting too long", so
 * state is a row of tabs rather than a dropdown buried in a filter bar, and
 * every row carries how long the piece has been in production. The gallery view
 * is here because these are *designs* — a shop recognises a piece by looking at
 * it, and the image the model has always carried was never once shown.
 */
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { SelectField, TextArea } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { FilterSelect, SearchBox } from "@/components/Toolbar";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { staticUrl } from "@/lib/url";
import { DESIGN_STATUSES, DesignStatusChip, age } from "@/pages/designs/parts";

interface Design {
  id: number;
  design_no: string;
  tag_no: string | null;
  item_id: number;
  item_name: string | null;
  customer_id: number | null;
  customer_name: string | null;
  current_department_id: number | null;
  current_department_name: string | null;
  status: string;
  image_url: string | null;
  created_at: string;
}

interface Named {
  id: number;
  name: string;
}

const PAGE = 50;

export function DesignsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Design[]>([]);
  const [departments, setDepartments] = useState<Named[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [dept, setDept] = useState("");
  const [offset, setOffset] = useState(0);
  const [view, setView] = useState<"list" | "gallery">("list");

  const load = () => {
    setLoading(true);
    setError(null);
    const params: Record<string, string> = { limit: String(PAGE), offset: String(offset) };
    if (q) params.q = q;
    if (status) params.status = status;
    if (dept) params.current_department_id = dept;
    api
      .get<Design[]>("/designs", { params })
      .then((r) => setItems(r.data))
      .catch((e) => setError(apiError(e, "Failed to load designs")))
      .finally(() => setLoading(false));
  };

  useEffect(load, [q, status, dept, offset]);

  // A filter change is a new question, so it starts at the first page rather
  // than dropping the reader on page four of a different result set. Done in
  // the handlers, not an effect: resetting the offset afterwards would fire a
  // second request for the page the reader never saw.
  const filterBy = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setOffset(0);
  };

  useEffect(() => {
    api
      .get<Named[]>("/departments", { params: { is_active: true } })
      .then((r) => setDepartments(r.data))
      .catch(() => setDepartments([]));
  }, []);

  const filtered = Boolean(q || status || dept);
  // The list endpoint returns rows, not a count. A full page means there is
  // probably another one; claiming a total we were never told would be worse
  // than saying nothing.
  const hasMore = items.length === PAGE;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Designs</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Every piece on the floor, from the first department to the last. Open one to see where
            it is, who is holding it and what each stage cost.
          </p>
        </div>
        <button className="btn-primary" onClick={() => setOpen(true)}>
          New design
        </button>
      </div>

      {/* State is the first cut a shop makes, so it is a row of tabs rather
          than one option inside a filter dropdown. */}
      <div className="mt-5 flex flex-wrap items-center gap-1 border-b border-slate-200">
        {DESIGN_STATUSES.map((s) => {
          const active = status === s.value;
          return (
            <button
              key={s.value || "all"}
              onClick={() => filterBy(setStatus)(s.value)}
              aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
                active
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700"
              }`}
            >
              {s.label}
            </button>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <SearchBox
          value={q}
          onChange={filterBy(setQ)}
          placeholder="Search design or tag number…"
          className="w-full sm:w-72"
        />
        <FilterSelect
          value={dept}
          onChange={filterBy(setDept)}
          options={departments.map((d) => ({ value: String(d.id), label: d.name }))}
          allLabel="Anywhere"
        />
        <div className="ml-auto flex items-center gap-3">
          <span className="num text-xs text-slate-500">
            {offset + 1}–{offset + items.length}
          </span>
          <div className="flex rounded-lg border border-slate-300 bg-white p-0.5">
            {(["list", "gallery"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                aria-pressed={view === v}
                title={v === "list" ? "List view" : "Gallery view"}
                className={`rounded-md px-2 py-1 text-xs font-medium capitalize transition ${
                  view === v ? "bg-slate-100 text-slate-900" : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading && <div className="card mt-4 text-sm text-slate-500">Loading…</div>}
      {error && <div className="card mt-4 text-sm text-red-600">{error}</div>}

      {!loading && !error && items.length === 0 && (
        <div className="card mt-4 py-12 text-center">
          <p className="text-sm font-medium text-slate-700">
            {filtered ? "Nothing matches those filters." : "No designs yet."}
          </p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-slate-500">
            {filtered
              ? "Clear a filter, or search a different design number."
              : "Mint a design the moment work starts on a piece — everything it does afterwards is filed under that number."}
          </p>
          {!filtered && (
            <button className="btn-primary mt-4" onClick={() => setOpen(true)}>
              New design
            </button>
          )}
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <>
          {view === "gallery" ? (
            <Gallery items={items} />
          ) : (
            <>
              {/* Desktop: a scannable table. */}
              <div className="card-flush mt-4 hidden md:block">
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-left">
                    <tr className="eyebrow">
                      <th className="px-4 py-2.5 font-semibold">Design</th>
                      <th className="px-4 py-2.5 font-semibold">Item</th>
                      <th className="px-4 py-2.5 font-semibold">For</th>
                      <th className="px-4 py-2.5 font-semibold">Currently at</th>
                      <th className="px-4 py-2.5 text-right font-semibold">Age</th>
                      <th className="px-4 py-2.5 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {items.map((d) => (
                      <tr
                        key={d.id}
                        onClick={() => navigate(`/designs/${d.id}`)}
                        className="cursor-pointer transition hover:bg-brand-50/50"
                      >
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-3">
                            <Thumb url={d.image_url} label={d.design_no} size="sm" />
                            <div className="min-w-0">
                              <Link
                                to={`/designs/${d.id}`}
                                onClick={(e) => e.stopPropagation()}
                                className="num font-medium text-brand-700 hover:underline"
                              >
                                {d.design_no}
                              </Link>
                              <div className="num truncate text-xs text-slate-400">
                                {d.tag_no ?? "no tag"}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-slate-700">{d.item_name ?? "—"}</td>
                        <td className="px-4 py-2.5 text-slate-600">
                          {d.customer_name ?? <span className="text-slate-400">Stock</span>}
                        </td>
                        <td className="px-4 py-2.5">
                          {d.current_department_name ? (
                            <span className="chip-out">
                              <span className="dot bg-amber-500" aria-hidden />
                              {d.current_department_name}
                            </span>
                          ) : (
                            <span className="text-xs text-slate-400">In house</span>
                          )}
                        </td>
                        <td className="num px-4 py-2.5 text-right text-slate-600">
                          {age(d.created_at)}
                        </td>
                        <td className="px-4 py-2.5">
                          <DesignStatusChip status={d.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Below md a six-column table is unreadable, and this screen is
                  meant to be opened on the floor. Same rows, stacked. */}
              <div className="mt-4 space-y-2 md:hidden">
                {items.map((d) => (
                  <Link
                    key={d.id}
                    to={`/designs/${d.id}`}
                    className="card flex items-center gap-3 p-3 transition active:bg-slate-50"
                  >
                    <Thumb url={d.image_url} label={d.design_no} size="md" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="num font-medium text-slate-900">{d.design_no}</span>
                        <DesignStatusChip status={d.status} />
                      </div>
                      <p className="mt-0.5 truncate text-xs text-slate-500">
                        {d.item_name ?? "—"} · {d.customer_name ?? "Stock"}
                      </p>
                      <p className="mt-1 text-xs">
                        {d.current_department_name ? (
                          <span className="text-amber-700">
                            Out at {d.current_department_name}
                          </span>
                        ) : (
                          <span className="text-slate-400">In house</span>
                        )}
                        <span className="num text-slate-400"> · {age(d.created_at)}</span>
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            </>
          )}

          {(offset > 0 || hasMore) && (
            <div className="mt-4 flex items-center justify-between">
              <button
                className="btn-ghost"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE))}
              >
                ← Previous
              </button>
              <span className="num text-xs text-slate-500">
                {offset + 1}–{offset + items.length}
              </span>
              <button className="btn-ghost" disabled={!hasMore} onClick={() => setOffset((o) => o + PAGE)}>
                Next →
              </button>
            </div>
          )}
        </>
      )}

      <NewDesignForm
        open={open}
        onClose={() => {
          setOpen(false);
          load();
        }}
      />
    </div>
  );
}

/** The piece, when there is a picture of it — and its number when there isn't. */
function Thumb({
  url,
  label,
  size,
}: {
  url: string | null;
  label: string;
  size: "sm" | "md" | "lg";
}) {
  const box =
    size === "sm" ? "h-9 w-9 text-[9px]" : size === "md" ? "h-12 w-12 text-[10px]" : "h-full w-full";
  if (url) {
    return (
      <img
        src={staticUrl(url)}
        alt={label}
        loading="lazy"
        className={`${box} flex-none rounded-lg border border-slate-200 object-cover`}
      />
    );
  }
  return (
    <div
      className={`${box} num flex flex-none items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 font-medium text-slate-400`}
      aria-hidden
    >
      {label.split("-")[0]}
    </div>
  );
}

function Gallery({ items }: { items: Design[] }) {
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {items.map((d) => (
        <Link
          key={d.id}
          to={`/designs/${d.id}`}
          className="card-flush group transition hover:border-brand-300 hover:shadow-md"
        >
          <div className="aspect-square overflow-hidden bg-slate-50">
            {d.image_url ? (
              <img
                src={staticUrl(d.image_url)}
                alt={d.design_no}
                loading="lazy"
                className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
              />
            ) : (
              <div className="num flex h-full w-full items-center justify-center text-2xl font-semibold text-slate-200">
                {d.design_no}
              </div>
            )}
          </div>
          <div className="p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="num truncate text-sm font-medium text-slate-900">
                {d.design_no}
              </span>
              <span className="num flex-none text-xs text-slate-400">{age(d.created_at)}</span>
            </div>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              {d.item_name ?? "—"} · {d.customer_name ?? "Stock"}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <DesignStatusChip status={d.status} />
              {d.current_department_name && (
                <span className="chip-out">{d.current_department_name}</span>
              )}
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}

function NewDesignForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<Named[]>([]);
  const [customers, setCustomers] = useState<Named[]>([]);
  const [itemId, setItemId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [minted, setMinted] = useState<Design | null>(null);

  useEffect(() => {
    if (!open) return;
    setMinted(null);
    setNotes("");
    Promise.all([
      api.get<Named[]>("/items", { params: { is_active: true } }),
      api.get<Named[]>("/customers", { params: { limit: 500 } }),
    ])
      .then(([i, c]) => {
        setItems(i.data);
        setCustomers(c.data);
        setItemId((prev) => prev || String(i.data[0]?.id ?? ""));
      })
      .catch((e) => toast("error", apiError(e, "Could not load items")));
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post<Design>("/designs", {
        item_id: Number(itemId),
        customer_id: customerId ? Number(customerId) : null,
        notes: notes || null,
      });
      setMinted(r.data);
    } catch (err) {
      toast("error", apiError(err, "Could not mint design"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={minted ? "Design minted" : "New design"}>
      {minted ? (
        <div className="space-y-4">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-6 text-center">
            <p className="eyebrow text-emerald-700">Design number</p>
            <p className="num mt-1 text-4xl font-semibold text-emerald-900">{minted.design_no}</p>
            <p className="mx-auto mt-3 max-w-xs text-xs leading-relaxed text-emerald-800">
              Write this on the job card. Everything the piece does from here is filed under it.
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setMinted(null)}>
              Mint another
            </button>
            <Link className="btn-primary" to={`/designs/${minted.id}`}>
              Open {minted.design_no}
            </Link>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <SelectField
            label="Item"
            required
            value={itemId}
            onChange={(e) => setItemId(e.target.value)}
            options={items.map((i) => ({ value: i.id, label: i.name }))}
            hint="The item's abbreviation becomes the design number prefix"
          />
          <SelectField
            label="Customer"
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            options={[
              { value: "", label: "Stock — no customer" },
              ...customers.map((c) => ({ value: c.id, label: c.name })),
            ]}
            hint="Leave on stock unless this is a commission"
          />
          <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={busy || !itemId}>
              {busy ? "Minting…" : "Mint design"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}

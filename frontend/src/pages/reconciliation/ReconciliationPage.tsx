/**
 * What the books say, against what is on the scale.
 *
 * The one thing a precious-metals system has to be able to do, and this one
 * could not. Stock moved only through documents — the right rule, and exactly
 * why a discrepancy had nowhere to go: there was no document for "we weighed
 * it and there is 2.6 g less than there should be".
 *
 * The screen refuses the obvious shortcut. There is no editable stock figure
 * anywhere on it. A count is a **sheet**: you open it, the book figures are
 * frozen, you write down what the scale said, and accepting the difference
 * posts a movement and a journal entry carrying a reason and a name — like
 * every other change in the system.
 *
 * Scopes that cannot yet be counted are shown with their figures and a plain
 * sentence saying why, rather than hidden. Hiding them would imply there is
 * nothing else worth checking; a button that half-worked would be worse.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { TextArea } from "@/components/Field";
import { PasswordConfirm } from "@/components/PasswordConfirm";
import { toast } from "@/components/Toast";
import { apiError } from "@/lib/api-error";
import { fmtMoney } from "@/lib/money";

interface Scope {
  key: string;
  label: string;
  unit: string;
  book_quantity: string;
  book_value: string | null;
  countable: boolean;
  note: string | null;
  last_counted_at: string | null;
  open_count_id: number | null;
  open_count_status: string | null;
}

interface Line {
  id: number;
  inventory_item_id: number;
  label: string;
  purity: number | null;
  tunch_pct: string | null;
  book_weight_g: string;
  counted_weight_g: string | null;
  variance_g: string | null;
  variance_fine_g: string | null;
  notes: string | null;
}

interface Sheet {
  id: number;
  count_no: string;
  branch_name: string | null;
  metal: "gold" | "silver";
  status: "draft" | "submitted" | "posted" | "cancelled";
  counted_at: string;
  reason: string | null;
  lines: Line[];
  book_total_g: string;
  counted_total_g: string;
  variance_g: string;
  variance_fine_g: string;
  variance_value: string | null;
  rate_per_fine_g: string | null;
  unweighed_lines: number;
  journal_entry_no: string | null;
  posted_at: string | null;
  // Whether this shop wants two people on a write-off, and whether this reader
  // may be the second. Sent so the button can be greyed with a sentence rather
  // than letting somebody finish a count and meet a 403 at the last click.
  requires_second_person: boolean;
  can_post: boolean;
  blocked_reason: string | null;
}

const n = (v: string | null) => Number(v ?? 0) || 0;
const g = (v: string | null) => n(v).toFixed(4);

export function ReconciliationPage() {
  const [scopes, setScopes] = useState<Scope[]>([]);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [history, setHistory] = useState<Sheet[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<{ scopes: Scope[] }>("/reconciliation")
      .then((r) => setScopes(r.data.scopes))
      .catch((e) => setError(apiError(e, "Could not load reconciliation")))
      .finally(() => setLoading(false));
    api
      .get<Sheet[]>("/reconciliation/counts", { params: { limit: 20 } })
      .then((r) => setHistory(r.data))
      .catch(() => setHistory([]));
  }, []);

  useEffect(load, [load]);

  const openSheet = async (metal: string, existing: number | null) => {
    try {
      const r = existing
        ? await api.get<Sheet>(`/reconciliation/counts/${existing}`)
        : await api.post<Sheet>("/reconciliation/counts", { metal });
      setSheet(r.data);
    } catch (e) {
      toast("error", apiError(e, "Could not open a count sheet"));
    }
  };

  if (error) return <div className="card text-sm text-red-600">{error}</div>;
  if (loading && !scopes.length) return <div className="card text-sm text-slate-500">Loading…</div>;

  if (sheet) {
    return (
      <CountSheet
        sheet={sheet}
        onChange={setSheet}
        onClose={() => {
          setSheet(null);
          load();
        }}
        asking={asking}
        setAsking={setAsking}
      />
    );
  }

  const countable = scopes.filter((s) => s.countable);
  const rest = scopes.filter((s) => !s.countable);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Reconciliation</h1>
        <p className="mt-1 text-sm text-slate-500">
          What the books say, against what is actually there. Accepting a difference posts
          a document — nothing on this screen edits a balance.
        </p>
      </div>

      <section>
        <h2 className="eyebrow">Countable</h2>
        <div className="mt-2 grid gap-3 lg:grid-cols-2">
          {countable.map((s) => (
            <div key={s.key} className="card flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">{s.label}</p>
                <p className="num mt-0.5 text-xl font-semibold text-slate-900">
                  {Number(s.book_quantity).toFixed(4)}{" "}
                  <span className="text-sm font-normal text-slate-500">{s.unit}</span>
                </p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {s.book_value ? `worth ${fmtMoney(s.book_value)} · ` : ""}
                  {s.last_counted_at
                    ? `last counted ${s.last_counted_at.slice(0, 10)}`
                    : "never counted"}
                </p>
                {s.note && <p className="mt-1 text-[11px] text-amber-700">{s.note}</p>}
              </div>
              {/* A submitted sheet is somebody else's work waiting on a
                  decision, so it gets its own words and its own colour — a
                  button reading "Resume count" would invite the approver to
                  start weighing again. */}
              <button
                className={
                  s.open_count_status === "submitted"
                    ? "btn-primary"
                    : s.open_count_id
                    ? "btn-outline"
                    : "btn-primary"
                }
                onClick={() => openSheet(s.key, s.open_count_id)}
              >
                {s.open_count_status === "submitted"
                  ? "Review & approve"
                  : s.open_count_id
                  ? "Resume count"
                  : "Count"}
              </button>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="eyebrow">Not countable here</h2>
        <div className="mt-2 grid gap-3 lg:grid-cols-2">
          {rest.map((s) => (
            <div key={s.key} className="card bg-slate-50/60">
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-sm font-medium text-slate-700">{s.label}</p>
                <p className="num text-sm font-semibold text-slate-900">
                  {s.unit === "PKR"
                    ? fmtMoney(s.book_quantity)
                    : `${Number(s.book_quantity).toFixed(4)} ${s.unit}`}
                </p>
              </div>
              {s.note && (
                <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{s.note}</p>
              )}
            </div>
          ))}
        </div>
      </section>

      {history.length > 0 && (
        <section>
          <h2 className="eyebrow">Counts taken</h2>
          <div className="card mt-2 overflow-x-auto p-0">
            <table className="w-full min-w-[44rem] text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Sheet</th>
                  <th className="px-4 py-3">Metal</th>
                  <th className="px-4 py-3">Counted</th>
                  <th className="px-4 py-3 text-right">Variance</th>
                  <th className="px-4 py-3">Reason</th>
                  <th className="px-4 py-3">Entry</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {history.map((h) => (
                  <tr
                    key={h.id}
                    className="cursor-pointer hover:bg-slate-50"
                    onClick={() => openSheet(h.metal, h.id)}
                  >
                    <td className="px-4 py-3 font-mono text-xs">
                      {h.count_no}
                      <span
                        className={`ml-2 rounded-full px-2 py-0.5 text-[11px] ${
                          h.status === "posted"
                            ? "bg-emerald-50 text-emerald-700"
                            : h.status === "cancelled"
                            ? "bg-slate-100 text-slate-500"
                            : h.status === "submitted"
                            ? "bg-sky-50 text-sky-700"
                            : "bg-amber-50 text-amber-800"
                        }`}
                      >
                        {h.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 capitalize">{h.metal}</td>
                    <td className="num px-4 py-3 text-xs text-slate-500">
                      {h.counted_at.slice(0, 10)}
                    </td>
                    <td
                      className={`num px-4 py-3 text-right ${
                        n(h.variance_g) < 0
                          ? "font-medium text-red-600"
                          : n(h.variance_g) > 0
                          ? "font-medium text-sky-700"
                          : "text-slate-400"
                      }`}
                    >
                      {n(h.variance_g) ? `${g(h.variance_g)} g` : "agreed"}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">{h.reason ?? "—"}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">
                      {h.journal_entry_no ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {history.length === 0 && (
        <EmptyState title="Nothing has been counted yet">
          Pick a metal above to open a count sheet. The book figures are frozen the moment
          you open it, so a sale made while you are still weighing cannot turn into a
          variance you go hunting for.
        </EmptyState>
      )}
    </div>
  );
}

function CountSheet({
  sheet,
  onChange,
  onClose,
  asking,
  setAsking,
}: {
  sheet: Sheet;
  onChange: (s: Sheet) => void;
  onClose: () => void;
  asking: boolean;
  setAsking: (v: boolean) => void;
}) {
  const [draft, setDraft] = useState<Record<number, string>>(() =>
    Object.fromEntries(sheet.lines.map((l) => [l.id, l.counted_weight_g ?? ""])),
  );
  const [reason, setReason] = useState(sheet.reason ?? "");
  const [saving, setSaving] = useState(false);
  const posted = sheet.status !== "draft";

  // Worked out on screen from the same rule the server uses, so the figure you
  // approve is the figure that posts.
  const live = useMemo(() => {
    let counted = 0;
    let variance = 0;
    let unweighed = 0;
    for (const l of sheet.lines) {
      const raw = draft[l.id];
      if (raw === "" || raw === undefined) {
        unweighed += 1;
        continue;
      }
      counted += Number(raw) || 0;
      variance += (Number(raw) || 0) - n(l.book_weight_g);
    }
    return { counted, variance, unweighed };
  }, [draft, sheet.lines]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.patch<Sheet>(`/reconciliation/counts/${sheet.id}`, {
        reason: reason || null,
        lines: sheet.lines.map((l) => ({
          line_id: l.id,
          counted_weight_g: draft[l.id] === "" ? null : draft[l.id],
        })),
      });
      onChange(r.data);
      toast("success", "Sheet saved");
    } catch (e) {
      toast("error", apiError(e, "Could not save the sheet"));
    } finally {
      setSaving(false);
    }
  };

  const post = async (password: string) => {
    try {
      const r = await api.post<Sheet>(
        `/reconciliation/counts/${sheet.id}/post`,
        {},
        { headers: { "X-Confirm-Password": password } },
      );
      onChange(r.data);
      setAsking(false);
      toast(
        "success",
        r.data.journal_entry_no
          ? `Posted ${r.data.journal_entry_no}`
          : "Counted and it agreed — nothing to post.",
      );
    } catch (e) {
      toast("error", apiError(e, "Could not post the count"));
    }
  };

  const submit = async () => {
    try {
      const r = await api.post<Sheet>(`/reconciliation/counts/${sheet.id}/submit`, {});
      onChange(r.data);
      toast("success", "Sent for approval");
    } catch (e) {
      toast("error", apiError(e, "Could not submit the sheet"));
    }
  };

  const cancel = async () => {
    try {
      await api.post(`/reconciliation/counts/${sheet.id}/cancel`, {});
      toast("success", `${sheet.count_no} cancelled`);
      onClose();
    } catch (e) {
      toast("error", apiError(e, "Could not cancel the sheet"));
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <button onClick={onClose} className="text-xs text-brand-700 hover:underline">
            ← Reconciliation
          </button>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">
            {sheet.count_no}{" "}
            <span className="text-base font-normal capitalize text-slate-500">
              {sheet.metal} count
            </span>
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {sheet.branch_name} · opened {sheet.counted_at.slice(0, 10)}
            {posted && sheet.journal_entry_no && ` · posted as ${sheet.journal_entry_no}`}
          </p>
        </div>
        {!posted && (
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-ghost" onClick={cancel}>
              Cancel sheet
            </button>
            {sheet.status === "draft" && (
              <button className="btn-outline" onClick={save} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
            )}
            {/* Under four eyes the counter hands the sheet on; posting is
                somebody else's click. With the rule off there is nothing to
                hand to, so the submit step is not shown at all. */}
            {sheet.requires_second_person && sheet.status === "draft" && (
              <button
                className="btn-primary"
                disabled={live.unweighed > 0 || !reason.trim()}
                onClick={submit}
                title={
                  live.unweighed > 0
                    ? "Every pot has to be weighed first"
                    : !reason.trim()
                    ? "Say why the books were wrong"
                    : undefined
                }
              >
                Send for approval
              </button>
            )}
            {(!sheet.requires_second_person || sheet.status === "submitted") && (
              <button
                className="btn-primary"
                disabled={live.unweighed > 0 || !reason.trim() || !sheet.can_post}
                onClick={() => setAsking(true)}
                title={
                  sheet.blocked_reason ??
                  (live.unweighed > 0
                    ? "Every pot has to be weighed first"
                    : !reason.trim()
                    ? "Say why the books were wrong"
                    : undefined)
                }
              >
                Accept &amp; post
              </button>
            )}
          </div>
        )}
      </div>

      {sheet.blocked_reason && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
          {sheet.blocked_reason}
        </p>
      )}
      {sheet.status === "submitted" && sheet.can_post && (
        <p className="rounded-lg bg-sky-50 px-3 py-2 text-xs leading-relaxed text-sky-900">
          This sheet is waiting for a decision. Somebody else weighed the metal — you are
          being asked to accept the difference into the books.
        </p>
      )}

      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[46rem] text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Pot</th>
              <th className="px-4 py-3 text-right">System says</th>
              <th className="px-4 py-3 text-right">On the scale</th>
              <th className="px-4 py-3 text-right">Difference</th>
              <th className="px-4 py-3 text-right">As pure</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sheet.lines.map((l) => {
              const raw = draft[l.id];
              const weighed = raw !== "" && raw !== undefined;
              const diff = weighed ? (Number(raw) || 0) - n(l.book_weight_g) : null;
              return (
                <tr key={l.id}>
                  <td className="px-4 py-3">
                    <span className="font-medium text-slate-900">{l.label}</span>
                    <span className="ml-2 text-xs text-slate-400">
                      {l.tunch_pct ? `${Number(l.tunch_pct)} tunch` : l.purity ? `${l.purity}k` : ""}
                    </span>
                  </td>
                  <td className="num px-4 py-3 text-right text-slate-600">
                    {g(l.book_weight_g)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {posted ? (
                      <span className="num">{g(l.counted_weight_g)}</span>
                    ) : (
                      <input
                        type="number"
                        step="0.0001"
                        min="0"
                        className="input w-32 text-right"
                        placeholder="not weighed"
                        value={raw ?? ""}
                        onChange={(e) =>
                          setDraft((p) => ({ ...p, [l.id]: e.target.value }))
                        }
                      />
                    )}
                  </td>
                  <td
                    className={`num px-4 py-3 text-right ${
                      diff === null
                        ? "text-slate-300"
                        : diff < 0
                        ? "font-medium text-red-600"
                        : diff > 0
                        ? "font-medium text-sky-700"
                        : "text-emerald-700"
                    }`}
                  >
                    {diff === null ? "—" : diff === 0 ? "agrees" : diff.toFixed(4)}
                  </td>
                  <td className="num px-4 py-3 text-right text-xs text-slate-500">
                    {l.variance_fine_g !== null && n(l.variance_fine_g) !== 0
                      ? `${g(l.variance_fine_g)} fine`
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot className="border-t-2 border-slate-200 bg-slate-50 text-sm font-medium">
            <tr>
              <td className="px-4 py-3">Total</td>
              <td className="num px-4 py-3 text-right">{g(sheet.book_total_g)}</td>
              <td className="num px-4 py-3 text-right">{live.counted.toFixed(4)}</td>
              <td
                className={`num px-4 py-3 text-right ${
                  live.variance < 0
                    ? "text-red-600"
                    : live.variance > 0
                    ? "text-sky-700"
                    : "text-emerald-700"
                }`}
              >
                {live.variance.toFixed(4)}
              </td>
              <td className="num px-4 py-3 text-right text-xs">
                {n(sheet.variance_fine_g) ? `${g(sheet.variance_fine_g)} fine` : "—"}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* The difference in as-weighed grams is what the counter argues about;
          the fine figure is what actually moves the books, and on a 22k pot the
          two are nine percent apart. Both are shown for that reason. */}
      {n(sheet.variance_g) !== 0 && (
        <div className="card">
          <div className="grid gap-3 sm:grid-cols-3">
            <Figure label="Short / over" value={`${g(sheet.variance_g)} g`} />
            <Figure label="As pure metal" value={`${g(sheet.variance_fine_g)} fine g`} />
            <Figure
              label="Worth"
              value={sheet.variance_value ? fmtMoney(sheet.variance_value) : "no rate on record"}
            />
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            The scale reading and the fine figure differ whenever the pot is not pure — 2.6 g
            missing from a 22k pot is 2.3833 fine grams, and booking it as 2.6 would leave the
            trial balance out by the alloy. The books move by the fine figure.
            {n(sheet.variance_g) > 0 &&
              " More metal than the books show is not a windfall: something arrived that was never recorded."}
          </p>
        </div>
      )}

      {!posted && (
        <div className="card">
          <TextArea
            label="Why were the books wrong?"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Physical stock reconciliation, month end"
          />
          <p className="mt-1 text-[11px] text-slate-500">
            Required. A write-off with no explanation is the first thing an auditor asks
            about, so the system asks first.
          </p>
        </div>
      )}

      {posted && sheet.reason && (
        <div className="card">
          <p className="eyebrow">Reason given</p>
          <p className="mt-1 text-sm text-slate-700">{sheet.reason}</p>
        </div>
      )}

      <PasswordConfirm
        open={asking}
        onClose={() => setAsking(false)}
        title={`Post ${sheet.count_no}?`}
        description={
          `This moves ${g(sheet.variance_fine_g)} fine grams` +
          (sheet.variance_value ? ` (${fmtMoney(sheet.variance_value)})` : "") +
          " between stock and 5500 Stock Variance. The stock movement and the journal " +
          "entry are one transaction. Undoing it means a hand-written reversal."
        }
        confirmLabel="Accept & post"
        onConfirm={post}
      />
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase text-slate-500">{label}</p>
      <p className="num mt-0.5 text-lg font-semibold text-slate-900">{value}</p>
    </div>
  );
}

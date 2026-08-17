/**
 * What the shop has told its customers, and who is worth telling something.
 *
 * The occasions list exists because `date_of_birth` and `anniversary` have sat
 * on the customer record since the beginning with nothing ever reading them —
 * a jeweller's single best repeat-sale prompt, unused. Nothing sends itself:
 * every message is a person deciding to send it.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import { NotifySheet, NotificationKind } from "@/components/NotifySheet";
import { FilterSelect } from "@/components/Toolbar";
import { apiError } from "@/lib/api-error";

interface Note {
  id: number;
  created_at: string;
  kind: string;
  status: "sent" | "failed" | "skipped";
  customer_id: number | null;
  customer_name: string | null;
  to_phone: string | null;
  body: string;
  error: string | null;
  sent_at: string | null;
}

interface Occasion {
  customer_id: number;
  customer_name: string;
  phone: string | null;
  kind: "birthday" | "anniversary";
  date: string;
  days_away: number;
  has_phone: boolean;
}

interface Occasions {
  days: number;
  today: string;
  rows: Occasion[];
}

const KIND_LABELS: Record<string, string> = {
  order_confirmed: "Order confirmed",
  order_ready: "Ready to collect",
  order_delivered: "Thank you",
  invoice: "Invoice",
  payment_reminder: "Balance reminder",
  birthday: "Birthday",
  anniversary: "Anniversary",
  custom: "Message",
};

function StatusChip({ status }: { status: Note["status"] }) {
  if (status === "sent")
    return (
      <span className="chip-back">
        <span className="dot bg-emerald-500" aria-hidden />
        Sent
      </span>
    );
  if (status === "failed")
    return (
      <span className="chip-owed">
        <span className="dot bg-red-500" aria-hidden />
        Failed
      </span>
    );
  return (
    <span className="chip-out">
      <span className="dot bg-amber-500" aria-hidden />
      Not sent
    </span>
  );
}

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function MessagesPage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [occasions, setOccasions] = useState<Occasions | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [send, setSend] = useState<{ kind: NotificationKind; customerId: number } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (status) params.status = status;
    api
      .get<Note[]>("/notifications", { params })
      .then((r) => setNotes(r.data))
      .catch((e) => setError(apiError(e, "Could not load messages")))
      .finally(() => setLoading(false));
    api
      .get<Occasions>("/notifications/occasions", { params: { days: "14" } })
      .then((r) => setOccasions(r.data))
      .catch(() => setOccasions(null));
  }, [status]);

  useEffect(load, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Messages</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Everything the shop has told a customer on WhatsApp — including the messages that never
          left, so nobody assumes a customer knows something they were never told.
        </p>
      </div>

      {occasions && occasions.rows.length > 0 && (
        <section className="card">
          <h2 className="text-sm font-semibold text-slate-900">
            Coming up{" "}
            <span className="font-normal text-slate-400">· next {occasions.days} days</span>
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            A note on the day is the cheapest reason a customer has to come back in.
          </p>
          <ul className="mt-3 divide-y divide-slate-100">
            {occasions.rows.map((o) => (
              <li
                key={`${o.customer_id}-${o.kind}`}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <div className="min-w-0">
                  <span className="text-sm text-slate-900">{o.customer_name}</span>
                  <span className="ml-2 text-xs text-slate-500">
                    {o.kind === "birthday" ? "Birthday" : "Anniversary"}
                    {o.days_away === 0
                      ? " · today"
                      : ` · in ${o.days_away} day${o.days_away === 1 ? "" : "s"}`}
                  </span>
                </div>
                {o.has_phone ? (
                  <button
                    className="btn-outline"
                    onClick={() => setSend({ kind: o.kind, customerId: o.customer_id })}
                  >
                    Send wishes
                  </button>
                ) : (
                  <span className="text-xs text-slate-400">No number on file</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-900">History</h2>
          <FilterSelect
            value={status}
            onChange={setStatus}
            options={[
              { value: "sent", label: "Sent" },
              { value: "skipped", label: "Not sent" },
              { value: "failed", label: "Failed" },
            ]}
            allLabel="All"
          />
        </div>

        {loading && <div className="card mt-3 text-sm text-slate-500">Loading…</div>}
        {error && <div className="card mt-3 text-sm text-red-600">{error}</div>}

        {!loading && !error && notes.length === 0 && (
          <div className="card mt-3 py-10 text-center">
            <p className="text-sm font-medium text-slate-700">
              {status ? "Nothing here." : "No messages yet."}
            </p>
            <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
              {status
                ? "Try another filter."
                : "Messages are sent from an order or a customer — telling someone their piece is ready, or that a balance is outstanding. They'll all be listed here."}
            </p>
          </div>
        )}

        <ul className="mt-3 space-y-2">
          {notes.map((n) => (
            <li key={n.id} className="card p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-slate-900">
                      {n.customer_name ?? "—"}
                    </span>
                    <span className="chip-idle">{KIND_LABELS[n.kind] ?? n.kind}</span>
                    <StatusChip status={n.status} />
                  </div>
                  {n.to_phone && (
                    <p className="num mt-0.5 text-xs text-slate-500">{n.to_phone}</p>
                  )}
                </div>
                <span className="num flex-none text-xs text-slate-400">{when(n.created_at)}</span>
              </div>
              <p className="mt-2 whitespace-pre-line rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-700">
                {n.body}
              </p>
              {n.error && (
                <p className="mt-2 text-xs leading-relaxed text-amber-800">{n.error}</p>
              )}
            </li>
          ))}
        </ul>
      </section>

      <NotifySheet
        open={send !== null}
        onClose={() => setSend(null)}
        kind={send?.kind ?? "birthday"}
        customerId={send?.customerId ?? null}
        onSent={load}
      />
    </div>
  );
}

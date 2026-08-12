import { FormEvent, useEffect, useRef, useState } from "react";
import { AxiosError } from "axios";

import { api } from "@/api/client";
import { apiError } from "@/lib/api-error";

/**
 * A conversation with the shop's own books.
 *
 * The transcript lives here rather than on the server. A chat is not a business
 * record, and keeping threads server-side would mean deciding when they expire
 * and who else in the shop may read them — a question nobody asked.
 *
 * Every figure it quotes comes from a query it shows you. That is the whole
 * design: the model writes SQL, the server validates and runs it read-only, and
 * the query comes back with the answer. An owner who cannot see the query has
 * no way to tell a right answer from a confidently wrong one.
 */

interface Turn {
  role: "user" | "assistant";
  content: string;
  kind?: string;
  sql?: string | null;
  columns?: string[] | null;
  rows?: Record<string, unknown>[] | null;
  notes?: string | null;
}

const SUGGESTIONS = [
  "Kis karigar ka nuqsan sab se zyada hai?",
  "How much gold is out with workers right now?",
  "Which items sold best this month?",
  "How do I issue gold to a karigar?",
];

function Rows({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  if (!rows.length) return <p className="text-xs text-slate-500">No rows matched.</p>;
  return (
    // Query results are arbitrarily wide, so they scroll in their own box
    // rather than pushing the conversation sideways.
    <div className="mt-2 max-h-72 overflow-auto rounded border border-slate-200">
      <table className="w-full text-xs tabular-nums">
        <thead className="sticky top-0 bg-slate-50 text-left text-slate-500">
          <tr>
            {columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-2 py-1 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className="whitespace-nowrap px-2 py-1">
                  {r[c] === null || r[c] === undefined ? "—" : String(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AssistantPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setupNote, setSetupNote] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setError(null);
    setSetupNote(null);
    // The user's turn goes up immediately, and the request carries the whole
    // transcript — that is what lets "and last month?" resolve against what
    // was asked before it.
    const next: Turn[] = [...turns, { role: "user", content: question }];
    setTurns(next);
    setInput("");
    setBusy(true);
    try {
      const { data } = await api.post("/insights/chat", {
        messages: next.map((t) => ({ role: t.role, content: t.content })),
      });
      setTurns([
        ...next,
        {
          role: "assistant",
          content: data.reply,
          kind: data.kind,
          sql: data.sql,
          columns: data.columns,
          rows: data.rows,
          notes: data.notes,
        },
      ]);
    } catch (err) {
      // The failed question stays on screen so it can be retried or edited,
      // rather than vanishing along with the error.
      setTurns(next);
      if (err instanceof AxiosError && err.response?.status === 503) {
        setSetupNote(apiError(err, "AI features are not configured."));
      } else {
        setError(apiError(err, "Could not answer that."));
      }
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(input);
  };

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Assistant</h1>
          <p className="mt-1 text-sm text-slate-500">
            Ask about the shop's records, or how to do something in the system. It can read
            everything and change nothing.
          </p>
        </div>
        {turns.length > 0 && (
          <button className="btn-ghost text-sm" onClick={() => setTurns([])}>
            New conversation
          </button>
        )}
      </div>

      <div className="mt-4 flex-1 space-y-4 overflow-y-auto pr-1">
        {turns.length === 0 && !setupNote && (
          <div className="space-y-3">
            <p className="text-sm text-slate-500">Try one of these:</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="rounded-full border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                  onClick={() => send(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {setupNote && (
          <div className="card border-amber-200 bg-amber-50 text-sm text-amber-900">
            {setupNote}
          </div>
        )}

        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-slate-900 px-4 py-2 text-sm text-white">
                {t.content}
              </div>
            </div>
          ) : (
            <div key={i} className="max-w-[95%] space-y-2">
              <div className="rounded-2xl rounded-bl-sm bg-slate-100 px-4 py-2 text-sm text-slate-900">
                {t.content}
              </div>
              {t.notes && <p className="px-1 text-xs text-slate-500">{t.notes}</p>}
              {/* Shown by default, not folded away behind a toggle: an answer
                  whose query nobody looked at is a figure on trust. */}
              {t.sql && (
                <details open className="px-1">
                  <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700">
                    The query behind this answer
                  </summary>
                  <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
                    {t.sql}
                  </pre>
                  {t.columns && t.rows && <Rows columns={t.columns} rows={t.rows} />}
                </details>
              )}
            </div>
          ),
        )}

        {busy && <p className="text-sm text-slate-400">Thinking…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="mt-4 flex gap-2 border-t border-slate-200 pt-4">
        <input
          className="input flex-1"
          placeholder="Ask in English, Urdu or Roman-Urdu…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
        />
        <button className="btn-primary" type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}

/**
 * Go anywhere by typing, in the shop's own words.
 *
 * Grouping the sidebar made it learnable; this makes it fast, and the two
 * answer different needs. A collapsed sidebar is a good map and a slow one —
 * two clicks to cross from Invoices to Karigars. This is the shortcut for
 * somebody who already knows where they are going.
 *
 * It searches two things at once, and the distinction matters. **Screens** are
 * matched locally from `nav.ts` and appear instantly, because navigating should
 * never wait on a network round trip. **Records** — an invoice number, a
 * customer, a karigar, a serial — are fetched from `/search`, debounced, and
 * appear underneath as they arrive. A palette that blocked on the server to
 * show you "Invoices" would be slower than the sidebar it replaces.
 *
 * The server decides what a record search may return: each type is gated on the
 * same permission its own screen uses, so this never shows a row the user
 * cannot open.
 *
 * It also quietly fixes the vocabulary problem that no amount of grouping
 * could. The system says "workers"; the shop says "karigar". It says
 * "invoice"; the counter says "bill". Each entry in `nav.ts` carries the words
 * a person would actually type, and they are matched but never displayed — so
 * typing "karigar" or "udhaar" or "chandi" finds the screen without the label
 * having to be in two languages at once.
 *
 * Matching is a subsequence, not a prefix: "stpr" finds "Stone parcels". That
 * is forgiving of typing quickly, which is the only state anyone is in when
 * they reach for ⌘K.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { allItems } from "@/components/nav";

interface Hit {
  type: string;
  type_label: string;
  id: number;
  title: string;
  subtitle: string | null;
  badge: string | null;
  to: string;
  score: number;
}

/** Case-insensitive subsequence: every letter of `q` appears in order. */
function fuzzy(text: string, q: string): boolean {
  const t = text.toLowerCase();
  let i = 0;
  for (const ch of q) {
    i = t.indexOf(ch, i);
    if (i === -1) return false;
    i += 1;
  }
  return true;
}

/**
 * Lower is better. Ranked so that an exact word beats a scattered match —
 * typing "sto" should land on "Stone list", not on "Cust*o*mer*s* → *St*atements".
 */
function score(label: string, section: string, keywords: string[], q: string): number | null {
  const l = label.toLowerCase();
  if (l === q) return 0;
  if (l.startsWith(q)) return 1;
  if (l.includes(q)) return 2;
  if (keywords.some((k) => k.toLowerCase().startsWith(q))) return 3;
  if (keywords.some((k) => k.toLowerCase().includes(q))) return 4;
  if (section.toLowerCase().includes(q)) return 5;
  if (fuzzy(label, q)) return 6;
  if (keywords.some((k) => fuzzy(k, q))) return 7;
  return null;
}

export function CommandPalette({ role }: { role: string }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const [hits, setHits] = useState<Hit[]>([]);
  const [searching, setSearching] = useState(false);

  const items = useMemo(() => allItems(role), [role]);

  /**
   * Records, from the server.
   *
   * Debounced at 180ms — long enough that typing "INV-26-00025" fires once
   * rather than twelve times, short enough that it feels immediate. A stale
   * response is dropped rather than rendered: results for "IN" arriving after
   * results for "INV-26" would replace the right answer with a worse one.
   */
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setHits([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    let live = true;
    const t = setTimeout(() => {
      api
        .get<{ hits: Hit[] }>("/search", { params: { q: term } })
        .then((r) => live && setHits(r.data.hits))
        // Silent: the screen results are still on show, and an error banner
        // over a working palette is worse than quietly finding fewer things.
        .catch(() => live && setHits([]))
        .finally(() => live && setSearching(false));
    }, 180);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [q]);

  const results = useMemo(() => {
    const query = q.trim().toLowerCase();
    // No query shows everything, so ⌘K on its own is a full index of the app —
    // which is the fastest way to learn what is in it.
    if (!query) return items;
    return items
      .map((i) => ({ i, s: score(i.label, i.section, i.keywords ?? [], query) }))
      .filter((r): r is { i: (typeof items)[number]; s: number } => r.s !== null)
      .sort((a, b) => a.s - b.s)
      .map((r) => r.i);
  }, [items, q]);

  // One flat list for the keyboard, in the order the eye reads them, so the
  // arrow keys walk straight from the last screen into the first record.
  const rows = useMemo(
    () => [
      ...results.map((r) => ({ kind: "screen" as const, to: r.to, item: r })),
      ...hits.map((h) => ({ kind: "record" as const, to: h.to, item: h })),
    ],
    [results, hits],
  );

  useEffect(() => setCursor(0), [q]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        return;
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQ("");
      // Focused on the next frame: the input does not exist until this render
      // has painted, and focusing a node that is not in the document yet is a
      // no-op that leaves the user typing into the page behind.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  if (!open) return null;

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  return (
    <div className="no-print fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Go to"
        className="relative flex max-h-[70vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-900/10"
      >
        <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-3">
          <svg
            width="18" height="18" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" className="flex-none text-slate-400"
          >
            <circle cx="11" cy="11" r="7" />
            <line x1="16.5" y1="16.5" x2="21" y2="21" />
          </svg>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => Math.min(c + 1, rows.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (e.key === "Enter" && rows[cursor]) {
                e.preventDefault();
                go(rows[cursor].to);
              }
            }}
            placeholder="Search anything — INV-26-00025, a name, a serial…"
            className="w-full border-0 bg-transparent p-0 text-base text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0"
          />
          <kbd className="flex-none rounded border border-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
            esc
          </kbd>
        </div>

        <div className="overflow-y-auto py-2">
          {rows.length === 0 && !searching && (
            <p className="px-4 py-6 text-center text-sm text-slate-500">
              Nothing matches “{q}”.
            </p>
          )}

          {results.length > 0 && (
            <p className="px-4 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Screens
            </p>
          )}
          {results.map((r, idx) => (
            <button
              key={r.to}
              onMouseEnter={() => setCursor(idx)}
              onClick={() => go(r.to)}
              className={`flex w-full items-baseline gap-3 px-4 py-2 text-left transition ${
                idx === cursor ? "bg-brand-50" : "hover:bg-slate-50"
              }`}
            >
              <span className="flex-none text-sm font-medium text-slate-900">{r.label}</span>
              <span className="min-w-0 flex-1 truncate text-xs text-slate-500">{r.hint}</span>
              <span className="flex-none text-[10px] uppercase tracking-wide text-slate-400">
                {r.section}
              </span>
            </button>
          ))}

          {/* Records are a separate heading rather than mixed in. A screen and
              a document are different kinds of answer, and a list that blends
              them makes the reader check the right-hand column on every row to
              find out which one they are looking at. */}
          {(hits.length > 0 || searching) && (
            <p className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Records{searching && <span className="ml-2 font-normal normal-case">searching…</span>}
            </p>
          )}
          {hits.map((h, i) => {
            const idx = results.length + i;
            return (
              <button
                key={`${h.type}-${h.id}`}
                onMouseEnter={() => setCursor(idx)}
                onClick={() => go(h.to)}
                className={`flex w-full items-baseline gap-3 px-4 py-2 text-left transition ${
                  idx === cursor ? "bg-brand-50" : "hover:bg-slate-50"
                }`}
              >
                <span className="num flex-none text-sm font-medium text-slate-900">
                  {h.title}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-slate-500">
                  {h.subtitle}
                </span>
                {h.badge && (
                  <span className="flex-none rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                    {h.badge}
                  </span>
                )}
                <span className="flex-none text-[10px] uppercase tracking-wide text-slate-400">
                  {h.type_label}
                </span>
              </button>
            );
          })}

          {q.trim().length === 1 && (
            <p className="px-4 py-3 text-center text-[11px] text-slate-400">
              Keep typing to search invoices, customers, jobs and serials.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

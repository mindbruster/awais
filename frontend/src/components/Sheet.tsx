import { ReactNode, useEffect } from "react";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Second line under the title — what the sheet is acting on. */
  subtitle?: ReactNode;
  children: ReactNode;
  /** Pinned to the bottom, outside the scroll area, so the commit button is
      always reachable however long the form runs. */
  footer?: ReactNode;
  widthClass?: string;
}

/**
 * A right-anchored slide-over.
 *
 * `Modal` is centred and capped at 90vh, which suits a short confirmation but
 * fights a long form: the body scrolls inside a box that is itself floating in
 * the middle of the screen. A sheet is full-height, so a form with four
 * sections and a running summary beside it gets the width and the vertical run
 * it needs without being squeezed into a sidebar column.
 */
export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  widthClass = "max-w-3xl",
}: SheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="sheet-title"
      className="no-print fixed inset-0 z-50"
    >
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={`absolute inset-y-0 right-0 flex w-full ${widthClass} flex-col bg-slate-50 shadow-2xl ring-1 ring-slate-900/5`}
      >
        <header className="flex flex-none items-start justify-between gap-4 border-b border-slate-200 bg-white px-5 py-4">
          <div className="min-w-0">
            <h2 id="sheet-title" className="text-base font-semibold text-slate-900">
              {title}
            </h2>
            {subtitle && <div className="mt-0.5 text-xs text-slate-500">{subtitle}</div>}
          </div>
          <button
            onClick={onClose}
            className="-m-1 flex-none rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-5">{children}</div>

        {footer && (
          <footer className="flex-none border-t border-slate-200 bg-white px-5 py-4">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}

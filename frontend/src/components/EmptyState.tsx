/**
 * The screen that teaches, when there is nothing to show.
 *
 * A blank table tells a new user they have arrived somewhere useless. The same
 * space can tell them what this screen is for and what to do first, which is
 * the cheapest onboarding there is — it appears exactly when it is needed and
 * disappears the moment it isn't.
 *
 * Two rules, from how these actually get read:
 *   - the action is a verb and says what will happen ("Mint design", not
 *     "Get started"), because a first-time user is deciding whether to trust
 *     the click;
 *   - no jokes. Someone looking at an empty screen is mildly anxious about
 *     whether they have set this up right, and humour reads as evasion.
 */
import { ReactNode } from "react";
import { Link } from "react-router-dom";

interface Props {
  /** What this screen is for, or why it's empty. One line. */
  title: string;
  /** One sentence of value, one of how. */
  children?: ReactNode;
  /** The verb-first primary action. */
  action?: { label: string; onClick?: () => void; to?: string };
  /** A quieter second option — usually where the data comes from instead. */
  secondary?: { label: string; to: string };
  /** Set when the emptiness is the result of a filter rather than no data. */
  filtered?: boolean;
  onClear?: () => void;
}

export function EmptyState({
  title,
  children,
  action,
  secondary,
  filtered,
  onClear,
}: Props) {
  // A filtered-empty screen is a different message: the user has data, they
  // have just hidden it. Offering "add your first…" there is actively wrong.
  if (filtered) {
    return (
      <div className="card py-10 text-center">
        <p className="text-sm font-medium text-slate-700">Nothing matches those filters.</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-slate-500">
          Try widening them, or clear them to see everything.
        </p>
        {onClear && (
          <button className="btn-outline mt-4" onClick={onClear}>
            Clear filters
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="card py-12 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {children && (
        <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-slate-500">
          {children}
        </p>
      )}
      {(action || secondary) && (
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {action &&
            (action.to ? (
              <Link className="btn-primary" to={action.to}>
                {action.label}
              </Link>
            ) : (
              <button className="btn-primary" onClick={action.onClick}>
                {action.label}
              </button>
            ))}
          {secondary && (
            <Link className="btn-outline" to={secondary.to}>
              {secondary.label}
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

import React from "react";

/**
 * The last thing between a render error and a blank white screen.
 *
 * React unmounts the whole tree when a component throws during render, so
 * without this the shop gets an empty page: no message, no navigation, nothing
 * to read out over the phone. On a counter that is taking money that is
 * indistinguishable from the system being down, and it is the one failure the
 * staff cannot work around by trying a different screen.
 *
 * It deliberately does not try to recover the broken subtree. A component that
 * threw once on the same props will throw again, and a retry button that
 * re-renders straight back into the error teaches people the app is flaky. The
 * offer is to go back to the dashboard, which is a screen with different data
 * and therefore a real escape.
 */
type State = { error: Error | null };

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  State
> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Kept in the console rather than swallowed: there is no error-tracking
    // service wired up yet, so the browser console is the only place a
    // developer can see what actually happened.
    console.error("Unhandled render error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-slate-900">
            This screen could not be drawn
          </h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-600">
            Nothing you were looking at has been saved or changed by this — it is
            a display fault, not a lost entry. Your other screens still work.
          </p>
          <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 font-mono text-xs break-words text-slate-500">
            {this.state.error.message || String(this.state.error)}
          </p>
          <a
            href="/"
            className="mt-4 inline-flex rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white"
          >
            Back to the dashboard
          </a>
        </div>
      </div>
    );
  }
}

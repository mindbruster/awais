/**
 * The three charts the dashboard needs, drawn by hand.
 *
 * No charting library on purpose. The bundle is already over Vite's warning
 * threshold, this app carries no UI dependencies beyond React and the router,
 * and three chart types is less SVG than the smallest library's entry point.
 * Hand-drawn also prints: a canvas-based chart comes off the printer blank.
 *
 * Everything is a `viewBox` with no fixed pixel width, so a chart is as wide as
 * whatever holds it. Values are formatted by the caller — these components draw
 * shapes and never decide what a number means.
 */
import { ReactNode, useId } from "react";

const AXIS = "#cbd5e1";
const GRID = "#e2e8f0";
const MUTED = "#94a3b8";

/** A chart with a title, a headline figure, and a note under it. */
export function ChartCard({
  title,
  figure,
  note,
  children,
}: {
  title: string;
  figure?: ReactNode;
  note?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="eyebrow">{title}</h2>
        {figure && <div className="num-lg text-slate-900">{figure}</div>}
      </div>
      {note && <p className="mt-0.5 text-xs text-slate-500">{note}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/**
 * Shown instead of an empty grid.
 *
 * A chart with no data drawn as an empty axis looks like a bug. Saying so in
 * words is the honest rendering, and it is the common case in a shop's first
 * weeks.
 */
function NoData({ what }: { what: string }) {
  return (
    <div className="flex h-32 items-center justify-center rounded border border-dashed border-slate-200 text-xs text-slate-400">
      No {what} in this period yet.
    </div>
  );
}

export interface Point {
  label: string;
  value: number;
}

/**
 * Daily bars. Used for takings.
 *
 * Bars, not a line: a day with no sales is a real, meaningful zero — the shop
 * was shut, or nothing went out — and a line drawn through it implies a
 * gradual decline that did not happen.
 */
export function BarChart({ data, height = 120 }: { data: Point[]; height?: number }) {
  const max = Math.max(...data.map((d) => d.value), 0);
  if (!data.length || max <= 0) return <NoData what="sales" />;

  const w = 100;
  const gap = data.length > 40 ? 0.15 : 0.3;
  const step = w / data.length;
  const barW = step * (1 - gap);

  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="h-32 w-full" preserveAspectRatio="none">
      {[0.25, 0.5, 0.75].map((f) => (
        <line
          key={f}
          x1="0"
          x2={w}
          y1={height * f}
          y2={height * f}
          stroke={GRID}
          strokeWidth="0.5"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {data.map((d, i) => {
        const h = d.value <= 0 ? 0 : Math.max((d.value / max) * (height - 4), 1.5);
        return (
          <rect
            key={i}
            x={i * step + (step - barW) / 2}
            y={height - h}
            width={barW}
            height={h}
            // The last bar is today. Emphasised because it is the one the shop
            // is standing inside.
            fill={i === data.length - 1 ? "#b06a18" : "#d8a55a"}
            rx="0.4"
          >
            <title>{`${d.label}: ${d.value.toLocaleString()}`}</title>
          </rect>
        );
      })}
      <line
        x1="0"
        x2={w}
        y1={height}
        y2={height}
        stroke={AXIS}
        strokeWidth="1"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/**
 * A single line with an emphasised endpoint. Used for the gold rate.
 *
 * The y-axis deliberately does *not* start at zero. A gold rate moving from
 * 30,000 to 31,000 is a real move a shop cares about, and zero-basing it draws
 * a flat line across the top of the chart that hides the only thing worth
 * seeing.
 */
export function LineChart({
  data,
  height = 120,
}: {
  // A null value is a day with no rate on record, not a rate of zero. The two
  // draw completely differently and conflating them puts a cliff in the chart.
  data: { label: string; value: number | null }[];
  height?: number;
}) {
  const gradientId = useId();
  const points = data.filter((d) => d.value !== null) as Point[];
  if (points.length < 2) return <NoData what="rate history" />;

  const values = points.map((p) => p.value);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  // A perfectly flat series would divide by zero; give it a band to sit in.
  const span = hi - lo || Math.max(hi * 0.02, 1);
  const pad = span * 0.15;
  const top = hi + pad;
  const bottom = lo - pad;

  const w = 100;
  const x = (i: number) => (i / (data.length - 1)) * w;
  const y = (v: number) => height - ((v - bottom) / (top - bottom)) * height;

  // Nulls before the first known rate leave a gap rather than a line to zero.
  const path = data
    .map((d, i) => (d.value === null ? null : `${x(i)},${y(d.value)}`))
    .filter(Boolean)
    .join(" ");

  const lastIndex = data.map((d) => d.value).lastIndexOf(values[values.length - 1]);
  const firstIndex = data.findIndex((d) => d.value !== null);

  return (
    // `overflow-visible` so the endpoint marker, which sits exactly on the
    // right edge, is not sliced in half by the viewBox.
    <svg
      viewBox={`0 0 ${w} ${height}`}
      className="h-32 w-full overflow-visible"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#b06a18" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#b06a18" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        points={`${x(firstIndex)},${height} ${path} ${x(data.length - 1)},${height}`}
        fill={`url(#${gradientId})`}
      />
      <polyline
        points={path}
        fill="none"
        stroke="#b06a18"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
      />
      <circle cx={x(lastIndex)} cy={y(values[values.length - 1])} r="2" fill="#b06a18" />
    </svg>
  );
}

/**
 * Two series back to back around a centre line. Used for metal in and out.
 *
 * Mirrored rather than stacked or side by side: in and out are opposites, and
 * a shop reads "more went out than came in this week" off the shape long
 * before it reads the numbers.
 */
export function FlowChart({
  data,
  height = 140,
}: {
  data: { label: string; up: number; down: number }[];
  height?: number;
}) {
  const max = Math.max(...data.flatMap((d) => [d.up, d.down]), 0);
  if (!data.length || max <= 0) return <NoData what="metal movement" />;

  const w = 100;
  const mid = height / 2;
  const step = w / data.length;
  const barW = step * (data.length > 40 ? 0.85 : 0.7);
  const scale = (v: number) => (v / max) * (mid - 3);

  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="h-36 w-full" preserveAspectRatio="none">
      {data.map((d, i) => {
        const cx = i * step + (step - barW) / 2;
        return (
          <g key={i}>
            {d.up > 0 && (
              // Emerald: metal arriving. Same colour the design screens use for
              // "back / settled", so the meaning carries across the app.
              <rect
                x={cx}
                y={mid - scale(d.up)}
                width={barW}
                height={Math.max(scale(d.up), 1)}
                fill="#059669"
                rx="0.4"
              >
                <title>{`${d.label}: ${d.up.toLocaleString()} g in`}</title>
              </rect>
            )}
            {d.down > 0 && (
              // Amber: metal out with someone. The same amber as an open leg.
              <rect
                x={cx}
                y={mid}
                width={barW}
                height={Math.max(scale(d.down), 1)}
                fill="#d97706"
                rx="0.4"
              >
                <title>{`${d.label}: ${d.down.toLocaleString()} g out`}</title>
              </rect>
            )}
          </g>
        );
      })}
      <line
        x1="0"
        x2={w}
        y1={mid}
        y2={mid}
        stroke={AXIS}
        strokeWidth="1"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** The dates under a chart: first, middle and last only. More than three
 *  labels across a phone-width chart is unreadable. */
export function AxisLabels({ data }: { data: { label: string }[] }) {
  if (data.length < 2) return null;
  const middle = data[Math.floor(data.length / 2)];
  return (
    <div className="mt-1 flex justify-between text-[10px]" style={{ color: MUTED }}>
      <span>{data[0].label}</span>
      <span>{middle.label}</span>
      <span>{data[data.length - 1].label}</span>
    </div>
  );
}

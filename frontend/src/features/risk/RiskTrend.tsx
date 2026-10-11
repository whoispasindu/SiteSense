import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
  type TooltipValueType,
} from "recharts";

import type { ProjectRisk } from "../../api/risk";
import { formatDate } from "../projects/dates";
import { LEVEL_LABELS } from "./risk";

const tickDay = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

function shortDay(iso: string): string {
  return tickDay.format(new Date(`${iso}T00:00:00Z`));
}

interface Point {
  date: string;
  score: number;
  range: [number, number] | null;
}

function TrendTooltip({ active, payload, label }: TooltipContentProps<TooltipValueType, string | number>) {
  if (!active || payload.length === 0) return null;
  const point = payload[0]?.payload as Point | undefined;
  if (!point) return null;
  return (
    <div className="rounded-lg border border-rule bg-paper-raised px-3 py-2 text-sm shadow-[var(--shadow-pop)]">
      <p className="mb-1 text-xs text-ink-faint">{typeof label === "string" ? formatDate(label) : ""}</p>
      <p className="tabular font-semibold text-ink">Score {point.score}</p>
      <p className="tabular text-ink-soft">{point.range ? `likely ${String(point.range[0])} to ${String(point.range[1])}` : "no range"}</p>
    </div>
  );
}

/**
 * The last 14 days of scores, each with its likely range as a band, over the BR-10 bands. The chart
 * is decorative for screen readers; the same numbers are in the table underneath.
 */
export function RiskTrend({ history }: { history: ProjectRisk["history"] }) {
  const first = history.at(0);
  const last = history.at(-1);
  if (!first || !last) return <p className="text-sm text-ink-faint">No scores in the last 14 days yet.</p>;
  const data: Point[] = history.map((h) => ({
    date: h.date,
    score: h.score,
    range: h.score_range ? [h.score_range.low, h.score_range.high] : null,
  }));
  const change = last.score - first.score;

  return (
    <figure className="space-y-3">
      <div
        role="img"
        aria-label={`Risk score over the last ${String(history.length)} scored days: from ${String(first.score)} to ${String(last.score)}.`}
        className="h-56 w-full"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: -16 }}>
            <ReferenceArea y1={70} y2={100} fill="var(--color-signal-high-tint)" fillOpacity={0.5} ifOverflow="hidden" />
            <ReferenceArea y1={40} y2={70} fill="var(--color-signal-medium-tint)" fillOpacity={0.4} ifOverflow="hidden" />
            <CartesianGrid stroke="var(--color-rule)" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={shortDay}
              minTickGap={24}
              tick={{ fontSize: 12, fill: "var(--color-ink-faint)" }}
              axisLine={{ stroke: "var(--color-rule)" }}
              tickLine={false}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 40, 70, 100]}
              tick={{ fontSize: 12, fill: "var(--color-ink-faint)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={TrendTooltip} cursor={{ stroke: "var(--color-rule-strong)" }} />
            <Area
              type="monotone"
              dataKey="range"
              name="Likely range"
              stroke="none"
              fill="var(--color-ink)"
              fillOpacity={0.1}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="score"
              name="Score"
              stroke="var(--color-accent-line)"
              strokeWidth={3}
              dot={{ r: 3, fill: "var(--color-accent-line)" }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-ink-soft">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0 w-6 border-t-[3px] border-accent-line" />
          Score
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-3 w-6 rounded-sm bg-ink/10" />
          Likely range
        </span>
        <span>
          {change === 0
            ? "No change over the period."
            : `${change > 0 ? "Up" : "Down"} ${String(Math.abs(change))} points over the period.`}
        </span>
      </figcaption>
      <details className="text-sm">
        <summary className="cursor-pointer font-medium text-survey hover:underline">Show the numbers</summary>
        <table className="mt-2 w-full text-sm">
          <caption className="sr-only">Risk score by day, with its likely range</caption>
          <thead className="text-xs text-ink-faint">
            <tr>
              <th scope="col" className="py-1 text-left font-medium">Date</th>
              <th scope="col" className="py-1 text-right font-medium">Score</th>
              <th scope="col" className="py-1 text-right font-medium">Likely range</th>
              <th scope="col" className="py-1 text-right font-medium">Band</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {history.map((h) => (
              <tr key={h.date}>
                <td className="py-1">{formatDate(h.date)}</td>
                <td className="tabular py-1 text-right">{h.score}</td>
                <td className="tabular py-1 text-right">
                  {h.score_range ? `${String(h.score_range.low)} to ${String(h.score_range.high)}` : "—"}
                </td>
                <td className="py-1 text-right">{LEVEL_LABELS[h.level]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

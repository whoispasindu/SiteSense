import { useId } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
  type TooltipValueType,
} from "recharts";

import type { Progress } from "../../api/schedule";
import { formatDate } from "../projects/dates";

const tickDate = new Intl.DateTimeFormat("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });

function shortDate(iso: string): string {
  return tickDate.format(new Date(`${iso}T00:00:00Z`));
}

export function CurveTooltip({ active, payload, label }: TooltipContentProps<TooltipValueType, string | number>) {
  if (!active || payload.length === 0) return null;
  const planned = payload.find((p) => p.dataKey === "planned")?.value;
  const actual = payload.find((p) => p.dataKey === "actual")?.value;
  return (
    <div className="rounded-lg border border-rule bg-paper-raised px-3 py-2 text-sm shadow-[var(--shadow-pop)]">
      <p className="mb-1 text-xs text-ink-faint">{typeof label === "string" ? formatDate(label) : ""}</p>
      <p className="tabular text-ink-soft">Planned {typeof planned === "number" ? `${planned.toFixed(1)}%` : "—"}</p>
      <p className="tabular font-semibold text-ink">Actual {typeof actual === "number" ? `${actual.toFixed(1)}%` : "—"}</p>
    </div>
  );
}

/**
 * Planned against actual progress. The chart is decorative for screen readers; the same numbers
 * are available in the table underneath and in the summary sentence.
 */
export function SCurve({ progress }: { progress: Progress }) {
  const tableId = useId();
  const fillId = `actual-fill-${tableId.replace(/[^a-zA-Z0-9]/g, "")}`;
  const data = progress.points.map((p) => ({ date: p.date, planned: p.planned, actual: p.actual }));
  const actualPoints = progress.points.filter((p) => p.actual !== null);

  return (
    <figure className="space-y-3">
      <div
        role="img"
        aria-label={`S-curve: planned ${progress.planned_percent.toFixed(1)} percent and actual ${progress.actual_percent.toFixed(1)} percent as of ${formatDate(progress.as_of)}.`}
        className="h-72 w-full sm:h-80"
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 16, right: 32, bottom: 4, left: -8 }}>
            <defs>
              <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--color-accent-line)" stopOpacity={0.3} />
                <stop offset="100%" stopColor="var(--color-accent-line)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--color-rule)" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              minTickGap={36}
              tick={{ fontSize: 12, fill: "var(--color-ink-faint)" }}
              axisLine={{ stroke: "var(--color-rule)" }}
              tickLine={false}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(v: number) => `${String(v)}%`}
              tick={{ fontSize: 12, fill: "var(--color-ink-faint)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={CurveTooltip} cursor={{ stroke: "var(--color-rule-strong)" }} />
            <ReferenceLine
              x={progress.contract_end}
              stroke="var(--color-ink-faint)"
              strokeDasharray="3 3"
              label={{ value: "Contract end", position: "insideTopRight", fontSize: 12, fill: "var(--color-ink-soft)" }}
            />
            <ReferenceLine
              x={progress.as_of}
              stroke="var(--color-survey)"
              strokeWidth={1.5}
              label={{ value: "Today", position: "insideTopLeft", fontSize: 12, fill: "var(--color-survey)" }}
            />
            <Line
              type="monotone"
              dataKey="planned"
              name="Planned"
              stroke="var(--color-ink-faint)"
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={false}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="actual"
              name="Actual"
              stroke="var(--color-accent-line)"
              strokeWidth={3}
              fill={`url(#${fillId})`}
              dot={false}
              activeDot={{ r: 4, fill: "var(--color-accent-line)", stroke: "var(--color-paper-raised)", strokeWidth: 2 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-ink-soft">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0 w-6 border-t-2 border-dashed border-ink-faint" />
          Planned (from task weights and dates)
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0 w-6 border-t-[3px] border-accent-line" />
          Actual (reported progress)
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-3 w-0.5 bg-survey" />
          Today
        </span>
      </figcaption>

      <details className="text-sm">
        <summary className="cursor-pointer font-medium text-survey hover:underline">Show the numbers</summary>
        <div className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-rule">
          <table id={tableId} className="w-full text-sm">
            <caption className="sr-only">Planned and actual progress by date, percent</caption>
            <thead className="sticky top-0 bg-paper-sunk text-xs text-ink-faint">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium">Date</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Planned %</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Actual %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {progress.points.map((p) => (
                <tr key={p.date}>
                  <td className="px-3 py-1.5">{formatDate(p.date)}</td>
                  <td className="tabular px-3 py-1.5 text-right text-ink-soft">{p.planned.toFixed(1)}</td>
                  <td className="tabular px-3 py-1.5 text-right">{p.actual === null ? "—" : p.actual.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-1 text-xs text-ink-faint">{actualPoints.length} dates with recorded progress.</p>
      </details>
    </figure>
  );
}

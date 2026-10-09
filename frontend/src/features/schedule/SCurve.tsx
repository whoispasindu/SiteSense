import { useId } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
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

function CurveTooltip({ active, payload, label }: TooltipContentProps<TooltipValueType, string | number>) {
  if (!active || payload.length === 0) return null;
  const planned = payload.find((p) => p.dataKey === "planned")?.value;
  const actual = payload.find((p) => p.dataKey === "actual")?.value;
  return (
    <div className="rounded-[var(--radius-sheet)] border border-ink bg-paper-raised px-3 py-2 font-mono text-xs shadow-[var(--shadow-sheet)]">
      <p className="mb-1 text-ink-faint">{typeof label === "string" ? formatDate(label) : ""}</p>
      <p>Planned {typeof planned === "number" ? planned.toFixed(1) : "—"} %</p>
      <p className="font-semibold">Actual {typeof actual === "number" ? actual.toFixed(1) : "—"} %</p>
    </div>
  );
}

/**
 * Planned against actual progress. The chart is decorative for screen readers; the same numbers
 * are available in the table underneath and in the summary sentence.
 */
export function SCurve({ progress }: { progress: Progress }) {
  const tableId = useId();
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
          <LineChart data={data} margin={{ top: 16, right: 32, bottom: 4, left: -8 }}>
            <CartesianGrid stroke="var(--color-rule)" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              minTickGap={36}
              tick={{ fontSize: 11, fontFamily: "var(--font-mono)", fill: "var(--color-ink-faint)" }}
              axisLine={{ stroke: "var(--color-rule-strong)" }}
              tickLine={false}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(v: number) => `${String(v)}%`}
              tick={{ fontSize: 11, fontFamily: "var(--font-mono)", fill: "var(--color-ink-faint)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={CurveTooltip} />
            <ReferenceLine
              x={progress.contract_end}
              stroke="var(--color-ink-soft)"
              strokeDasharray="1 3"
              label={{ value: "Contract end", position: "insideTopRight", fontSize: 10, fill: "var(--color-ink-soft)" }}
            />
            <ReferenceLine
              x={progress.as_of}
              stroke="var(--color-hivis-deep)"
              strokeWidth={2}
              label={{ value: "Today", position: "insideTopLeft", fontSize: 10, fill: "var(--color-ink)" }}
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
            <Line
              type="monotone"
              dataKey="actual"
              name="Actual"
              stroke="var(--color-ink)"
              strokeWidth={3}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-ink-soft">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0 w-6 border-t-2 border-dashed border-ink-faint" />
          Planned (from task weights and dates)
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0 w-6 border-t-[3px] border-ink" />
          Actual (reported progress)
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-3 w-0.5 bg-hivis-deep" />
          Today
        </span>
      </figcaption>

      <details className="text-sm">
        <summary className="cursor-pointer text-ink-soft hover:text-ink">Show the numbers</summary>
        <div className="mt-2 max-h-64 overflow-y-auto rounded-[var(--radius-sheet)] border border-rule">
          <table id={tableId} className="w-full font-mono text-xs">
            <caption className="sr-only">Planned and actual progress by date, percent</caption>
            <thead className="sticky top-0 bg-paper-sunk">
              <tr>
                <th scope="col" className="px-3 py-1.5 text-left font-normal">Date</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">Planned %</th>
                <th scope="col" className="px-3 py-1.5 text-right font-normal">Actual %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {progress.points.map((p) => (
                <tr key={p.date}>
                  <td className="px-3 py-1">{formatDate(p.date)}</td>
                  <td className="tabular px-3 py-1 text-right">{p.planned.toFixed(1)}</td>
                  <td className="tabular px-3 py-1 text-right">{p.actual === null ? "—" : p.actual.toFixed(1)}</td>
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

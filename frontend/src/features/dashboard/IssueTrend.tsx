import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { IssueWeek } from "../../api/dashboard";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { formatDayShort } from "../../lib/time";
import { categoryLabel } from "./dashboard";

const shortDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

/** "12 Oct": the Monday a week starts on. */
function weekLabel(iso: string): string {
  return shortDate.format(new Date(`${iso}T00:00:00Z`));
}

function breakdown(week: IssueWeek): [string, number][] {
  return Object.entries(week.by_category)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

function WeekTooltip({ active, payload }: { active?: boolean; payload?: readonly { payload?: IssueWeek }[] }) {
  const week = active ? payload?.[0]?.payload : undefined;
  if (!week) return null;
  const rows = breakdown(week);
  return (
    <div className="rounded-lg border border-rule bg-paper-raised px-3 py-2 text-xs shadow-[var(--shadow-pop)]">
      <p className="font-medium text-ink">
        Week of {formatDayShort(week.week_start)}: {week.total} {week.total === 1 ? "issue" : "issues"}
      </p>
      {rows.length > 0 ? (
        <ul className="mt-1 space-y-0.5 text-ink-soft">
          {rows.map(([category, n]) => (
            <li key={category} className="flex justify-between gap-4">
              <span>{categoryLabel(category)}</span>
              <span className="tabular">{n}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * Confirmed issues per week for the last 8 weeks: one series (the total), with the categories in the
 * tooltip and, for the last four weeks, as a ranked list. Eight categories in eight colours would not read.
 */
export function IssueTrend({ weeks }: { weeks: IssueWeek[] }) {
  const recent = weeks.slice(-4);
  const totals = new Map<string, number>();
  for (const week of recent) {
    for (const [category, n] of Object.entries(week.by_category)) totals.set(category, (totals.get(category) ?? 0) + n);
  }
  const ranked = [...totals.entries()].filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const top = ranked[0]?.[1] ?? 0;
  const summary = weeks.map((w) => `week of ${formatDayShort(w.week_start)}: ${String(w.total)}`).join("; ");

  return (
    <Sheet className="p-5">
      <SectionHeading annotation="confirmed in daily reports">Issues per week</SectionHeading>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div role="img" aria-label={`Confirmed issues per week, last 8 weeks: ${summary}`} className="h-52">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={weeks} margin={{ top: 8, right: 4, bottom: 0, left: -18 }} barCategoryGap="28%">
              <CartesianGrid vertical={false} stroke="var(--color-rule)" />
              <XAxis
                dataKey="week_start"
                tickFormatter={weekLabel}
                tick={{ fontSize: 11, fill: "var(--color-ink-faint)" }}
                axisLine={false}
                tickLine={false}
                interval={0}
              />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--color-ink-faint)" }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "var(--color-paper-sunk)" }} content={<WeekTooltip />} />
              <Bar dataKey="total" fill="var(--color-accent-line)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <p className="text-xs font-medium tracking-wide text-ink-faint uppercase">Last 4 weeks by kind</p>
          {ranked.length === 0 ? (
            <p className="mt-3 text-sm text-ink-soft">No confirmed issues in the last four weeks.</p>
          ) : (
            <ul aria-label="Issues in the last four weeks by kind" className="mt-2 space-y-2">
              {ranked.map(([category, n]) => (
                <li key={category} className="grid grid-cols-[7.5rem_minmax(0,1fr)_2rem] items-center gap-2 text-sm">
                  <span className="truncate text-ink-soft">{categoryLabel(category)}</span>
                  <span aria-hidden="true" className="h-2 rounded-r-[4px] bg-accent-line/70" style={{ width: `${String((n / top) * 100)}%` }} />
                  <span className="tabular text-right font-medium text-ink">{n}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Sheet>
  );
}

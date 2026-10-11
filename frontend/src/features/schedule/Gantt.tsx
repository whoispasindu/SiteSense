import { useEffect, useRef } from "react";

import type { Network, TaskTiming } from "../../api/schedule";
import { formatDate } from "../projects/dates";
import { slipText } from "./network";

const DAY_MS = 86_400_000;
const ROW = 44; // px per task row
const LABEL_WIDTH = "15rem";
const monthLabel = new Intl.DateTimeFormat("en-GB", {
  month: "short",
  timeZone: "UTC",
});

function utc(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}

function months(start: number, end: number): { at: number; label: string }[] {
  const out = [];
  const cursor = new Date(start);
  cursor.setUTCDate(1);
  cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  while (cursor.getTime() <= end) {
    const january = cursor.getUTCMonth() === 0;
    out.push({
      at: cursor.getTime(),
      label: january ? `'${String(cursor.getUTCFullYear()).slice(2)}` : monthLabel.format(cursor),
    });
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  return out;
}

/** Where today falls across the chart (0 to 1), or null when it is outside it. */
function todayPosition(network: Network): number | null {
  if (network.tasks.length === 0) return null;
  const starts = network.tasks.flatMap((t) => [utc(t.planned_start), utc(t.forecast_start)]);
  const ends = [
    ...network.tasks.flatMap((t) => [utc(t.planned_end), utc(t.forecast_finish)]),
    utc(network.planned_end),
  ];
  const from = Math.min(...starts);
  const to = Math.max(...ends) + DAY_MS;
  const today = utc(network.as_of);
  return today < from || today > to ? null : (today - from) / (to - from);
}

function rowNote(t: TaskTiming): string {
  if (t.is_done) return "done";
  const parts = [t.is_critical ? "critical" : `${String(t.total_float)} working days of float`];
  if (t.slip_days !== 0) parts.push(slipText(t.slip_days));
  if (t.stopped) parts.push("stopped by stop-work");
  if (t.rain_days.length > 0) parts.push(`heavy rain forecast ${t.rain_days.map((d) => formatDate(d)).join(", ")}`);
  return parts.join(" · ");
}

/**
 * The programme as a Gantt chart on the forecast network (Phase 9). Each row has the planned bar
 * (thin, grey) and the forecast bar (filled to its progress); critical tasks and the links between
 * them are red. Slip, stop-work (BR-11) and heavy rain on a pour (BR-06) are marked in words too.
 * The chart is drawn for sight; the same facts are in the table that screen readers get.
 */
export function Gantt({ network }: { network: Network }) {
  const scroller = useRef<HTMLDivElement>(null);
  const tasks = network.tasks;
  const todayShare = todayPosition(network);

  // On a narrow screen the chart scrolls sideways: open it with today in view, not the project start.
  useEffect(() => {
    const box = scroller.current;
    if (!box || todayShare === null || box.scrollWidth <= box.clientWidth) return;
    box.scrollLeft = Math.max(0, todayShare * box.scrollWidth - box.clientWidth / 3);
  }, [todayShare]);

  if (tasks.length === 0) return null;
  const starts = tasks.flatMap((t) => [utc(t.planned_start), utc(t.forecast_start)]);
  const ends = tasks.flatMap((t) => [utc(t.planned_end), utc(t.forecast_finish)]);
  ends.push(utc(network.planned_end));
  const from = Math.min(...starts);
  const to = Math.max(...ends) + DAY_MS;
  const span = Math.max(to - from, DAY_MS);
  const x = (t: number) => ((t - from) / span) * 100; // percent of the timeline
  const pct = (t: number) => `${String(Math.min(100, Math.max(0, x(t))))}%`;
  const today = utc(network.as_of);
  const row = new Map(tasks.map((t, i) => [t.task_id, i]));
  const critical = new Set(tasks.filter((t) => t.is_critical).map((t) => t.task_id));

  return (
    <div>
      <div ref={scroller} className="relative overflow-x-auto overflow-y-hidden">
        <div className="min-w-[52rem]" aria-hidden="true">
          <div className="relative h-7 border-b border-rule" style={{ marginLeft: LABEL_WIDTH }}>
            {months(from, to).map((m) => (
              <span
                key={m.at}
                className="absolute top-0 h-full border-l border-rule pl-1.5 text-xs text-ink-faint"
                style={{ left: pct(m.at) }}
              >
                {m.label}
              </span>
            ))}
          </div>
          <div className="relative">
            {/* Dependency links, drawn in timeline units so they stretch with the chart. */}
            <svg
              className="pointer-events-none absolute top-0 h-full"
              style={{
                left: LABEL_WIDTH,
                width: `calc(100% - ${LABEL_WIDTH})`,
              }}
              viewBox={`0 0 100 ${String(tasks.length * ROW)}`}
              preserveAspectRatio="none"
            >
              {network.dependencies.map((d) => {
                const a = row.get(d.predecessor_id);
                const b = row.get(d.successor_id);
                const before = tasks[a ?? -1];
                const after = tasks[b ?? -1];
                if (a === undefined || b === undefined || !before || !after) return null;
                const x1 = x(utc(before.forecast_finish) + DAY_MS);
                const x2 = x(utc(after.forecast_start));
                const y1 = a * ROW + ROW / 2;
                const y2 = b * ROW + ROW / 2;
                const mid = Math.max(x1 + 0.6, Math.min(x2 - 0.3, x1 + 1.2));
                const hot = critical.has(d.predecessor_id) && critical.has(d.successor_id);
                return (
                  <path
                    key={d.id}
                    d={`M ${String(x1)} ${String(y1)} H ${String(mid)} V ${String(y2)} H ${String(x2)}`}
                    fill="none"
                    vectorEffect="non-scaling-stroke"
                    className={hot ? "stroke-signal-high" : "stroke-ink-faint"}
                    strokeWidth={hot ? 1.75 : 1}
                    strokeDasharray={hot ? undefined : "3 3"}
                  />
                );
              })}
            </svg>
            {today >= from && today <= to ? (
              <div className="pointer-events-none absolute top-0 bottom-0 z-10" style={{ left: LABEL_WIDTH, right: 0 }}>
                <div className="absolute top-0 bottom-0 w-0.5 bg-survey" style={{ left: pct(today) }} />
              </div>
            ) : null}
            {tasks.map((t) => {
              const done = Number(t.percent_complete);
              const fs = utc(t.forecast_start);
              const fe = utc(t.forecast_finish) + DAY_MS;
              const late = t.slip_days > 0 && !t.is_done;
              return (
                <div key={t.task_id} className="flex items-center border-b border-rule" style={{ height: ROW }}>
                  <div
                    className="flex shrink-0 items-center gap-1.5 truncate pr-3 text-sm text-ink"
                    style={{ width: LABEL_WIDTH }}
                  >
                    <span className="font-mono text-xs text-ink-faint">{t.code ?? ""}</span>
                    <span className={`truncate ${t.is_critical ? "font-semibold" : ""}`}>{t.name}</span>
                    {t.stopped ? (
                      <span className="shrink-0 rounded bg-signal-high px-1.5 text-[0.6875rem] font-semibold text-white">
                        STOP
                      </span>
                    ) : null}
                    {t.rain_days.length > 0 ? <span className="shrink-0 text-xs text-survey">☂</span> : null}
                  </div>
                  <div className="relative h-full flex-1">
                    {/* planned */}
                    <div
                      className="absolute top-[9px] h-1.5 rounded-full bg-rule-strong"
                      style={{
                        left: pct(utc(t.planned_start)),
                        width: `calc(${pct(utc(t.planned_end) + DAY_MS)} - ${pct(utc(t.planned_start))})`,
                      }}
                    />
                    {/* forecast */}
                    <div
                      className={`absolute top-[19px] h-4 overflow-hidden rounded ${
                        t.is_done
                          ? "bg-signal-low/80"
                          : t.is_critical
                            ? "bg-signal-high-tint ring-1 ring-signal-high"
                            : "bg-paper-sunk ring-1 ring-rule-strong"
                      } ${t.stopped ? "bg-[repeating-linear-gradient(135deg,transparent_0_5px,rgb(214_69_65/.35)_5px_9px)]" : ""}`}
                      style={{
                        left: pct(fs),
                        width: `calc(${pct(fe)} - ${pct(fs)})`,
                      }}
                    >
                      {!t.is_done ? (
                        <div
                          className={`h-full ${t.is_critical ? "bg-signal-high/60" : "bg-accent-line"}`}
                          style={{ width: `${String(done)}%` }}
                        />
                      ) : null}
                    </div>
                    {late ? (
                      <span
                        className="absolute top-[18px] pl-1 text-xs font-medium whitespace-nowrap text-signal-high"
                        style={{ left: pct(fe) }}
                      >
                        +{t.slip_days}d
                      </span>
                    ) : null}
                    {t.rain_days.map((d) => (
                      <span
                        key={d}
                        className="absolute top-[34px] h-2 w-1 -translate-x-1/2 rounded-b-full bg-survey"
                        style={{ left: pct(utc(d) + DAY_MS / 2) }}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="sr-only">
        <table>
          <caption>Programme: planned and forecast dates, float and flags for each task</caption>
          <thead>
            <tr>
              <th scope="col">Task</th>
              <th scope="col">Planned</th>
              <th scope="col">Forecast</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.task_id}>
                <th scope="row">
                  {t.code ? `${t.code} ` : ""}
                  {t.name}
                </th>
                <td>
                  {formatDate(t.planned_start)} to {formatDate(t.planned_end)}
                </td>
                <td>
                  {formatDate(t.forecast_start)} to {formatDate(t.forecast_finish)}
                </td>
                <td>{rowNote(t)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-faint">
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-1.5 w-5 rounded-full bg-rule-strong" /> Planned
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-5 rounded bg-paper-sunk ring-1 ring-rule-strong" />{" "}
          Forecast, filled to progress
        </span>
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-5 rounded bg-signal-high-tint ring-1 ring-signal-high"
          />{" "}
          Critical: any delay moves handover
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-0.5 bg-survey" /> Today
        </span>
        <span>STOP: stopped by a stop-work flag (BR-11)</span>
        <span>☂ and blue marks: 10 mm or more of rain forecast on a pour day (BR-06)</span>
        <span>+Nd: working days past the planned end</span>
      </p>
    </div>
  );
}

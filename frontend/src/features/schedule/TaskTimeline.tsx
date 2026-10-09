import type { Task } from "../../api/schedule";
import { formatDate } from "../projects/dates";

const DAY_MS = 86_400_000;
const monthLabel = new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" });

function utc(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}

function months(start: number, end: number): { at: number; label: string; year: boolean }[] {
  const out = [];
  const cursor = new Date(start);
  cursor.setUTCDate(1);
  cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  while (cursor.getTime() <= end) {
    out.push({ at: cursor.getTime(), label: monthLabel.format(cursor), year: cursor.getUTCMonth() === 0 });
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  return out;
}

interface TaskTimelineProps {
  tasks: Task[];
  start: string;
  end: string;
  today: string;
}

/**
 * One bar per task across the programme. The filled part is reported progress; the thin mark is
 * where the plan says the task should be today. Every number is also in the task list as text.
 */
export function TaskTimeline({ tasks, start, end, today }: TaskTimelineProps) {
  const from = utc(start);
  const to = utc(end) + DAY_MS;
  const span = Math.max(to - from, DAY_MS);
  const pos = (t: number) => `${String(Math.min(100, Math.max(0, ((t - from) / span) * 100)))}%`;
  const todayAt = utc(today);
  const showToday = todayAt >= from && todayAt <= to;

  return (
    <div className="relative overflow-x-auto">
      <div className="min-w-[44rem]" aria-hidden="true">
        <div className="relative ml-56 h-6 border-b border-rule-strong">
          {months(from, to).map((m) => (
            <span
              key={m.at}
              className={`absolute top-0 h-full border-l pl-1 font-mono text-[0.6rem] ${m.year ? "border-ink font-semibold text-ink" : "border-rule text-ink-faint"}`}
              style={{ left: pos(m.at) }}
            >
              {/* January shows the year instead, so the scale reads ... Nov Dec '27 Feb ... */}
              {m.year ? `'${String(new Date(m.at).getUTCFullYear()).slice(2)}` : m.label}
            </span>
          ))}
        </div>

        <div className="relative">
          {showToday ? (
            <div className="pointer-events-none absolute top-0 bottom-0 z-10 ml-56" style={{ left: 0, right: 0 }}>
              <div className="absolute top-0 bottom-0 w-0.5 bg-hivis-deep" style={{ left: pos(todayAt) }} />
            </div>
          ) : null}

          {tasks.map((task) => {
            const s = utc(task.planned_start);
            const e = utc(task.planned_end) + DAY_MS;
            const done = Number(task.percent_complete);
            return (
              <div key={task.id} className="flex h-10 items-center border-b border-rule">
                <div className="w-56 shrink-0 truncate pr-3 text-xs">
                  {task.is_critical ? <span className="mr-1 font-bold text-signal-high">!</span> : null}
                  <span className="mr-1.5 font-mono text-ink-faint">{task.code ?? ""}</span>
                  {task.name}
                </div>
                <div className="relative h-full flex-1">
                  <div
                    title={`${task.name}: ${formatDate(task.planned_start)} to ${formatDate(task.planned_end)}, ${task.percent_complete}% done`}
                    className={`absolute top-1/2 h-4 -translate-y-1/2 overflow-hidden rounded-[2px] border ${
                      task.is_critical ? "border-signal-high" : "border-ink"
                    } bg-paper-sunk`}
                    style={{ left: pos(s), width: `calc(${pos(e)} - ${pos(s)})` }}
                  >
                    <div
                      className={`h-full ${task.state === "behind" ? "hazard-band" : "bg-ink"}`}
                      style={{ width: `${String(done)}%` }}
                    />
                    {task.planned_percent_today > 0 && task.planned_percent_today < 100 ? (
                      <span
                        className="absolute top-0 bottom-0 w-0.5 bg-survey"
                        style={{ left: `${String(task.planned_percent_today)}%` }}
                      />
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <p className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-soft">
        <span>Filled: reported progress (striped when behind plan).</span>
        <span>Blue mark: where the plan says the task should be today.</span>
        <span>Red outline and "!": critical task.</span>
      </p>
    </div>
  );
}

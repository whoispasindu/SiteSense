import { Link } from "react-router";

import { useScheduleSummary } from "../../api/schedule";
import { Alert } from "../../components/ui/Alert";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { varianceLabel } from "../../features/schedule/variance";

function ProgressPair({ planned, actual }: { planned: number; actual: number }) {
  return (
    <div aria-hidden="true" className="space-y-1.5">
      <div className="relative h-2 rounded-full bg-paper-sunk">
        <div className="absolute inset-y-0 left-0 rounded-full bg-rule-strong" style={{ width: `${String(planned)}%` }} />
      </div>
      <div className="relative h-2 rounded-full bg-paper-sunk">
        <div className="absolute inset-y-0 left-0 rounded-full bg-accent-line" style={{ width: `${String(actual)}%` }} />
      </div>
    </div>
  );
}

export function SchedulePage() {
  const summary = useScheduleSummary();
  // Furthest behind first: that is where attention is needed.
  const rows = [...(summary.data ?? [])].sort((a, b) => a.variance - b.variance);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        title="Schedule"
        description="Planned against actual progress for every project you can see, furthest behind first."
      />

      {summary.isError ? <Alert tone="error">{errorText(summary.error)}</Alert> : null}
      {summary.isPending ? <p className="py-10 text-center text-ink-faint">Loading…</p> : null}
      {summary.data && rows.length === 0 ? (
        <Sheet className="px-6 py-12 text-center text-ink-soft">No projects on your sites yet.</Sheet>
      ) : null}

      <ol aria-label="Projects by schedule variance" className="space-y-3">
        {rows.map((row) => {
          const v = varianceLabel(row.variance);
          return (
            <li key={row.project.id}>
              <Link
                to={`/projects/${row.project.id}/schedule`}
                className="group grid gap-4 rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-5 shadow-[var(--shadow-sheet)] transition hover:border-rule-strong hover:shadow-[var(--shadow-pop)] md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] md:items-center md:gap-8"
              >
                <div className="min-w-0">
                  <p className="text-xs text-ink-faint">
                    {row.project.code} · {row.project.site.code}
                  </p>
                  <h2 className="mt-1 truncate text-base font-semibold text-ink group-hover:text-survey">
                    {row.project.name}
                  </h2>
                  <p className="text-xs text-ink-faint">Handover planned {formatDate(row.project.planned_end)}</p>
                </div>
                <div>
                  {row.task_count === 0 ? (
                    <p className="text-sm text-ink-faint">No programme yet</p>
                  ) : (
                    <>
                      <ProgressPair planned={row.planned_percent} actual={row.actual_percent} />
                      <p className="tabular mt-2 flex justify-between text-xs text-ink-soft">
                        <span>Planned {row.planned_percent.toFixed(1)}%</span>
                        <span className="font-semibold text-ink">Actual {row.actual_percent.toFixed(1)}%</span>
                      </p>
                    </>
                  )}
                </div>
                <div className="md:text-right">{row.task_count > 0 ? <StatusBadge tone={v.tone} label={v.label} /> : null}</div>
              </Link>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

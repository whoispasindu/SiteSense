import { Link } from "react-router";

import { useTodayStatus } from "../../api/reports";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { primaryLinkClass } from "../../components/ui/Button";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { formatSiteTime } from "../../lib/time";
import { errorText } from "../admin/adminUtils";

/** BR-11 at a glance: has every active project filed today's report, and is the deadline close? */
export function TodayReports({ compact = false }: { compact?: boolean }) {
  const status = useTodayStatus();
  const { can } = useAuth();
  const canWrite = can("reports:create");

  if (status.isError) return <Alert tone="error">{errorText(status.error)}</Alert>;
  const data = status.data;
  const missing = data?.projects.filter((p) => p.report_id === null).length ?? 0;

  return (
    <Sheet className="p-5">
      <SectionHeading
        id="today-reports-heading"
        annotation={data ? `due ${formatSiteTime(data.deadline)}` : undefined}
        action={
          compact ? (
            <Link to="/reports" className="text-sm font-medium text-survey hover:underline">
              All reports
            </Link>
          ) : undefined
        }
      >
        Today&apos;s reports
      </SectionHeading>
      {status.isPending ? <p className="py-4 text-sm text-ink-faint">Loading…</p> : null}
      {data && data.projects.length === 0 ? (
        <p className="py-4 text-sm text-ink-soft">No active projects on your sites.</p>
      ) : null}
      {data && data.projects.length > 0 ? (
        <>
          <p className="mb-2 text-sm text-ink-soft" aria-live="polite">
            {missing === 0
              ? "Every active project has filed today's report."
              : `${String(missing)} of ${String(data.projects.length)} still to file${data.deadline_passed ? ", past the deadline" : ""}.`}
          </p>
          <ul aria-labelledby="today-reports-heading" className="divide-y divide-rule">
            {data.projects.map((p) => (
              <li key={p.project_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <Link to={`/projects/${p.project_id}/reports`} className="font-medium text-ink hover:underline">
                    {p.project_name}
                  </Link>
                  <p className="text-sm text-ink-faint">
                    {p.report_id && p.submitted_at
                      ? `Filed by ${p.author_name ?? "unknown"} at ${formatSiteTime(p.submitted_at)}`
                      : `Site ${p.site_code}`}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  {p.report_id ? (
                    <>
                      <StatusBadge tone="ok" label="Filed" />
                      <Link to={`/reports/${p.report_id}`} className="text-sm font-medium text-survey hover:underline">
                        Open
                      </Link>
                    </>
                  ) : (
                    <>
                      <StatusBadge tone={data.deadline_passed ? "down" : "warn"} label={data.deadline_passed ? "Overdue" : "Not filed"} />
                      {canWrite ? (
                        <Link to={`/projects/${p.project_id}/reports/new`} className={primaryLinkClass}>
                          Write report
                        </Link>
                      ) : null}
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Sheet>
  );
}

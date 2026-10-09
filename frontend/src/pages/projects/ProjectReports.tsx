import { useState } from "react";
import { Link } from "react-router";

import { REPORTS_PAGE_SIZE, useReports, useWeather } from "../../api/reports";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button, primaryLinkClass } from "../../components/ui/Button";
import { Icon } from "../../components/ui/icons";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { WeatherStrip } from "../../features/reports/WeatherStrip";
import { formatSiteTime, siteTodayIso } from "../../lib/time";
import { useCurrentProject } from "./projectContext";

export function ProjectReports() {
  const project = useCurrentProject();
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const reports = useReports(project.id, offset);
  const weather = useWeather(project.id);
  const today = siteTodayIso();
  const filedToday = reports.data?.items.some((r) => r.report_date === today) ?? false;
  const canWrite = can("reports:create") && (project.status === "active" || project.status === "on_hold");
  const total = reports.data?.total ?? 0;

  return (
    <div className="space-y-10">
      <section aria-labelledby="weather-heading">
        <SectionHeading id="weather-heading" annotation={`site ${project.site.code}`}>
          Weather
        </SectionHeading>
        {weather.isPending ? <p className="text-sm text-ink-faint">Loading forecast…</p> : null}
        {weather.isError ? <Alert tone="warn">The forecast could not be loaded. Reports can still be filed.</Alert> : null}
        {weather.data ? <WeatherStrip weather={weather.data} today={today} /> : null}
      </section>

      <section aria-labelledby="reports-heading">
        <SectionHeading
          id="reports-heading"
          annotation={total ? `${String(total)} reports` : undefined}
          action={
            canWrite && !filedToday ? (
              <Link to={`/projects/${project.id}/reports/new`} className={primaryLinkClass}>
                <Icon name="plus" className="size-4" />
                Write today&apos;s report
              </Link>
            ) : undefined
          }
        >
          Daily reports
        </SectionHeading>

        {reports.isError ? <Alert tone="error">{errorText(reports.error)}</Alert> : null}
        {reports.isPending ? <p className="py-8 text-center text-ink-faint">Loading reports…</p> : null}
        {reports.data?.items.length === 0 ? (
          <Sheet className="px-6 py-12 text-center">
            <p className="font-semibold text-ink">No reports yet</p>
            <p className="mt-1 text-sm text-ink-soft">
              {canWrite ? "File the first daily report for this project." : "The site engineer files a report every working day."}
            </p>
          </Sheet>
        ) : null}

        {reports.data && reports.data.items.length > 0 ? (
          <ol aria-label="Daily reports, newest first" className="space-y-3">
            {reports.data.items.map((r) => (
              <li key={r.id}>
                <Link
                  to={`/reports/${r.id}`}
                  className="group grid gap-3 rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-4 shadow-[var(--shadow-sheet)] transition hover:border-rule-strong hover:shadow-[var(--shadow-pop)] sm:grid-cols-[9rem_minmax(0,1fr)_auto] sm:items-center sm:gap-6"
                >
                  <div>
                    <p className="font-semibold text-ink group-hover:text-survey">{formatDate(r.report_date)}</p>
                    <p className="text-xs text-ink-faint">
                      {r.author.full_name} · {formatSiteTime(r.submitted_at)}
                    </p>
                  </div>
                  <p className="line-clamp-2 text-sm text-ink-soft">{r.work_done_preview}</p>
                  <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                    {r.has_problems ? <StatusBadge tone="warn" label="Problems noted" /> : null}
                    <span className="inline-flex items-center gap-1 text-xs text-ink-faint" title="Crew on site">
                      <Icon name="crew" className="size-4" />
                      <span className="sr-only">Crew</span> {r.crew_count}
                    </span>
                    {r.photo_count ? (
                      <span className="inline-flex items-center gap-1 text-xs text-ink-faint">
                        <Icon name="camera" className="size-4" />
                        <span className="sr-only">Photos</span> {r.photo_count}
                      </span>
                    ) : null}
                    {r.weather_summary ? <span className="text-xs text-ink-faint">{r.weather_summary}</span> : null}
                  </div>
                </Link>
              </li>
            ))}
          </ol>
        ) : null}

        {total > REPORTS_PAGE_SIZE ? (
          <div className="mt-4 flex justify-between gap-3">
            <Button
              disabled={offset === 0}
              onClick={() => {
                setOffset(Math.max(0, offset - REPORTS_PAGE_SIZE));
              }}
            >
              Newer
            </Button>
            <Button
              disabled={offset + REPORTS_PAGE_SIZE >= total}
              onClick={() => {
                setOffset(offset + REPORTS_PAGE_SIZE);
              }}
            >
              Older
            </Button>
          </div>
        ) : null}
      </section>
    </div>
  );
}

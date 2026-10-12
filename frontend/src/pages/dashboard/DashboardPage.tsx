import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { downloadWeeklyReport, usePortfolio, type Kpis, type SiteWeather } from "../../api/dashboard";
import { useHealth, useReadiness } from "../../api/health";
import { useProjects } from "../../api/projects";
import { useScheduleSummary } from "../../api/schedule";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Icon, type IconName } from "../../components/ui/icons";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";
import { AlertsList, ApprovalQueue } from "../../features/dashboard/AlertsAndApprovals";
import { BriefingCard } from "../../features/dashboard/BriefingCard";
import { CostAgainstPlan } from "../../features/dashboard/CostAgainstPlan";
import { asWeather } from "../../features/dashboard/dashboard";
import { IssueTrend } from "../../features/dashboard/IssueTrend";
import { KpiTile } from "../../features/projects/ProjectBits";
import { TodayReports } from "../../features/reports/TodayReports";
import { WeatherStrip } from "../../features/reports/WeatherStrip";
import { RiskRankingPanel } from "../../features/risk/RiskRankingPanel";
import { varianceLabel } from "../../features/schedule/variance";
import { formatSiteDate, greeting, siteTodayIso } from "../../lib/time";

function ScheduleHealth() {
  const summary = useScheduleSummary();
  const rows = [...(summary.data ?? [])].sort((a, b) => a.variance - b.variance).slice(0, 6);

  return (
    <Sheet className="p-5">
      <SectionHeading
        annotation="planned vs actual"
        action={
          <Link to="/schedule" className="text-sm font-medium text-survey hover:underline">
            View schedule
          </Link>
        }
      >
        Schedule health
      </SectionHeading>
      {summary.isPending ? <p className="py-6 text-sm text-ink-faint">Loading…</p> : null}
      {summary.data?.length === 0 ? <p className="py-6 text-sm text-ink-soft">No projects on your sites yet.</p> : null}
      <ul aria-label="Schedule health by project" className="divide-y divide-rule">
        {rows.map((row) => {
          const v = varianceLabel(row.variance);
          return (
            <li key={row.project.id} className="py-3">
              <div className="flex items-center justify-between gap-3">
                <Link to={`/projects/${row.project.id}/schedule`} className="min-w-0 truncate font-medium text-ink hover:underline">
                  {row.project.name}
                </Link>
                {row.task_count > 0 ? (
                  <StatusBadge tone={v.tone} label={v.label} />
                ) : (
                  <span className="text-xs text-ink-faint">No programme</span>
                )}
              </div>
              {row.task_count > 0 ? (
                <div className="mt-2 flex items-center gap-3">
                  <div aria-hidden="true" className="relative h-2 flex-1 overflow-hidden rounded-full bg-paper-sunk">
                    <div className="absolute inset-y-0 left-0 rounded-full bg-rule-strong" style={{ width: `${String(row.planned_percent)}%` }} />
                    <div className="absolute inset-y-0 left-0 rounded-full bg-accent-line" style={{ width: `${String(row.actual_percent)}%` }} />
                  </div>
                  <span className="tabular w-32 shrink-0 text-right text-xs text-ink-soft">
                    {row.actual_percent.toFixed(1)}% <span className="text-ink-faint">of {row.planned_percent.toFixed(1)}%</span>
                  </span>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {rows.length > 0 ? (
        <p className="mt-3 flex items-center gap-4 text-xs text-ink-faint">
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2 w-4 rounded-full bg-accent-line" /> Actual
          </span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2 w-4 rounded-full bg-rule-strong" /> Planned to date
          </span>
        </p>
      ) : null}
    </Sheet>
  );
}

/** Permissions that put things in someone's approval queue. Without any, the queue is left out. */
const APPROVER_PERMISSIONS = [
  "materials:approve_qs",
  "materials:approve_pm",
  "purchase_orders:manage",
  "claims:approve",
  "variations:price",
  "variations:approve",
];

function DashboardKpis({ kpis, approver }: { kpis: Kpis; approver: boolean }) {
  const progress = kpis.average_actual_pct;
  const missing = kpis.reports_due_today - kpis.reports_filed_today;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <KpiTile icon="projects" label="Active projects" value={String(kpis.active_projects)} note={`${String(kpis.total_projects)} on your sites`} />
      <KpiTile
        icon="schedule"
        label="Average progress"
        value={progress === null ? "—" : `${progress.toFixed(1)}%`}
        note={
          kpis.average_planned_pct === null
            ? "No programmes yet"
            : `Planned ${kpis.average_planned_pct.toFixed(1)}% · ${String(kpis.behind_plan)} behind plan`
        }
        tone={kpis.behind_plan ? "warn" : progress === null ? "idle" : "ok"}
      />
      <KpiTile
        icon="reports"
        label="Reports today"
        value={`${String(kpis.reports_filed_today)} of ${String(kpis.reports_due_today)}`}
        note={missing > 0 ? `${String(missing)} still to file (BR-07)` : "Every report due is filed"}
        tone={missing > 0 ? "warn" : "ok"}
      />
      <KpiTile
        icon="alert"
        label="Stop-work open"
        value={String(kpis.stop_work_open)}
        note={kpis.stop_work_open ? "Waiting for the project manager (BR-11)" : "No stop-work flags"}
        tone={kpis.stop_work_open ? "down" : "ok"}
      />
      {kpis.high_risk !== null ? (
        <KpiTile
          icon="risk"
          label="High risk"
          value={String(kpis.high_risk)}
          note={kpis.high_risk ? "Risk score 70 or more (BR-10)" : "No project is at high risk"}
          tone={kpis.high_risk ? "down" : "ok"}
        />
      ) : null}
      <KpiTile icon="crew" label="Issues this week" value={String(kpis.issues_this_week)} note="Confirmed in daily reports since Monday" />
      {approver ? (
        <KpiTile
          icon="materials"
          label="Waiting for you"
          value={String(kpis.waiting_for_you)}
          note={kpis.waiting_for_you ? "Approvals and orders, oldest first below" : "Nothing to approve"}
          tone={kpis.waiting_for_you ? "warn" : "ok"}
        />
      ) : null}
    </div>
  );
}

function SiteWeatherPanel({ sites, today }: { sites: SiteWeather[]; today: string }) {
  if (sites.length === 0) return null;
  return (
    <Sheet className="p-5">
      <SectionHeading annotation="saved each morning at 05:30">Weather on your sites</SectionHeading>
      <div className="space-y-5">
        {sites.map((site) => (
          <div key={site.site_code}>
            {sites.length > 1 ? (
              <p className="mb-2 text-sm font-medium text-ink">
                {site.site_name} <span className="font-mono text-xs font-normal text-ink-faint">{site.site_code}</span>
              </p>
            ) : null}
            <WeatherStrip weather={asWeather(site)} today={today} />
          </div>
        ))}
      </div>
    </Sheet>
  );
}

function WeeklyReportButton({ today }: { today: string }) {
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <Button
        disabled={state === "busy"}
        onClick={() => {
          setState("busy");
          downloadWeeklyReport(today).then(
            () => {
              setState("idle");
            },
            () => {
              setState("error");
            },
          );
        }}
      >
        <Icon name="download" className="size-4" />
        {state === "busy" ? "Preparing PDF…" : "Weekly report (PDF)"}
      </Button>
      {state === "error" ? (
        <p role="alert" className="text-xs text-signal-high">
          Could not prepare the report. Try again.
        </p>
      ) : null}
    </div>
  );
}

function PortfolioOverview() {
  const { can } = useAuth();
  const portfolio = usePortfolio();
  const projects = useProjects();
  const projectIds = useMemo(() => new Map((projects.data ?? []).map((p) => [p.code, p.id])), [projects.data]);
  const data = portfolio.data;
  const approver = APPROVER_PERMISSIONS.some((permission) => can(permission));

  return (
    <div className="space-y-6">
      <BriefingCard projectIds={projectIds} />
      {portfolio.isPending ? <p className="text-sm text-ink-faint">Loading the portfolio…</p> : null}
      {portfolio.isError ? <Alert tone="error">{errorText(portfolio.error)}</Alert> : null}
      {data ? (
        <>
          <DashboardKpis kpis={data.kpis} approver={approver} />
          {approver ? (
            <div className="grid gap-6 xl:grid-cols-2">
              <ApprovalQueue items={data.approvals} total={data.kpis.waiting_for_you} />
              <AlertsList />
            </div>
          ) : (
            <AlertsList />
          )}
          <SiteWeatherPanel sites={data.weather} today={data.as_of} />
          {can("risk:read") ? <RiskRankingPanel /> : null}
          {data.cost ? <CostAgainstPlan cost={data.cost} /> : null}
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <IssueTrend weeks={data.issue_trend} />
            {can("schedule:read") ? <ScheduleHealth /> : null}
          </div>
        </>
      ) : null}
    </div>
  );
}

function Reading({ label, tone, status, detail }: { label: string; tone: Tone; status: string; detail: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-3" role="group" aria-label={label}>
      <div>
        <p className="font-medium text-ink">{label}</p>
        <p className="text-sm text-ink-faint">{detail}</p>
      </div>
      <StatusBadge tone={tone} label={status} pulse={tone === "ok"} />
    </div>
  );
}

function errorNote(error: unknown): string {
  if (error instanceof ApiError) return error.requestId ? `Reference ${error.requestId.slice(0, 8)}` : error.code;
  return "Unknown error";
}

/** For the company admin: is the system healthy, and where are the admin tools. */
function SystemStatus() {
  const queryClient = useQueryClient();
  const health = useHealth();
  const readiness = useReadiness();
  const checking = useIsFetching({ queryKey: ["health"] }) > 0;
  const dbOk = readiness.data?.data.checks.database === "ok";

  const links: { to: string; label: string; icon: IconName; text: string }[] = [
    { to: "/admin/users", label: "Users", icon: "users", text: "Accounts, roles and site access" },
    { to: "/admin/sites", label: "Sites", icon: "sites", text: "Construction sites" },
    { to: "/admin/audit", label: "Audit log", icon: "audit", text: "Sign-ins and changes" },
  ];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Sheet className="p-5">
        <SectionHeading
          annotation="checked every 30 s"
          action={
            <Button
              disabled={checking}
              onClick={() => {
                void queryClient.invalidateQueries({ queryKey: ["health"] });
              }}
            >
              {checking ? "Checking…" : "Re-check now"}
            </Button>
          }
        >
          System status
        </SectionHeading>
        <div className="divide-y divide-rule">
          <Reading
            label="API"
            tone={health.isPending ? "idle" : health.isError ? "down" : "ok"}
            status={health.isPending ? "Checking" : health.isError ? "Offline" : "Online"}
            detail={
              health.data
                ? `Responded in ${String(health.data.latencyMs)} ms · v${health.data.data.version}`
                : health.isError
                  ? errorNote(health.error)
                  : "Contacting…"
            }
          />
          <Reading
            label="Database"
            tone={readiness.isPending ? "idle" : dbOk ? "ok" : "down"}
            status={readiness.isPending ? "Checking" : dbOk ? "Ready" : "Unavailable"}
            detail={dbOk && readiness.data ? `PostgreSQL · ${String(readiness.data.latencyMs)} ms` : "PostgreSQL"}
          />
        </div>
        <p className="mt-3 text-sm text-ink-soft" aria-live="polite">
          {health.isError
            ? "The API is not answering. Is the backend running? See “Run it locally” in the README."
            : readiness.isSuccess && !dbOk
              ? "The API is up but cannot reach PostgreSQL."
              : "All systems are working."}
        </p>
      </Sheet>
      <Sheet className="p-5">
        <SectionHeading>Administration</SectionHeading>
        <ul className="divide-y divide-rule">
          {links.map((l) => (
            <li key={l.to}>
              <Link to={l.to} className="group flex items-center gap-3 py-3">
                <span className="grid size-9 place-items-center rounded-lg bg-paper-sunk text-ink-soft group-hover:text-ink">
                  <Icon name={l.icon} />
                </span>
                <span className="flex-1">
                  <span className="block font-medium text-ink group-hover:underline">{l.label}</span>
                  <span className="block text-sm text-ink-faint">{l.text}</span>
                </span>
                <Icon name="chevron" className="size-4 text-ink-faint" />
              </Link>
            </li>
          ))}
        </ul>
      </Sheet>
    </div>
  );
}

export function DashboardPage() {
  const { user, can } = useAuth();
  const firstName = user?.full_name.split(" ")[0] ?? "";

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm text-ink-faint">{formatSiteDate(new Date())}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]">
            {greeting(new Date())}, {firstName}
          </h1>
          <p className="mt-1 text-ink-soft">
            {can("projects:read") ? "Here is what needs your attention today." : "Here is the state of SiteSense today."}
          </p>
        </div>
        {can("cost:read") ? <WeeklyReportButton today={siteTodayIso()} /> : null}
      </div>

      {can("projects:read") ? <PortfolioOverview /> : null}
      {can("reports:read") ? <TodayReports compact /> : null}
      {can("users:manage") ? <SystemStatus /> : null}
    </div>
  );
}

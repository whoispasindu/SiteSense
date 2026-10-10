import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ApiError } from "../../api/client";
import { useHealth, useReadiness } from "../../api/health";
import { useProjects } from "../../api/projects";
import { useRiskRanking } from "../../api/risk";
import { useScheduleSummary } from "../../api/schedule";
import { useAuth } from "../../auth/context";
import { Button } from "../../components/ui/Button";
import { Icon, type IconName } from "../../components/ui/icons";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";
import { KpiTile } from "../../features/projects/ProjectBits";
import { TodayReports } from "../../features/reports/TodayReports";
import { RiskRankingPanel } from "../../features/risk/RiskRankingPanel";
import { varianceLabel } from "../../features/schedule/variance";
import { formatCompactLKR, toNumber } from "../../lib/money";
import { formatSiteDate, greeting } from "../../lib/time";

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

function ValueChart({ data }: { data: { name: string; value: number }[] }) {
  return (
    <Sheet className="p-5">
      <SectionHeading annotation="LKR">Contract value by project</SectionHeading>
      <div role="img" aria-label={data.map((d) => `${d.name}: ${formatCompactLKR(d.value)}`).join("; ")} className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }} barCategoryGap={10}>
            <CartesianGrid horizontal={false} stroke="var(--color-rule)" />
            <XAxis
              type="number"
              tickFormatter={(v: number) => formatCompactLKR(v).replace("LKR ", "")}
              tick={{ fontSize: 12, fill: "var(--color-ink-faint)" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={140}
              tick={{ fontSize: 12, fill: "var(--color-ink-soft)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              cursor={{ fill: "var(--color-paper-sunk)" }}
              formatter={(v) => [formatCompactLKR(Number(v)), "Contract value"]}
              contentStyle={{
                background: "var(--color-paper-raised)",
                border: "1px solid var(--color-rule)",
                borderRadius: 8,
                fontSize: 13,
                color: "var(--color-ink)",
              }}
            />
            <Bar dataKey="value" fill="var(--color-accent-line)" radius={[0, 6, 6, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Sheet>
  );
}

function PortfolioOverview() {
  const { can } = useAuth();
  const projects = useProjects();
  const list = projects.data ?? [];
  const active = list.filter((p) => p.status === "active").length;
  // Contract values arrive only for roles that see rates (not site engineers).
  const priced = can("rates:read");
  const contract = list.reduce((sum, p) => sum + toNumber(p.contract_value ?? 0), 0);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-[repeat(auto-fit,minmax(11rem,1fr))]">
        <KpiTile icon="projects" label="Active projects" value={projects.isPending ? "—" : String(active)} note={`${String(list.length)} in total`} />
        {priced ? (
          <KpiTile icon="cost" label="Contract value" value={projects.isPending ? "—" : formatCompactLKR(contract)} note="All visible projects" />
        ) : null}
        {can("schedule:read") ? <ScheduleKpis /> : null}
        {can("risk:read") ? <HighRiskKpi /> : null}
      </div>

      {can("risk:read") ? <RiskRankingPanel /> : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {can("schedule:read") ? <ScheduleHealth /> : null}
        {priced && list.length > 0 ? (
          <ValueChart data={list.map((p) => ({ name: p.name, value: toNumber(p.contract_value ?? 0) }))} />
        ) : null}
      </div>
    </div>
  );
}

function HighRiskKpi() {
  const ranking = useRiskRanking();
  const high = (ranking.data ?? []).filter((r) => r.level === "high").length;
  return (
    <KpiTile
      icon="risk"
      label="High risk"
      value={ranking.isPending ? "—" : String(high)}
      note={high ? "Risk score 70 or more (BR-10)" : "No project is at high risk"}
      tone={high ? "down" : "ok"}
    />
  );
}

function ScheduleKpis() {
  const summary = useScheduleSummary();
  const scheduled = (summary.data ?? []).filter((s) => s.task_count > 0);
  const behind = scheduled.filter((s) => s.variance < -2).length;
  const average = (pick: (s: (typeof scheduled)[number]) => number) =>
    scheduled.length ? scheduled.reduce((sum, s) => sum + pick(s), 0) / scheduled.length : 0;

  return (
    <>
      <KpiTile
        icon="schedule"
        label="Average progress"
        value={scheduled.length ? `${average((s) => s.actual_percent).toFixed(1)}%` : "—"}
        note={scheduled.length ? `Planned ${average((s) => s.planned_percent).toFixed(1)}% by today` : "No programmes yet"}
      />
      <KpiTile
        icon="risk"
        label="Behind plan"
        value={summary.isPending ? "—" : String(behind)}
        note={behind ? "Projects more than 2 points behind" : "Every programme is on plan"}
        tone={behind ? "warn" : "ok"}
      />
    </>
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
      <div>
        <p className="text-sm text-ink-faint">{formatSiteDate(new Date())}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]">
          {greeting(new Date())}, {firstName}
        </h1>
        <p className="mt-1 text-ink-soft">
          {can("projects:read") ? "Here is how your projects stand today." : "Here is the state of SiteSense today."}
        </p>
      </div>

      {can("reports:read") ? <TodayReports compact /> : null}
      {can("projects:read") ? <PortfolioOverview /> : null}
      {can("users:manage") ? <SystemStatus /> : null}
    </div>
  );
}

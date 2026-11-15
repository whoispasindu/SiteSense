import { useState } from "react";
import { Link } from "react-router";

import { PROJECT_STATUSES, STATUS_LABELS, TYPE_LABELS, useProjects, type ProjectStatus } from "../../api/projects";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { ProgrammeBar, ProjectStatusBadge } from "../../features/projects/ProjectBits";
import { ProjectFormDialog } from "../../features/projects/ProjectFormDialog";
import { formatCompactMoney, percent } from "../../lib/money";

export function ProjectsPage() {
  const { can, user } = useAuth();
  const [status, setStatus] = useState<ProjectStatus | "">("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const projects = useProjects(status, query);
  const list = projects.data ?? [];

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <PageHeader
        title="Projects"
        description={
          user?.site_scoped
            ? "Projects on the sites you are assigned to."
            : "Every project the company is running, across all sites."
        }
        action={
          can("projects:manage") ? (
            <Button
              variant="primary"
              onClick={() => {
                setCreating(true);
              }}
            >
              New project
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <label className="min-w-0 flex-1 sm:max-w-xs">
          <span className="sr-only">Search projects</span>
          <input
            type="search"
            placeholder="Search name, code or client"
            value={query}
            maxLength={80}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            className="min-h-10 w-full rounded-lg border border-field-line bg-paper-raised px-3 text-sm text-ink placeholder:text-ink-faint focus:border-survey focus:ring-2 focus:ring-survey/25 focus:outline-none"
          />
        </label>
        <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
          {(["", ...PROJECT_STATUSES] as const).map((s) => (
            <button
              key={s || "all"}
              type="button"
              aria-pressed={status === s}
              onClick={() => {
                setStatus(s);
              }}
              className={`min-h-9 rounded-full border px-3 text-sm font-medium ${
                status === s ? "border-ink bg-ink text-paper" : "border-rule-strong text-ink-soft hover:border-ink"
              }`}
            >
              {s ? STATUS_LABELS[s] : "All"}
            </button>
          ))}
        </div>
      </div>

      {projects.isError ? <Alert tone="error">{errorText(projects.error)}</Alert> : null}

      {projects.isPending ? (
        <p className="py-10 text-center text-ink-faint">Loading projects…</p>
      ) : list.length === 0 ? (
        <Sheet className="px-6 py-14 text-center">
          <p className="text-lg font-semibold">No projects {status || query ? "match" : "yet"}</p>
          <p className="mt-2 text-ink-soft">
            {status || query
              ? "Try another filter or search."
              : can("projects:manage")
                ? "Create the first project on one of your sites."
                : "Projects will appear here once a project manager adds them to your sites."}
          </p>
        </Sheet>
      ) : (
        <ol aria-label="Projects" className="space-y-3">
          {list.map((p) => {
            const coverage = p.boq_total !== undefined && p.contract_value !== undefined ? percent(p.boq_total, p.contract_value) : null;
            return (
              <li key={p.id}>
                <Link
                  to={`/projects/${p.id}`}
                  className="group block rounded-[var(--radius-sheet)] border border-rule bg-paper-raised shadow-[var(--shadow-sheet)] transition hover:border-rule-strong hover:shadow-[var(--shadow-pop)] focus-visible:border-survey"
                >
                  <div className="grid gap-4 p-5 md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1.1fr)] md:items-center md:gap-8">
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-3">
                        <span className="font-mono text-xs font-medium text-ink-faint">{p.code}</span>
                        <ProjectStatusBadge status={p.status} />
                      </p>
                      <h2 className="mt-2 truncate text-base font-semibold text-ink group-hover:text-survey">
                        {p.name}
                      </h2>
                      <p className="mt-0.5 truncate text-sm text-ink-soft">
                        {p.client_name} · {TYPE_LABELS[p.project_type]} ·{" "}
                        <span>{p.site.code}</span>
                      </p>
                    </div>
                    <div>
                      {p.contract_value !== undefined ? (
                        <p className="tabular text-lg font-semibold text-ink">{formatCompactMoney(p.contract_value)}</p>
                      ) : null}
                      <p className="mt-0.5 text-xs text-ink-faint">
                        {p.item_count === 0
                          ? "No BOQ yet"
                          : coverage === null
                            ? `BOQ: ${String(p.item_count)} items`
                            : `BOQ ${String(p.item_count)} items · ${coverage.toFixed(1)}% of contract`}
                      </p>
                    </div>
                    <div>
                      <ProgrammeBar start={p.start_date} end={p.planned_end} />
                      <p className="tabular mt-2 flex justify-between text-xs text-ink-faint">
                        <span>{formatDate(p.start_date)}</span>
                        <span>{formatDate(p.planned_end)}</span>
                      </p>
                    </div>
                  </div>
                </Link>
              </li>
            );
          })}
        </ol>
      )}

      <ProjectFormDialog
        open={creating}
        onClose={() => {
          setCreating(false);
        }}
      />
    </div>
  );
}

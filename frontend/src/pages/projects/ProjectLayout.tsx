import { useState } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { TYPE_LABELS, useProject } from "../../api/projects";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { errorText } from "../../features/admin/adminUtils";
import { ProjectStatusBadge } from "../../features/projects/ProjectBits";
import { ProjectFormDialog } from "../../features/projects/ProjectFormDialog";
import { NotFoundPage } from "../NotFoundPage";

const TAB = "font-wide inline-flex min-h-11 items-center border-b-2 px-1 text-xs font-bold tracking-[0.14em] uppercase";

export function ProjectLayout() {
  const { projectId = "" } = useParams();
  const { can } = useAuth();
  const project = useProject(projectId);
  const [editing, setEditing] = useState(false);

  if (project.isPending) return <p className="py-16 text-center text-ink-faint">Loading project…</p>;
  if (project.isError) {
    // Unassigned and non-existent projects both answer 404: the page cannot tell them apart either.
    if (project.error instanceof ApiError && project.error.status === 404) return <NotFoundPage />;
    return <Alert tone="error">{errorText(project.error)}</Alert>;
  }
  const p = project.data;

  return (
    <div className="mx-auto max-w-6xl">
      <nav aria-label="Breadcrumb" className="font-mono text-xs text-ink-faint">
        <Link to="/projects" className="hover:text-ink hover:underline">
          Projects
        </Link>{" "}
        / {p.code}
      </nav>

      <header className="mt-4 flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <ProjectStatusBadge status={p.status} />
            <span className="font-mono text-xs text-ink-faint">
              {p.site.code} · {TYPE_LABELS[p.project_type]}
            </span>
          </div>
          <h1 className="font-wide mt-3 text-4xl leading-tight font-extrabold tracking-tight text-balance sm:text-5xl">
            {p.name}
          </h1>
          <p className="mt-2 text-ink-soft">{p.client_name}</p>
        </div>
        {can("projects:manage") ? (
          <Button
            onClick={() => {
              setEditing(true);
            }}
          >
            Edit project
          </Button>
        ) : null}
      </header>

      <nav aria-label="Project sections" className="mt-8 flex gap-8 border-b border-rule">
        <NavLink
          to={`/projects/${p.id}`}
          end
          className={({ isActive }) => `${TAB} ${isActive ? "border-ink text-ink" : "border-transparent text-ink-faint hover:text-ink"}`}
        >
          Overview
        </NavLink>
        <NavLink
          to={`/projects/${p.id}/boq`}
          className={({ isActive }) => `${TAB} ${isActive ? "border-ink text-ink" : "border-transparent text-ink-faint hover:text-ink"}`}
        >
          BOQ &amp; budget
        </NavLink>
        {can("schedule:read") ? (
          <NavLink
            to={`/projects/${p.id}/schedule`}
            className={({ isActive }) => `${TAB} ${isActive ? "border-ink text-ink" : "border-transparent text-ink-faint hover:text-ink"}`}
          >
            Schedule
          </NavLink>
        ) : null}
      </nav>

      <div className="mt-8">
        <Outlet context={p} />
      </div>

      {can("projects:manage") ? (
        <ProjectFormDialog
          key={p.updated_at}
          open={editing}
          project={p}
          onClose={() => {
            setEditing(false);
          }}
        />
      ) : null}
    </div>
  );
}

import { Link, Navigate, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { useClientProject, useClientProjects, type ClientProjectCard } from "../../api/portal";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Icon } from "../../components/ui/icons";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { errorText } from "../../features/admin/adminUtils";
import { asProgress } from "../../features/client/portal";
import { HandoverCard, MilestoneTrack, Payments, PhotoGallery } from "../../features/client/PortalBits";
import { formatDate } from "../../features/projects/dates";
import { SCurve } from "../../features/schedule/SCurve";
import { NotFoundPage } from "../NotFoundPage";

const STATUS_WORDS: Record<string, string> = {
  planning: "Getting ready",
  active: "Under construction",
  on_hold: "On hold",
  completed: "Completed",
};

function ProgressMeter({ planned, actual }: { planned: number; actual: number }) {
  return (
    <div aria-hidden="true" className="relative mt-3 h-2.5 overflow-hidden rounded-full bg-paper-sunk">
      <div className="absolute inset-y-0 left-0 rounded-full bg-rule-strong" style={{ width: `${String(Math.min(planned, 100))}%` }} />
      <div className="absolute inset-y-0 left-0 rounded-full bg-accent-line" style={{ width: `${String(Math.min(actual, 100))}%` }} />
    </div>
  );
}

function ProjectCard({ card }: { card: ClientProjectCard }) {
  return (
    <Link
      to={`/client/projects/${card.id}`}
      className="group block rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-5 shadow-[var(--shadow-sheet)] transition-colors hover:border-rule-strong"
    >
      <p className="text-xs text-ink-faint">
        {card.location} · {STATUS_WORDS[card.status] ?? card.status}
      </p>
      <p className="mt-1 text-lg font-semibold tracking-tight text-ink group-hover:underline">{card.name}</p>
      <p className="tabular mt-3 text-sm text-ink-soft">
        <span className="text-2xl font-semibold text-ink">{card.actual_percent.toFixed(0)}%</span> built · planned{" "}
        {card.planned_percent.toFixed(0)}% by today
      </p>
      <ProgressMeter planned={card.planned_percent} actual={card.actual_percent} />
      <p className="mt-4 text-sm text-ink-soft">
        {card.handover_published ? "Expected handover" : "Contract handover"}{" "}
        <span className="tabular font-medium text-ink">{formatDate(card.handover_date)}</span>
      </p>
      {card.variations_waiting ? (
        <p className="mt-2 text-sm font-medium text-signal-medium">
          {card.variations_waiting} variation{card.variations_waiting === 1 ? "" : "s"} waiting for your decision
        </p>
      ) : null}
    </Link>
  );
}

/** The client's home: their projects. With just one, it opens straight away. */
export function ClientHomePage() {
  const { user } = useAuth();
  const projects = useClientProjects();
  if (projects.isPending) return <p className="py-16 text-center text-ink-faint">Loading your projects…</p>;
  if (projects.isError) return <Alert tone="error">{errorText(projects.error)}</Alert>;
  if (projects.data.length === 1 && projects.data[0]) return <Navigate to={`/client/projects/${projects.data[0].id}`} replace />;

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-ink-faint">Welcome, {user?.full_name}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]">Your projects</h1>
      </div>
      {projects.data.length === 0 ? (
        <Sheet className="p-8 text-center text-ink-soft">No projects are linked to your account yet.</Sheet>
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          {projects.data.map((card) => (
            <ProjectCard key={card.id} card={card} />
          ))}
        </div>
      )}
    </div>
  );
}

/** One project, as the client sees it: progress, the handover date, milestones, photos and payments. */
export function ClientProjectPage() {
  const { projectId = "" } = useParams();
  const project = useClientProject(projectId);
  if (project.isPending) return <p className="py-16 text-center text-ink-faint">Loading the project…</p>;
  if (project.isError) {
    if (project.error instanceof ApiError && project.error.status === 404) return <NotFoundPage />;
    return <Alert tone="error">{errorText(project.error)}</Alert>;
  }
  const p = project.data;
  const behind = p.actual_percent < p.planned_percent - 2;

  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm text-ink-faint">
          <Link to="/" className="hover:text-ink hover:underline">
            Your projects
          </Link>{" "}
          · {p.location} · <span className="font-mono">{p.code}</span>
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink sm:text-[1.75rem]">{p.name}</h1>
        <p className="mt-1 text-ink-soft">{STATUS_WORDS[p.status] ?? p.status}</p>
      </header>

      {p.variations_waiting ? (
        <Link
          to="/client/variations"
          className="flex items-center justify-between gap-3 rounded-lg border border-signal-medium/40 bg-signal-medium-tint px-4 py-3 text-sm font-medium text-signal-medium hover:underline"
        >
          <span>
            {p.variations_waiting} variation{p.variations_waiting === 1 ? " is" : "s are"} waiting for your decision
          </span>
          <Icon name="chevron" className="size-4" />
        </Link>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Sheet className="p-5">
          <SectionHeading annotation={`as of ${formatDate(asProgress(p).as_of)}`}>Progress</SectionHeading>
          <p className="tabular text-sm text-ink-soft">
            <span className="text-[2rem] leading-none font-semibold tracking-tight text-ink">{p.actual_percent.toFixed(1)}%</span> built,
            against {p.planned_percent.toFixed(1)}% planned by today
            {behind ? <span className="text-signal-medium"> ({(p.planned_percent - p.actual_percent).toFixed(1)} points behind)</span> : null}
          </p>
          <ProgressMeter planned={p.planned_percent} actual={p.actual_percent} />
          {p.progress.length > 1 ? (
            <div className="mt-5">
              <SCurve progress={asProgress(p)} />
            </div>
          ) : null}
        </Sheet>
        <div className="space-y-6">
          <HandoverCard project={p} />
          <MilestoneTrack milestones={p.milestones} />
        </div>
      </div>

      <PhotoGallery photos={p.photos} />
      <Payments projectId={p.id} />
    </div>
  );
}

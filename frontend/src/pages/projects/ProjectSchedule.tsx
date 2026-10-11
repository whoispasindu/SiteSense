import { useState } from "react";

import { useNetwork, useProgress, useTasks, type Task } from "../../api/schedule";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";
import { StopWorkBanner } from "../../features/reports/StopWorkBanner";
import { formatDate } from "../../features/projects/dates";
import { KpiTile } from "../../features/projects/ProjectBits";
import { SCurve } from "../../features/schedule/SCurve";
import { TaskFormDialog } from "../../features/schedule/TaskFormDialog";
import { TaskTable } from "../../features/schedule/TaskTable";
import { Gantt } from "../../features/schedule/Gantt";
import { slipText } from "../../features/schedule/network";
import { varianceLabel } from "../../features/schedule/variance";
import { useCurrentProject } from "./projectContext";

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** "123456" -> "Mon–Sat"; anything else is listed. */
function weekText(week: string): string {
  if (week === "123456") return "Mon–Sat";
  if (week === "12345") return "Mon–Fri";
  return week
    .split("")
    .map((d) => DAY_NAMES[Number(d) - 1] ?? d)
    .join(", ");
}

export function ProjectSchedule() {
  const project = useCurrentProject();
  const { can } = useAuth();
  const tasks = useTasks(project.id);
  const progress = useProgress(project.id);
  const network = useNetwork(project.id);
  const [editing, setEditing] = useState<Task | "new" | null>(null);
  const canManage = can("schedule:manage");

  if (tasks.isPending || progress.isPending) return <p className="py-10 text-center text-ink-faint">Loading programme…</p>;
  if (tasks.isError) return <Alert tone="error">{errorText(tasks.error)}</Alert>;
  if (progress.isError) return <Alert tone="error">{errorText(progress.error)}</Alert>;

  const p = progress.data;
  const list = tasks.data.tasks;
  const weightTotal = Number(tasks.data.weight_total);
  const variance = varianceLabel(p.variance);
  const net = network.data;

  return (
    <div className="space-y-10">
      {can("reports:read") ? <StopWorkBanner projectId={project.id} /> : null}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile icon="schedule" label="Planned today" value={`${p.planned_percent.toFixed(1)}%`} note={`As of ${formatDate(p.as_of)}`} />
        <KpiTile icon="reports" label="Actual" value={`${p.actual_percent.toFixed(1)}%`} note="Weighted by task share of the contract" />
        <div className="relative rounded-[var(--radius-sheet)] border border-rule bg-paper-raised p-5 shadow-[var(--shadow-sheet)]">
          <p className="text-sm font-medium text-ink-soft">Variance</p>
          <p className="tabular mt-2 text-[1.75rem] leading-tight font-semibold tracking-tight text-ink">
            {p.variance > 0 ? "+" : ""}
            {p.variance.toFixed(1)} pts
          </p>
          <p className="mt-2">
            <StatusBadge tone={variance.tone} label={variance.label} />
          </p>
        </div>
        <KpiTile
          icon="schedule"
          label="Forecast handover"
          value={net?.forecast_end ? formatDate(net.forecast_end) : "—"}
          tone={net && net.slip_days > 0 ? "down" : "idle"}
          note={net ? `${slipText(net.slip_days)} against ${formatDate(net.planned_end)}` : `Contract end ${formatDate(p.contract_end)}`}
        />
      </div>

      {list.length > 0 && Math.abs(weightTotal - 100) > 0.01 ? (
        <Alert tone="warn" title={`Task weights add up to ${weightTotal.toFixed(2)}%, not 100%`}>
          Progress is still scaled to 100%, but adjust the weights so each task's share of the contract is right.
        </Alert>
      ) : null}

      <section aria-labelledby="curve-heading">
        <SectionHeading id="curve-heading" annotation="planned vs actual">
          S-curve
        </SectionHeading>
        <Sheet className="p-4 sm:p-6">
          {list.length === 0 ? (
            <p className="py-10 text-center text-ink-soft">Add tasks with dates and weights to draw the planned curve.</p>
          ) : (
            <SCurve progress={p} />
          )}
        </Sheet>
      </section>

      {net?.warnings.map((w) => (
        <Alert key={w} tone="warn">
          {w}
        </Alert>
      ))}
      {network.isError ? <Alert tone="error">{errorText(network.error)}</Alert> : null}

      {list.length > 0 && net ? (
        <section aria-labelledby="timeline-heading">
          <SectionHeading
            id="timeline-heading"
            annotation={`critical path on the forecast; working days, ${weekText(net.working_week)}`}
          >
            Programme
          </SectionHeading>
          <Sheet className="p-4 sm:p-6">
            <Gantt network={net} />
          </Sheet>
        </section>
      ) : null}

      <section aria-labelledby="tasks-heading">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0 flex-1">
            <SectionHeading id="tasks-heading" annotation={`weights ${weightTotal.toFixed(2)}%`}>
              Tasks
            </SectionHeading>
          </div>
        </div>
        {canManage ? (
          <div className="mb-4">
            <Button
              variant="primary"
              onClick={() => {
                setEditing("new");
              }}
            >
              Add task
            </Button>
          </div>
        ) : null}
        <Sheet>
          {list.length === 0 ? (
            <p className="px-6 py-10 text-center text-ink-soft">
              {canManage ? "No tasks yet. Add the first one." : "The project manager has not added tasks yet."}
            </p>
          ) : (
            <TaskTable
              tasks={list}
              projectId={project.id}
              canManage={canManage}
              canReportProgress={can("schedule:progress")}
              onEdit={setEditing}
            />
          )}
        </Sheet>
      </section>

      {editing !== null ? (
        <TaskFormDialog
          key={editing === "new" ? "new" : editing.id}
          open
          project={project}
          task={editing === "new" ? undefined : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

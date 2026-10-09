import { useState } from "react";

import { useProgress, useTasks, type Task } from "../../api/schedule";
import { useAuth } from "../../auth/context";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { errorText } from "../../features/admin/adminUtils";
import { formatDate } from "../../features/projects/dates";
import { KpiTile } from "../../features/projects/ProjectBits";
import { SCurve } from "../../features/schedule/SCurve";
import { TaskFormDialog } from "../../features/schedule/TaskFormDialog";
import { TaskTable } from "../../features/schedule/TaskTable";
import { TaskTimeline } from "../../features/schedule/TaskTimeline";
import { varianceLabel } from "../../features/schedule/variance";
import { useCurrentProject } from "./projectContext";

export function ProjectSchedule() {
  const project = useCurrentProject();
  const { can } = useAuth();
  const tasks = useTasks(project.id);
  const progress = useProgress(project.id);
  const [editing, setEditing] = useState<Task | "new" | null>(null);
  const canManage = can("schedule:manage");

  if (tasks.isPending || progress.isPending) return <p className="py-10 text-center text-ink-faint">Loading programme…</p>;
  if (tasks.isError) return <Alert tone="error">{errorText(tasks.error)}</Alert>;
  if (progress.isError) return <Alert tone="error">{errorText(progress.error)}</Alert>;

  const p = progress.data;
  const list = tasks.data.tasks;
  const weightTotal = Number(tasks.data.weight_total);
  const variance = varianceLabel(p.variance);
  const overruns = p.programme_end > p.contract_end;

  return (
    <div className="space-y-10">
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
          label="Programme end"
          value={formatDate(p.programme_end)}
          note={overruns ? `Past the contract end (${formatDate(p.contract_end)})` : `Contract end ${formatDate(p.contract_end)}`}
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

      {list.length > 0 ? (
        <section aria-labelledby="timeline-heading">
          <SectionHeading id="timeline-heading" annotation={`${String(list.length)} tasks`}>
            Programme
          </SectionHeading>
          <Sheet className="p-4 sm:p-6">
            <TaskTimeline tasks={list} start={p.programme_start} end={p.programme_end} today={p.as_of} />
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

import { useState, type SubmitEvent } from "react";

import { useDeleteTask, useUpdateTask, type Task, type TaskState } from "../../api/schedule";
import { Button } from "../../components/ui/Button";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";
import { errorText } from "../admin/adminUtils";
import { formatDate } from "../projects/dates";

const STATE: Record<TaskState, { tone: Tone; label: string }> = {
  not_started: { tone: "idle", label: "Not started" },
  on_track: { tone: "ok", label: "On track" },
  behind: { tone: "warn", label: "Behind" },
  done: { tone: "ok", label: "Done" },
};

function ProgressCell({ task, projectId, editable }: { task: Task; projectId: string; editable: boolean }) {
  const update = useUpdateTask(projectId);
  const [value, setValue] = useState(String(Number(task.percent_complete)));
  const dirty = Number(value) !== Number(task.percent_complete);
  const valid = /^\d{1,3}(\.\d{1,2})?$/.test(value) && Number(value) <= 100;

  if (!editable) {
    return <span className="tabular">{Number(task.percent_complete)}%</span>;
  }

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (valid && dirty) update.mutate({ id: task.id, percent_complete: value });
  }

  return (
    <form onSubmit={onSubmit} className="flex items-center justify-end gap-1.5">
      <label htmlFor={`pct-${task.id}`} className="sr-only">
        Percent complete for {task.name}
      </label>
      <input
        id={`pct-${task.id}`}
        type="number"
        min={0}
        max={100}
        step="any"
        value={value}
        aria-invalid={!valid}
        onChange={(e) => {
          setValue(e.target.value);
        }}
        className="tabular min-h-9 w-20 rounded-lg border border-field-line bg-paper-raised px-2 text-right text-sm text-ink focus:border-survey focus:ring-2 focus:ring-survey/25 focus:outline-none aria-[invalid=true]:border-signal-high"
      />
      <span className="text-xs text-ink-faint">%</span>
      {dirty ? (
        <Button type="submit" variant="primary" disabled={!valid || update.isPending} className="min-h-9 px-3">
          Save
        </Button>
      ) : null}
      {update.isError ? <span className="sr-only" role="alert">{errorText(update.error)}</span> : null}
    </form>
  );
}

interface TaskTableProps {
  tasks: Task[];
  projectId: string;
  canManage: boolean;
  canReportProgress: boolean;
  onEdit: (task: Task) => void;
}

export function TaskTable({ tasks, projectId, canManage, canReportProgress, onEdit }: TaskTableProps) {
  const remove = useDeleteTask(projectId);
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <div className="relative overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Programme tasks</caption>
        <thead className="border-b border-rule bg-paper-sunk/60 text-xs font-medium whitespace-nowrap text-ink-faint">
          <tr>
            <th scope="col" className="px-4 py-2.5 text-left font-medium">Task</th>
            <th scope="col" className="hidden px-4 py-2.5 text-left font-medium md:table-cell">Planned</th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">Weight</th>
            <th scope="col" className="hidden px-4 py-2.5 text-right font-medium sm:table-cell">Plan today</th>
            <th scope="col" className="px-4 py-2.5 text-right font-medium">Done</th>
            <th scope="col" className="px-4 py-2.5 text-left font-medium">Status</th>
            {canManage ? (
              <th scope="col" className="px-4 py-2.5 font-medium">
                <span className="sr-only">Actions</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {tasks.map((task) => (
            <tr key={task.id}>
              <th scope="row" className="px-4 py-3 text-left font-normal">
                <span className="flex items-center gap-2">
                  {task.code ? <span className="font-mono text-xs text-ink-faint">{task.code}</span> : null}
                  <span className="font-medium text-ink">{task.name}</span>
                  {task.is_critical ? (
                    <span className="rounded-full bg-signal-high-tint px-2 py-0.5 text-xs font-medium text-signal-high">
                      Critical
                    </span>
                  ) : null}
                </span>
                {task.boq_section_code ? <span className="text-xs text-ink-faint">BOQ section {task.boq_section_code}</span> : null}
              </th>
              <td className="tabular hidden px-4 py-3 whitespace-nowrap text-ink-soft md:table-cell">
                {formatDate(task.planned_start)} → {formatDate(task.planned_end)}
              </td>
              <td className="tabular px-4 py-3 text-right">{Number(task.weight)}%</td>
              <td className="tabular hidden px-4 py-3 text-right text-ink-soft sm:table-cell">{task.planned_percent_today}%</td>
              <td className="px-4 py-3 text-right">
                <ProgressCell key={task.percent_complete} task={task} projectId={projectId} editable={canReportProgress} />
              </td>
              <td className="px-4 py-3">
                <StatusBadge tone={STATE[task.state].tone} label={STATE[task.state].label} />
              </td>
              {canManage ? (
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {confirming === task.id ? (
                    <span className="inline-flex items-center gap-2">
                      <span className="text-xs text-signal-high">Delete?</span>
                      <Button
                        variant="primary"
                        className="min-h-9 px-3"
                        disabled={remove.isPending}
                        onClick={() => {
                          remove.mutate(task.id, {
                            onSettled: () => {
                              setConfirming(null);
                            },
                          });
                        }}
                      >
                        Yes
                      </Button>
                      <Button
                        className="min-h-9 px-3"
                        onClick={() => {
                          setConfirming(null);
                        }}
                      >
                        No
                      </Button>
                    </span>
                  ) : (
                    <span className="inline-flex gap-1">
                      <Button
                        variant="ghost"
                        className="min-h-9 px-2"
                        aria-label={`Edit ${task.name}`}
                        onClick={() => {
                          onEdit(task);
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        className="min-h-9 px-2 text-signal-high"
                        aria-label={`Delete ${task.name}`}
                        onClick={() => {
                          setConfirming(task.id);
                        }}
                      >
                        Delete
                      </Button>
                    </span>
                  )}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

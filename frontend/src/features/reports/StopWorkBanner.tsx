import { useState } from "react";
import { Link } from "react-router";

import { useCloseAction, useProjectActions, useSetStopScope, type ReportAction } from "../../api/issues";
import { useTasks, type Task } from "../../api/schedule";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { errorText } from "../admin/adminUtils";
import { stopScopeValid, type StopScopeValue } from "./stopScope";
import { StopScopeFields } from "./StopScopeFields";

function stopsText(flag: ReportAction, tasks: Task[]): string {
  if (flag.stop_scope === "project") return "Stops the whole project.";
  const names = tasks.filter((t) => flag.stop_task_ids.includes(t.id)).map((t) => t.code ?? t.name);
  return names.length > 0 ? `Stops ${names.join(", ")}.` : "Stops the chosen tasks.";
}

function ScopeDialog({ flag, tasks, onClose }: { flag: ReportAction; tasks: Task[]; onClose: () => void }) {
  const save = useSetStopScope();
  const [value, setValue] = useState<StopScopeValue>({ scope: flag.stop_scope ?? "project", taskIds: flag.stop_task_ids });
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-soft">“{flag.summary}”</p>
      <StopScopeFields tasks={tasks} value={value} onChange={setValue} idPrefix={`edit-${flag.id}`} />
      {save.isError ? <Alert tone="error">{errorText(save.error)}</Alert> : null}
      <div className="flex justify-end gap-3">
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="primary"
          disabled={!stopScopeValid(value) || save.isPending}
          onClick={() => {
            save.mutate(
              { id: flag.id, scope: value.scope, task_ids: value.scope === "tasks" ? value.taskIds : [] },
              { onSuccess: onClose },
            );
          }}
        >
          Save
        </Button>
      </div>
    </div>
  );
}

/**
 * Open stop-work flags on the project (BR-11): what each stops, until the project manager clears it.
 * Stopped tasks take no progress, and their forecast moves later by each stopped working day.
 */
export function StopWorkBanner({ projectId }: { projectId: string }) {
  const actions = useProjectActions(projectId);
  const tasks = useTasks(projectId);
  const close = useCloseAction();
  const [editing, setEditing] = useState<ReportAction | null>(null);
  const flags = (actions.data ?? []).filter((a) => a.kind === "stop_work");
  const programme = tasks.data?.tasks ?? [];
  if (flags.length === 0) return null;
  return (
    <Alert tone="error" title={flags.length === 1 ? "Stop-work flagged" : `${String(flags.length)} stop-work flags`}>
      <ul className="space-y-2">
        {flags.map((flag) => (
          <li key={flag.id} className="flex flex-wrap items-center justify-between gap-2">
            <span>
              “{flag.summary}” <span className="font-medium">{stopsText(flag, programme)}</span>{" "}
              <Link to={`/reports/${flag.report_id}`} className="font-medium underline">
                See the report
              </Link>
            </span>
            {flag.can_close ? (
              <span className="flex flex-wrap gap-2">
                {flag.can_edit_scope ? (
                  <Button
                    onClick={() => {
                      setEditing(flag);
                    }}
                  >
                    Change what it stops
                  </Button>
                ) : null}
                <Button
                  variant="danger"
                  disabled={close.isPending}
                  onClick={() => {
                    close.mutate({ id: flag.id, resolution: "done" });
                  }}
                >
                  Clear stop-work
                </Button>
              </span>
            ) : (
              <span className="text-xs">Only the project manager can clear it.</span>
            )}
          </li>
        ))}
      </ul>
      <Dialog
        open={editing !== null}
        title="What does this stop-work stop?"
        onClose={() => {
          setEditing(null);
        }}
      >
        {editing ? (
          <ScopeDialog
            key={editing.id}
            flag={editing}
            tasks={programme}
            onClose={() => {
              setEditing(null);
            }}
          />
        ) : null}
      </Dialog>
    </Alert>
  );
}

import { useState } from "react";

import { useAddDependency, useNetwork, useRemoveDependency, useTasks, type Task } from "../../api/schedule";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { errorText } from "../admin/adminUtils";

function label(t: Pick<Task, "code" | "name">): string {
  return t.code ? `${t.code} ${t.name}` : t.name;
}

/**
 * "Starts after": the task's finish-to-start predecessors, each with an optional lag in working days.
 * Changes save at once. A link that would make a loop is refused by the server, with the reason.
 */
export function DependencyEditor({ projectId, task }: { projectId: string; task: Task }) {
  const tasks = useTasks(projectId);
  const network = useNetwork(projectId);
  const add = useAddDependency(projectId);
  const remove = useRemoveDependency(projectId);
  const [predecessor, setPredecessor] = useState("");
  const [lag, setLag] = useState("0");

  const all = tasks.data?.tasks ?? [];
  const byId = new Map(all.map((t) => [t.id, t]));
  const links = (network.data?.dependencies ?? []).filter((d) => d.successor_id === task.id);
  const linked = new Set(links.map((d) => d.predecessor_id));
  const options = all.filter((t) => t.id !== task.id && !linked.has(t.id));
  const lagValid = /^\d{1,3}$/.test(lag) && Number(lag) <= 365;
  const error = add.error ?? remove.error;

  return (
    <section aria-labelledby={`deps-${task.id}`} className="space-y-3 border-t border-rule pt-4">
      <div>
        <h3 id={`deps-${task.id}`} className="text-sm font-semibold text-ink">
          Starts after
        </h3>
        <p className="text-xs text-ink-faint">
          It starts the working day after each of these finishes (plus any lag). This sets the critical path.
        </p>
      </div>
      {links.length === 0 ? (
        <p className="text-sm text-ink-soft">No predecessors: it can start on its planned start.</p>
      ) : (
        <ul className="space-y-1.5" aria-label="Predecessors">
          {links.map((d) => {
            const before = byId.get(d.predecessor_id);
            return (
              <li key={d.id} className="flex items-center justify-between gap-3 rounded-md bg-paper-sunk px-3 py-1.5 text-sm">
                <span>
                  {before ? label(before) : "A task"}
                  {d.lag_days > 0 ? <span className="text-ink-faint"> + {d.lag_days} working days</span> : null}
                </span>
                <Button
                  variant="ghost"
                  disabled={remove.isPending}
                  aria-label={`Remove the link to ${before ? label(before) : "this task"}`}
                  onClick={() => {
                    remove.mutate(d.id);
                  }}
                >
                  Remove
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1 text-sm">
          <span className="mb-1 block font-medium text-ink">Add a predecessor</span>
          <select
            value={predecessor}
            onChange={(e) => {
              setPredecessor(e.target.value);
            }}
            className="w-full rounded-md border border-rule-strong bg-paper px-3 py-2 text-ink"
          >
            <option value="">Choose a task…</option>
            {options.map((t) => (
              <option key={t.id} value={t.id}>
                {label(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="w-28 text-sm">
          <span className="mb-1 block font-medium text-ink">Lag (days)</span>
          <input
            value={lag}
            inputMode="numeric"
            aria-invalid={!lagValid}
            onChange={(e) => {
              setLag(e.target.value);
            }}
            className="tabular w-full rounded-md border border-rule-strong bg-paper px-3 py-2 text-ink"
          />
        </label>
        <Button
          disabled={!predecessor || !lagValid || add.isPending}
          onClick={() => {
            add.mutate(
              { predecessor_id: predecessor, successor_id: task.id, lag_days: Number(lag) },
              {
                onSuccess: () => {
                  setPredecessor("");
                  setLag("0");
                },
              },
            );
          }}
        >
          Add link
        </Button>
      </div>
      {error ? <Alert tone="error">{errorText(error)}</Alert> : null}
    </section>
  );
}

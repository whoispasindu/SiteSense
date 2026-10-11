import type { Task } from "../../api/schedule";
import type { StopScopeValue } from "./stopScope";

/**
 * BR-11: what a stop-work flag stops: chosen tasks, or the whole project for serious cases. Stopped
 * tasks take no progress until the project manager clears the flag, and their forecast keeps moving
 * later by each stopped working day.
 */
export function StopScopeFields({
  tasks,
  value,
  onChange,
  idPrefix,
}: {
  tasks: Task[];
  value: StopScopeValue;
  onChange: (next: StopScopeValue) => void;
  idPrefix: string;
}) {
  const chosen = new Set(value.taskIds);
  return (
    <fieldset className="space-y-2 rounded-lg border border-signal-high/40 bg-signal-high-tint/30 p-3">
      <legend className="px-1 text-sm font-semibold text-ink">What does it stop?</legend>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="radio"
          name={`${idPrefix}-scope`}
          checked={value.scope === "tasks"}
          onChange={() => {
            onChange({ ...value, scope: "tasks" });
          }}
          className="size-4 accent-[var(--color-survey)]"
        />
        Chosen tasks
      </label>
      {value.scope === "tasks" ? (
        tasks.length === 0 ? (
          <p className="pl-6 text-sm text-ink-faint">This project has no programme tasks: stop the whole project instead.</p>
        ) : (
          <ul className="max-h-48 space-y-1 overflow-y-auto pl-6" aria-label="Tasks to stop">
            {tasks.map((t) => (
              <li key={t.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={chosen.has(t.id)}
                    onChange={(e) => {
                      const next = new Set(chosen);
                      if (e.target.checked) next.add(t.id);
                      else next.delete(t.id);
                      onChange({ ...value, taskIds: tasks.filter((x) => next.has(x.id)).map((x) => x.id) });
                    }}
                    className="size-4 accent-[var(--color-survey)]"
                  />
                  <span>
                    {t.code ? <span className="mr-1.5 font-mono text-xs text-ink-faint">{t.code}</span> : null}
                    {t.name}
                    <span className="ml-1.5 text-xs text-ink-faint">{Number(t.percent_complete)}%</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )
      ) : null}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="radio"
          name={`${idPrefix}-scope`}
          checked={value.scope === "project"}
          onChange={() => {
            onChange({ ...value, scope: "project" });
          }}
          className="size-4 accent-[var(--color-survey)]"
        />
        The whole project (serious cases)
      </label>
      {value.scope === "tasks" && value.taskIds.length === 0 && tasks.length > 0 ? (
        <p className="text-xs text-signal-high">Choose at least one task, or stop the whole project.</p>
      ) : null}
    </fieldset>
  );
}

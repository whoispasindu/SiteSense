import type { StopScope } from "../../api/issues";
import type { Task } from "../../api/schedule";

export interface StopScopeValue {
  scope: StopScope;
  taskIds: string[];
}

/** Tasks under way (started, not finished): what a stop-work most often stops. */
export function tasksInProgress(tasks: Task[]): string[] {
  return tasks.filter((t) => Number(t.percent_complete) > 0 && Number(t.percent_complete) < 100).map((t) => t.id);
}

export function stopScopeValid(value: StopScopeValue): boolean {
  return value.scope === "project" || value.taskIds.length > 0;
}

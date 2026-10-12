import type { ClientProject, MilestoneStatus } from "../../api/portal";
import type { Progress, Task } from "../../api/schedule";
import type { Tone } from "../../components/ui/StatusBadge";
import { siteTodayIso } from "../../lib/time";

/** Words first, colour second: every milestone status reads on its own. */
export const MILESTONE_LABELS: Record<MilestoneStatus, string> = {
  done: "Done",
  on_track: "On track",
  late: "Running late",
  not_started: "Not started",
};

export const MILESTONE_TONES: Record<MilestoneStatus, Tone> = {
  done: "ok",
  on_track: "idle",
  late: "warn",
  not_started: "idle",
};

/** The client's progress points in the shape the S-curve draws (contract end and today marked). */
export function asProgress(project: ClientProject): Progress {
  const points = project.progress;
  return {
    as_of: siteTodayIso(),
    planned_percent: project.planned_percent,
    actual_percent: project.actual_percent,
    variance: Math.round((project.actual_percent - project.planned_percent) * 100) / 100,
    weight_total: "100.00",
    task_count: points.length,
    programme_start: points[0]?.date ?? project.start_date,
    programme_end: points.at(-1)?.date ?? project.handover.contract_end,
    contract_end: project.handover.contract_end,
    points,
  };
}

/** Whole days between two ISO dates (positive when ``later`` is later). */
export function daysBetween(earlier: string, later: string): number {
  return Math.round((Date.parse(`${later}T00:00:00Z`) - Date.parse(`${earlier}T00:00:00Z`)) / 86_400_000);
}

/** "3 weeks after the contract date", "on the contract date", "5 days before the contract date". */
export function againstContract(published: string, contract: string): string {
  const days = daysBetween(contract, published);
  if (days === 0) return "on the contract date";
  const size = Math.abs(days);
  const span = size >= 14 ? `${String(Math.round(size / 7))} weeks` : `${String(size)} day${size === 1 ? "" : "s"}`;
  return `${span} ${days > 0 ? "after" : "before"} the contract date`;
}

/** Milestones a client recognises; the PM maps each to a task. Keywords guess the task. */
export const SUGGESTED_MILESTONES: { name: string; keywords: string[] }[] = [
  { name: "Foundations complete", keywords: ["foundation", "piling", "pile", "substructure", "basement"] },
  { name: "Structure complete", keywords: ["frame", "structure", "superstructure", "slab"] },
  { name: "Roof complete", keywords: ["roof"] },
  { name: "Finishes complete", keywords: ["finish", "joinery", "painting"] },
  { name: "Handover", keywords: ["handover", "completion", "external works", "snagging"] },
];

/** The task that most likely ends the stage: the last-finishing task whose name has a keyword. */
export function guessTask(tasks: Task[], keywords: string[]): Task | undefined {
  const matches = tasks.filter((t) => keywords.some((k) => t.name.toLowerCase().includes(k)));
  return matches.sort((a, b) => b.planned_end.localeCompare(a.planned_end))[0];
}

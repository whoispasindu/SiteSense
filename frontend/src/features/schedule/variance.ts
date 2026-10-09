import type { Tone } from "../../components/ui/StatusBadge";

/** Within this many percentage points of plan counts as "on plan". */
export const ON_PLAN_POINTS = 2;
/** Further behind than this is shown as a serious slip. */
export const SERIOUS_POINTS = 10;

export function varianceLabel(variance: number): { tone: Tone; label: string } {
  const points = Math.abs(variance).toFixed(1);
  if (Math.abs(variance) <= ON_PLAN_POINTS) return { tone: "ok", label: "On plan" };
  if (variance > 0) return { tone: "ok", label: `Ahead ${points} pts` };
  return { tone: variance < -SERIOUS_POINTS ? "down" : "warn", label: `Behind ${points} pts` };
}

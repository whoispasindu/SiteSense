import type { Risk } from "../../api/risk";
import { addDaysIso } from "../../lib/time";

/** "on time", "3 working days late", "1 working day early" (Phase 9 slip, in working days). */
export function slipText(days: number): string {
  if (days === 0) return "on time";
  const n = Math.abs(days);
  return `${String(n)} working day${n === 1 ? "" : "s"} ${days > 0 ? "late" : "early"}`;
}

/** The risk model's likely handover window: the planned end plus the low and high delay forecasts. */
export function modelWindow(plannedEnd: string, risk: Risk | null | undefined): { from: string; to: string } | null {
  if (!risk?.ranges) return null;
  const { low, high } = risk.ranges.delay_days;
  return { from: addDaysIso(plannedEnd, Math.round(low)), to: addDaysIso(plannedEnd, Math.round(high)) };
}

/** When the two methods disagree, that is the signal worth reading. */
export function disagreement(atCurrentRates: string, span: { from: string; to: string }): string | null {
  if (atCurrentRates < span.from) return "The risk model expects a later finish than the current pace suggests.";
  if (atCurrentRates > span.to) return "The current pace points to a later finish than the risk model expects.";
  return null;
}

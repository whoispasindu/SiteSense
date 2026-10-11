import type { Driver, Range, RiskLevel } from "../../api/risk";
import type { Tone } from "../../components/ui/StatusBadge";

/** BR-10 bands in words: colour is never the only signal. */
export const LEVEL_LABELS: Record<RiskLevel, string> = { low: "Low", medium: "Medium", high: "High" };
export const LEVEL_TONES: Record<RiskLevel, Tone> = { low: "ok", medium: "warn", high: "down" };

/** "about 72 days late", "on time", "about 5 days early". Forecasts are estimates, so they are rounded. */
export function delayText(days: string | number): string {
  const d = Math.round(Number(days));
  if (Math.abs(d) < 3) return "on time";
  return d > 0 ? `about ${String(d)} days late` : `about ${String(-d)} days early`;
}

/** The end of a delay range in words: "40 days late", "5 days early", "on time". */
function daysEnd(days: number): string {
  const d = Math.round(days);
  if (d === 0) return "on time";
  return d > 0 ? `${String(d)} days late` : `${String(-d)} days early`;
}

/**
 * The likely range of a delay forecast: "likely 40 to 100 days late", "likely 5 days early to 30 days
 * late". Shown with every forecast: the number alone would look more certain than it is.
 */
export function delayRangeText(range: Range): string {
  const low = Math.round(range.low);
  const high = Math.round(range.high);
  if (low > 0) return `likely ${String(low)} to ${String(high)} days late`;
  if (high < 0) return `likely ${String(-high)} to ${String(-low)} days early`;
  return `likely ${daysEnd(low)} to ${daysEnd(high)}`;
}

function pctEnd(pct: number): string {
  if (Math.abs(pct) < 0.05) return "on budget";
  return pct > 0 ? `${pct.toFixed(1)}% over budget` : `${(-pct).toFixed(1)}% under budget`;
}

/** "likely 1.0% to 10.2% over budget", "likely 2.0% under budget to 4.5% over budget". */
export function overrunRangeText(range: Range): string {
  if (range.low >= 0.05) return `likely ${range.low.toFixed(1)}% to ${range.high.toFixed(1)}% over budget`;
  if (range.high <= -0.05) return `likely ${(-range.high).toFixed(1)}% to ${(-range.low).toFixed(1)}% under budget`;
  return `likely ${pctEnd(range.low)} to ${pctEnd(range.high)}`;
}

/** "likely 55 to 88" (or "likely 100" when both ends round to the same score). */
export function scoreRangeText(range: Range): string {
  return range.low === range.high ? `likely ${String(range.low)}` : `likely ${String(range.low)} to ${String(range.high)}`;
}

/** Said where a score made before risk model v2 has no range. */
export const NO_RANGE_TEXT = "range from the next scoring";

export function overrunText(pct: string | number): string {
  const p = Number(pct);
  if (Math.abs(p) < 0.5) return "on budget";
  return p > 0 ? `${p.toFixed(1)}% over budget` : `${(-p).toFixed(1)}% under budget`;
}

/** What a driver did to the forecast: "adds 6.8 days", "saves 2.1 days", "adds 0.4% cost". */
export function driverEffect(driver: Driver): string {
  const parts: string[] = [];
  if (Math.abs(driver.delay_days) >= 0.5) {
    parts.push(`${driver.delay_days > 0 ? "adds" : "saves"} ${Math.abs(driver.delay_days).toFixed(1)} days`);
  }
  if (Math.abs(driver.overrun_pct) >= 0.1) {
    parts.push(`${driver.overrun_pct > 0 ? "adds" : "saves"} ${Math.abs(driver.overrun_pct).toFixed(1)}% cost`);
  }
  return parts.join(", ") || "little effect";
}

/** Does this driver push the forecast up (worse) overall? */
export function raisesRisk(driver: Driver): boolean {
  return driver.delay_days + driver.overrun_pct * 5 > 0;
}

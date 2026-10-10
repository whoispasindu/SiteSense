import type { Driver, RiskLevel } from "../../api/risk";
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

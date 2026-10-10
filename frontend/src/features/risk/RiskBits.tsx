import type { Driver, RiskLevel } from "../../api/risk";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { driverEffect, LEVEL_LABELS, LEVEL_TONES, raisesRisk } from "./risk";

export function RiskBadge({ level }: { level: RiskLevel }) {
  return <StatusBadge tone={LEVEL_TONES[level]} label={`${LEVEL_LABELS[level]} risk`} />;
}

/**
 * The 0 to 100 score on a drawn scale: Low, Medium and High bands with hairline ticks at the BR-10
 * thresholds (40 and 70), and a marker at the score. The number and band are also given in text.
 */
export function ScoreScale({ score, level, compact = false }: { score: number; level: RiskLevel; compact?: boolean }) {
  const marker = level === "high" ? "bg-signal-high" : level === "medium" ? "bg-signal-medium" : "bg-signal-low";
  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={score}
      aria-valuetext={`${String(score)} out of 100, ${LEVEL_LABELS[level]} risk`}
      aria-label="Risk score"
      className={compact ? "w-full" : "w-full pt-1"}
    >
      <div className={`relative ${compact ? "h-1.5" : "h-2.5"} rounded-full`}>
        <div className="absolute inset-y-0 left-0 w-[40%] rounded-l-full bg-signal-low-tint" />
        <div className="absolute inset-y-0 left-[40%] w-[30%] bg-signal-medium-tint" />
        <div className="absolute inset-y-0 left-[70%] w-[30%] rounded-r-full bg-signal-high-tint" />
        <span aria-hidden="true" className="absolute -inset-y-1 left-[40%] w-px bg-rule-strong" />
        <span aria-hidden="true" className="absolute -inset-y-1 left-[70%] w-px bg-rule-strong" />
        <span
          aria-hidden="true"
          className={`absolute top-1/2 ${compact ? "size-2.5" : "size-3.5"} -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-paper-raised ${marker} shadow-sm`}
          style={{ left: `${String(Math.min(Math.max(score, 1), 99))}%` }}
        />
      </div>
      {compact ? null : (
        <div aria-hidden="true" className="tabular relative mt-1.5 h-4 text-[0.6875rem] text-ink-faint">
          <span className="absolute left-0">0</span>
          <span className="absolute left-[40%] -translate-x-1/2">40</span>
          <span className="absolute left-[70%] -translate-x-1/2">70</span>
          <span className="absolute right-0">100</span>
        </div>
      )}
    </div>
  );
}

/** What moved the forecast, signals (things the site can act on) before context. */
export function DriverList({ drivers }: { drivers: Driver[] }) {
  const ordered = [...drivers.filter((d) => d.kind === "signal"), ...drivers.filter((d) => d.kind === "context")];
  if (ordered.length === 0) return <p className="text-sm text-ink-faint">No single factor stands out.</p>;
  return (
    <ul aria-label="What moved the forecast" className="divide-y divide-rule">
      {ordered.map((d) => {
        const up = raisesRisk(d);
        return (
          <li key={d.feature} className="flex items-start gap-3 py-2.5">
            <span
              aria-hidden="true"
              className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-xs font-semibold ${
                up ? "bg-signal-high-tint text-signal-high" : "bg-signal-low-tint text-signal-low"
              }`}
            >
              {up ? "↑" : "↓"}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink">
                {d.label}
                <span className="font-normal text-ink-soft">: {d.value}</span>
                {d.kind === "context" ? <span className="ml-2 text-xs text-ink-faint">(context)</span> : null}
              </p>
              <p className="text-xs text-ink-faint">
                <span className="sr-only">{up ? "Raises the forecast: " : "Lowers the forecast: "}</span>
                {driverEffect(d)}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

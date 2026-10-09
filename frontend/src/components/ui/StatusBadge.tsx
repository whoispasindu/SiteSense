export type Tone = "ok" | "warn" | "down" | "idle";

const TONES: Record<Tone, string> = {
  ok: "bg-signal-low-tint text-signal-low",
  warn: "bg-signal-medium-tint text-signal-medium",
  down: "bg-signal-high-tint text-signal-high",
  idle: "bg-paper-sunk text-ink-faint",
};

interface StatusBadgeProps {
  tone: Tone;
  /** Always shown: colour is never the only signal. */
  label: string;
  pulse?: boolean;
}

export function StatusBadge({ tone, label, pulse = false }: StatusBadgeProps) {
  return (
    <span
      className={`font-wide inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[0.68rem] font-bold tracking-[0.14em] uppercase ${TONES[tone]}`}
    >
      <span
        aria-hidden="true"
        className={`size-1.5 rounded-full bg-current ${pulse ? "animate-pulse-dot" : ""}`}
      />
      {label}
    </span>
  );
}

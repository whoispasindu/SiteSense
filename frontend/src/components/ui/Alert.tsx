import type { ReactNode } from "react";

type Tone = "error" | "warn" | "info" | "success";

const TONES: Record<Tone, { box: string; label: string }> = {
  error: { box: "border-signal-high bg-signal-high-tint text-signal-high", label: "Stop" },
  warn: { box: "border-signal-medium bg-signal-medium-tint text-signal-medium", label: "Caution" },
  info: { box: "border-survey/40 bg-paper-sunk text-ink", label: "Note" },
  success: { box: "border-signal-low bg-signal-low-tint text-signal-low", label: "Done" },
};

/** Site-signage style message. The tone word is always printed, never colour alone. */
export function Alert({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  const style = TONES[tone];
  return (
    <div
      role={tone === "error" || tone === "warn" ? "alert" : "status"}
      className={`flex gap-3 rounded-[var(--radius-sheet)] border-l-4 px-4 py-3 text-sm ${style.box}`}
    >
      <span className="font-wide shrink-0 pt-0.5 text-[0.65rem] font-extrabold tracking-[0.18em] uppercase">
        {style.label}
      </span>
      <div className="min-w-0 text-ink">
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={title ? "mt-0.5 text-ink-soft" : ""}>{children}</div>
      </div>
    </div>
  );
}

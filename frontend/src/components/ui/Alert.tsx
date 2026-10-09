import type { ReactNode } from "react";

type Tone = "error" | "warn" | "info" | "success";

const TONES: Record<Tone, string> = {
  error: "border-signal-high/30 bg-signal-high-tint text-signal-high",
  warn: "border-signal-medium/30 bg-signal-medium-tint text-signal-medium",
  info: "border-rule bg-paper-sunk text-survey",
  success: "border-signal-low/30 bg-signal-low-tint text-signal-low",
};

const ICONS: Record<Tone, ReactNode> = {
  error: <path d="M12 8v5m0 3h.01M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />,
  warn: <path d="M12 8v5m0 3h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" />,
  info: <path d="M12 11v5m0-8h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" />,
  success: <path d="m8.5 12.5 2.5 2.5 5-5.5M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" />,
};

/** Message banner. Meaning is always carried by the text, the colour and icon only reinforce it. */
export function Alert({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <div
      role={tone === "error" || tone === "warn" ? "alert" : "status"}
      className={`flex gap-3 rounded-lg border px-4 py-3 text-sm ${TONES[tone]}`}
    >
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="mt-0.5 size-[18px] shrink-0"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {ICONS[tone]}
      </svg>
      <div className="min-w-0 text-ink">
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={title ? "mt-0.5 text-ink-soft" : ""}>{children}</div>
      </div>
    </div>
  );
}

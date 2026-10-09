import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  // Hi-vis yellow is reserved for the one primary action on a screen. Text stays dark in both themes.
  primary: "border-transparent bg-hivis text-[#1b1a17] shadow-[var(--shadow-sheet)] hover:bg-hivis-deep",
  secondary: "border-rule-strong bg-paper-raised text-ink hover:bg-paper-sunk",
  ghost: "border-transparent bg-transparent text-ink-soft hover:bg-paper-sunk hover:text-ink",
  danger: "border-transparent bg-signal-high-tint text-signal-high hover:brightness-95",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({ variant = "secondary", className = "", type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

/** Same look as a primary button, for links (navigation must stay a link, not a button). */
export const primaryLinkClass =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-transparent bg-hivis px-4 text-sm font-medium text-[#1b1a17] shadow-[var(--shadow-sheet)] transition-colors hover:bg-hivis-deep";

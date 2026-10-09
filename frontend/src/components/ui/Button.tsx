import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  // Hi-vis yellow is reserved for the one primary action on a screen.
  primary:
    "bg-hivis text-ink border-ink shadow-[3px_3px_0_0_var(--color-ink)] hover:bg-hivis-deep active:translate-x-[2px] active:translate-y-[2px] active:shadow-[1px_1px_0_0_var(--color-ink)]",
  secondary: "bg-paper-raised text-ink border-rule-strong hover:border-ink",
  ghost: "bg-transparent text-ink-soft border-transparent hover:text-ink hover:bg-paper-sunk",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({ variant = "secondary", className = "", type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={`font-wide inline-flex min-h-11 items-center justify-center gap-2 rounded-[var(--radius-sheet)] border-2 px-4 text-xs font-bold tracking-[0.12em] uppercase transition-[background-color,border-color,transform,box-shadow] duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

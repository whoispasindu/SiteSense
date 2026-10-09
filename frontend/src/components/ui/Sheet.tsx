import type { HTMLAttributes, ReactNode } from "react";

interface SheetProps extends HTMLAttributes<HTMLElement> {
  /** Drawing reference printed in the corner, e.g. "S-02". Decorative. */
  sheetCode?: string;
  as?: "section" | "article" | "div";
  children: ReactNode;
}

/** A drawing sheet: the base surface for every panel in SiteSense. */
export function Sheet({ sheetCode, as: Tag = "section", className = "", children, ...props }: SheetProps) {
  return (
    <Tag
      className={`relative rounded-[var(--radius-sheet)] border border-rule bg-paper-raised shadow-[var(--shadow-sheet)] ${className}`}
      {...props}
    >
      {sheetCode ? (
        <span
          aria-hidden="true"
          className="absolute top-0 right-0 border-b border-l border-rule px-2 py-0.5 font-mono text-[0.65rem] tracking-wider text-ink-faint"
        >
          {sheetCode}
        </span>
      ) : null}
      {children}
    </Tag>
  );
}
